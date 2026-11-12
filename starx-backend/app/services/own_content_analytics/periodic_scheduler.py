"""自有账号作品数据的小时级周期调度器。"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.core.config import settings
from app.core.database import SessionLocal
from app.core.logging import get_logger
from app.db.models import AccountRecord, OwnDashboardSyncStateRecord

from .refresh_jobs import DashboardRefreshJobService
from .service import OwnContentAnalyticsService

logger = get_logger(__name__)


class OwnDashboardPeriodicScheduler:
    def __init__(self) -> None:
        self._stop_event: asyncio.Event | None = None
        self._wake_event: asyncio.Event | None = None
        self._task: asyncio.Task[None] | None = None

    @property
    def is_running(self) -> bool:
        return self._task is not None and not self._task.done()

    def start(self) -> None:
        if self.is_running:
            return
        self._stop_event = asyncio.Event()
        self._wake_event = asyncio.Event()
        self._task = asyncio.create_task(
            self._run(), name="own-dashboard-periodic-scheduler"
        )

    def notify(self) -> None:
        """有手动任务入队时唤醒扫描器，避免等待固定扫描周期。"""
        if self._wake_event is not None:
            self._wake_event.set()

    async def stop(self) -> None:
        if self._task is None:
            return
        if self._stop_event is not None:
            self._stop_event.set()
        if self._wake_event is not None:
            self._wake_event.set()
        await self._task
        self._task = None
        self._stop_event = None
        self._wake_event = None

    async def scan_once(self) -> int:
        now = datetime.now(UTC)
        with SessionLocal() as session:
            manual_job_ids = DashboardRefreshJobService(session).claim_pending(
                settings.OWN_DASHBOARD_SCHEDULER_BATCH_SIZE
            )
        for refresh_id in manual_job_ids:
            try:
                with SessionLocal() as session:
                    await DashboardRefreshJobService(session).execute_claimed(
                        refresh_id
                    )
            except Exception:
                logger.exception(
                    "own dashboard manual refresh failed refresh_id=%s",
                    refresh_id,
                )

        claimed: list[tuple[str, str, str]] = []
        with SessionLocal() as session:
            accounts = session.scalars(
                select(AccountRecord).where(AccountRecord.status == "active")
            ).all()
            for account in accounts:
                platform_accounts = dict(account.platform_accounts or {})
                for platform_name in ("抖音", "小红书"):
                    if (
                        platform_name not in (account.platforms or [])
                        or not str(platform_accounts.get(platform_name) or "").strip()
                    ):
                        continue
                    state = session.scalar(
                        select(OwnDashboardSyncStateRecord).where(
                            OwnDashboardSyncStateRecord.account_id == account.id,
                            OwnDashboardSyncStateRecord.platform == platform_name,
                        )
                    )
                    if state is None:
                        state = OwnDashboardSyncStateRecord(
                            account_id=account.id,
                            platform=platform_name,
                            next_refresh_at=now,
                        )
                        session.add(state)
                        session.flush()
                    if (
                        state.enabled
                        and state.next_refresh_at <= now
                        and (
                            state.locked_until is None
                            or state.locked_until <= now
                        )
                        and len(claimed)
                        < settings.OWN_DASHBOARD_SCHEDULER_BATCH_SIZE
                    ):
                        state.locked_until = now + timedelta(minutes=30)
                        claimed.append((account.user_id, account.id, platform_name))
            session.commit()

        for user_id, account_id, platform_name in claimed:
            try:
                with SessionLocal() as session:
                    await OwnContentAnalyticsService(session).refresh(
                        user_id=user_id,
                        account_id=account_id,
                        platform_name=platform_name,
                    )
            except Exception:
                logger.exception(
                    "own dashboard refresh failed account_id=%s platform=%s",
                    account_id,
                    platform_name,
                )
        return len(manual_job_ids) + len(claimed)

    async def _run(self) -> None:
        stop_event = self._stop_event
        wake_event = self._wake_event
        if stop_event is None or wake_event is None:
            return
        while not stop_event.is_set():
            try:
                await self.scan_once()
            except Exception:
                logger.exception("own dashboard periodic scan failed")
            try:
                await asyncio.wait_for(
                    wake_event.wait(),
                    timeout=settings.OWN_DASHBOARD_SCHEDULER_SCAN_SECONDS,
                )
            except TimeoutError:
                pass
            finally:
                wake_event.clear()


own_dashboard_periodic_scheduler = OwnDashboardPeriodicScheduler()
