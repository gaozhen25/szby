"""数据看板轻量异步刷新任务。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models import (
    AccountRecord,
    OwnDashboardRefreshJobRecord,
    OwnDashboardSyncStateRecord,
)
from app.schemas.dashboards import DashboardRefreshJobSchema
from app.services.social_retrieval import backend_for_platform

from app.services.mediaspider.http_platforms.common.cookies import (
    get_user_bound_platform_entry,
)

from .service import OwnContentAnalyticsService, PLATFORM_CODES

ACTIVE_STATUSES = ("pending", "running")
STALE_AFTER = timedelta(minutes=30)


def serialize_refresh_job(
    record: OwnDashboardRefreshJobRecord,
) -> DashboardRefreshJobSchema:
    message = (
        record.error_message
        if record.status == "failed"
        else {
            "pending": "刷新任务已进入队列",
            "running": "正在采集作品互动数据",
            "succeeded": f"已更新 {record.item_count} 篇作品",
        }.get(record.status, "")
    )
    return DashboardRefreshJobSchema(
        refreshId=record.id,
        accountId=record.account_id,
        platform=record.platform,
        provider=record.provider,
        status=record.status,
        stage=record.stage,
        progress=record.progress,
        itemCount=record.item_count,
        message=message,
        createdAt=record.created_at.isoformat(),
        startedAt=record.started_at.isoformat() if record.started_at else None,
        finishedAt=record.finished_at.isoformat() if record.finished_at else None,
    )


class DashboardRefreshJobService:
    def __init__(self, session: Session, *, runtime_settings=settings) -> None:
        self.session = session
        self.settings = runtime_settings

    def enqueue(
        self,
        *,
        user_id: str,
        account_id: str,
        platform_name: str,
    ) -> DashboardRefreshJobSchema:
        account = self.session.scalar(
            select(AccountRecord).where(
                AccountRecord.id == account_id,
                AccountRecord.user_id == user_id,
                AccountRecord.status == "active",
            )
        )
        if account is None:
            raise StopIteration(account_id)
        if platform_name not in PLATFORM_CODES:
            raise ValueError(f"请先配置{platform_name}号")
        handle = str((account.platform_accounts or {}).get(platform_name) or "").strip()
        if not handle:
            code = PLATFORM_CODES[platform_name]
            bound = get_user_bound_platform_entry(user_id, code)
            handle = str((bound or {}).get("accountId") or "").strip()
            if handle:
                platform_accounts = dict(account.platform_accounts or {})
                platform_accounts[platform_name] = handle
                account.platform_accounts = platform_accounts
                platforms = list(account.platforms or [])
                if platform_name not in platforms:
                    platforms.append(platform_name)
                    account.platforms = platforms
        if not handle:
            raise ValueError(
                f"请先配置{platform_name}号，或先完成{platform_name}浏览器扫码登录"
            )

        existing = self.session.scalar(
            select(OwnDashboardRefreshJobRecord)
            .where(
                OwnDashboardRefreshJobRecord.account_id == account_id,
                OwnDashboardRefreshJobRecord.user_id == user_id,
                OwnDashboardRefreshJobRecord.platform == platform_name,
                OwnDashboardRefreshJobRecord.status.in_(ACTIVE_STATUSES),
            )
            .order_by(OwnDashboardRefreshJobRecord.created_at.desc())
        )
        if existing is not None:
            return serialize_refresh_job(existing)

        now = datetime.now(UTC)
        provider = backend_for_platform(
            self.settings, PLATFORM_CODES[platform_name]
        ).value
        record = OwnDashboardRefreshJobRecord(
            id=f"dashref_{uuid4().hex}",
            account_id=account_id,
            user_id=user_id,
            platform=platform_name,
            provider=provider,
            status="pending",
            stage="queued",
            progress=0,
            created_at=now,
            updated_at=now,
        )
        self.session.add(record)

        state = self.session.scalar(
            select(OwnDashboardSyncStateRecord).where(
                OwnDashboardSyncStateRecord.account_id == account_id,
                OwnDashboardSyncStateRecord.platform == platform_name,
            )
        )
        if state is None:
            state = OwnDashboardSyncStateRecord(
                account_id=account_id,
                platform=platform_name,
                provider=provider,
                next_refresh_at=now,
            )
            self.session.add(state)
        state.locked_until = now + STALE_AFTER
        state.updated_at = now
        self.session.commit()
        return serialize_refresh_job(record)

    def get(
        self, *, user_id: str, account_id: str, refresh_id: str
    ) -> DashboardRefreshJobSchema:
        record = self.session.scalar(
            select(OwnDashboardRefreshJobRecord).where(
                OwnDashboardRefreshJobRecord.id == refresh_id,
                OwnDashboardRefreshJobRecord.account_id == account_id,
                OwnDashboardRefreshJobRecord.user_id == user_id,
            )
        )
        if record is None:
            raise StopIteration(refresh_id)
        return serialize_refresh_job(record)

    def claim_pending(self, limit: int) -> list[str]:
        now = datetime.now(UTC)
        stale_before = now - STALE_AFTER
        stale = self.session.scalars(
            select(OwnDashboardRefreshJobRecord).where(
                OwnDashboardRefreshJobRecord.status == "running",
                OwnDashboardRefreshJobRecord.updated_at <= stale_before,
            )
        ).all()
        for record in stale:
            record.status = "pending"
            record.stage = "queued"
            record.progress = 0
            record.started_at = None
            record.updated_at = now

        records = self.session.scalars(
            select(OwnDashboardRefreshJobRecord)
            .where(OwnDashboardRefreshJobRecord.status == "pending")
            .order_by(OwnDashboardRefreshJobRecord.created_at.asc())
            .limit(limit)
            .with_for_update(skip_locked=True)
        ).all()
        for record in records:
            record.status = "running"
            record.stage = "collecting"
            record.progress = 15
            record.started_at = now
            record.updated_at = now
        self.session.commit()
        return [record.id for record in records]

    async def execute_claimed(self, refresh_id: str) -> None:
        record = self.session.get(OwnDashboardRefreshJobRecord, refresh_id)
        if record is None or record.status != "running":
            return
        try:
            item_count = await OwnContentAnalyticsService(
                self.session, runtime_settings=self.settings
            ).refresh(
                user_id=record.user_id,
                account_id=record.account_id,
                platform_name=record.platform,
            )
        except Exception as exc:
            now = datetime.now(UTC)
            record = self.session.get(OwnDashboardRefreshJobRecord, refresh_id)
            if record is not None:
                record.status = "failed"
                record.stage = "failed"
                record.progress = 100
                record.error_message = str(exc)[:500] or type(exc).__name__
                record.finished_at = now
                record.updated_at = now
                self.session.commit()
            return

        now = datetime.now(UTC)
        record = self.session.get(OwnDashboardRefreshJobRecord, refresh_id)
        if record is not None:
            record.status = "succeeded"
            record.stage = "completed"
            record.progress = 100
            record.item_count = item_count
            record.error_message = ""
            record.finished_at = now
            record.updated_at = now
            self.session.commit()
