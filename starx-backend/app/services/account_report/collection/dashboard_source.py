"""从数据看板每日快照读取账号报告所需的当前账号证据。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any, Callable
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.db.models import (
    AccountRecord,
    DashboardAccountSnapshotRecord,
    DashboardContentSnapshotRecord,
    OwnContentMetricSnapshotRecord,
    OwnSocialContentRecord,
)
from app.services.mediaspider.models import CrawlResult
from app.services.own_content_analytics import OwnContentAnalyticsService
from app.services.tikhub_service import TikHubProvider, default_tikhub_provider

from .platforms import canonical_platform, owner_identifiers

BUSINESS_TIMEZONE = ZoneInfo("Asia/Shanghai")
SUPPORTED_DASHBOARD_PLATFORMS = {"小红书", "抖音"}
CONTENT_ID_FIELDS = {
    "xhs": ("note_id", "note_url"),
    "dy": ("aweme_id", "aweme_url"),
}


@dataclass(frozen=True)
class DashboardAccountEvidence:
    results: list[CrawlResult] = field(default_factory=list)
    owner_hashes: set[str] = field(default_factory=set)
    failures: list[dict[str, str]] = field(default_factory=list)


class AccountDashboardSource:
    """先生成账号数据看板，再把同一份快照适配为报告证据。"""

    def __init__(
        self,
        *,
        session_factory: Callable[[], Session] = SessionLocal,
        provider: TikHubProvider = default_tikhub_provider,
    ) -> None:
        self._session_factory = session_factory
        self._provider = provider

    async def prepare(
        self,
        *,
        user_id: str,
        account_id: str,
        platform_names: list[str],
    ) -> DashboardAccountEvidence:
        observed_date = datetime.now(UTC).astimezone(BUSINESS_TIMEZONE).date()
        failures: list[dict[str, str]] = []

        for platform_name in platform_names:
            if platform_name not in SUPPORTED_DASHBOARD_PLATFORMS:
                continue
            with self._session_factory() as session:
                analytics = OwnContentAnalyticsService(
                    session, tikhub_provider=self._provider
                )
                try:
                    await analytics.refresh(
                        user_id=user_id,
                        account_id=account_id,
                        platform_name=platform_name,
                    )
                except Exception:
                    dashboard = analytics.build(
                        user_id=user_id,
                        account_id=account_id,
                        platform_name=platform_name,
                        days=30,
                    )
                else:
                    dashboard = analytics.build(
                        user_id=user_id,
                        account_id=account_id,
                        platform_name=platform_name,
                        days=30,
                    )
            if dashboard.status != "ready":
                failures.append(
                    {
                        "platform": platform_name,
                        "mode": "dashboard",
                        "reason": (
                            dashboard.notices[0]
                            if dashboard.notices
                            else "账号数据看板生成失败"
                        ),
                    }
                )

        with self._session_factory() as session:
            results = load_dashboard_crawl_results(
                session,
                account_id=account_id,
                platform_names=platform_names,
                observed_date=observed_date,
            )
        return DashboardAccountEvidence(
            results=results,
            owner_hashes={
                owner_hash
                for result in results
                for owner_hash in owner_identifiers(result)
            },
            failures=failures,
        )


def load_dashboard_crawl_results(
    session: Session,
    *,
    account_id: str,
    platform_names: list[str],
    observed_date: date,
) -> list[CrawlResult]:
    """将指定业务日的看板主页与作品快照转换为报告采集模型。"""

    account = session.get(AccountRecord, account_id)
    if account is None:
        return []
    identities = dict(account.platform_account_identities or {})
    platform_accounts = dict(account.platform_accounts or {})
    results: list[CrawlResult] = []

    for platform_name in platform_names:
        canonical = canonical_platform(platform_name)
        if canonical is None or platform_name not in SUPPORTED_DASHBOARD_PLATFORMS:
            continue
        _, platform_code = canonical
        account_snapshot = session.scalar(
            select(DashboardAccountSnapshotRecord).where(
                DashboardAccountSnapshotRecord.account_id == account_id,
                DashboardAccountSnapshotRecord.platform == platform_name,
                DashboardAccountSnapshotRecord.observed_date == observed_date,
            )
        )
        if account_snapshot is None:
            contents = _own_hourly_contents(
                session,
                account_id=account_id,
                platform_code=platform_code,
                identity=dict(identities.get(platform_name) or {}),
                display_name=account.name,
            )
            if contents:
                identity = dict(identities.get(platform_name) or {})
                profile_url = str(identity.get("profileUrl") or "")
                results.append(
                    CrawlResult(
                        platform=platform_code,
                        crawl_type="creator",
                        creator_url=profile_url or None,
                        creators=[],
                        contents=contents,
                        content_count=len(contents),
                        source_operations=["own_content_metric_snapshot"],
                    )
                )
            continue
        identity = dict(identities.get(platform_name) or {})
        owner_id = str(
            identity.get("userId")
            or identity.get("accountId")
            or platform_accounts.get(platform_name)
            or ""
        ).strip()
        profile_url = str(identity.get("profileUrl") or "")
        display_name = str(identity.get("displayName") or account.name)
        creators = [
            {
                "user_id": owner_id,
                "nickname": display_name,
                "display_name": display_name,
                "profile_url": profile_url,
                "fans_count": account_snapshot.followers,
                "follows_count": account_snapshot.follows,
                "works_count": account_snapshot.content_count,
                "liked_count": account_snapshot.total_likes,
                "source_operation": "dashboard_account_snapshot",
                "evidence_completeness": 1.0,
            }
        ]
        contents = _dashboard_contents(
            session,
            account_id=account_id,
            platform_name=platform_name,
            platform_code=platform_code,
            owner_id=owner_id,
            display_name=display_name,
            profile_url=profile_url,
            observed_date=observed_date,
        )
        results.append(
            CrawlResult(
                platform=platform_code,
                crawl_type="creator",
                creator_url=profile_url or None,
                creators=creators,
                contents=contents,
                creator_count=1,
                content_count=len(contents),
                source_operations=["dashboard_account_snapshot"],
            )
        )
    return results


def _dashboard_contents(
    session: Session,
    *,
    account_id: str,
    platform_name: str,
    platform_code: str,
    owner_id: str,
    display_name: str,
    profile_url: str,
    observed_date: date,
) -> list[dict[str, Any]]:
    id_field, url_field = CONTENT_ID_FIELDS[platform_code]
    snapshots = session.scalars(
        select(DashboardContentSnapshotRecord)
        .where(
            DashboardContentSnapshotRecord.account_id == account_id,
            DashboardContentSnapshotRecord.platform == platform_name,
            DashboardContentSnapshotRecord.observed_date == observed_date,
        )
        .order_by(DashboardContentSnapshotRecord.id)
    ).all()
    return [
        {
            id_field: item.content_id,
            url_field: item.content_url,
            "user_id": owner_id,
            "nickname": display_name,
            "display_name": display_name,
            "profile_url": profile_url,
            "title": item.title,
            "cover_url": item.cover_url,
            "content_type": item.content_type,
            "create_time": item.published_at,
            "view_count": item.views,
            "liked_count": item.likes,
            "comment_count": item.comments,
            "share_count": item.shares,
            "collected_count": item.favorites,
            "source_operation": "dashboard_content_snapshot",
        }
        for item in snapshots
    ]


def _own_hourly_contents(
    session: Session,
    *,
    account_id: str,
    platform_code: str,
    identity: dict[str, object],
    display_name: str,
) -> list[dict[str, Any]]:
    id_field, url_field = CONTENT_ID_FIELDS[platform_code]
    owner_id = str(identity.get("userId") or identity.get("accountId") or "")
    profile_url = str(identity.get("profileUrl") or "")
    contents = session.scalars(
        select(OwnSocialContentRecord)
        .where(
            OwnSocialContentRecord.account_id == account_id,
            OwnSocialContentRecord.platform == platform_code,
        )
        .order_by(OwnSocialContentRecord.published_at.desc().nullslast())
        .limit(50)
    ).all()
    rows: list[dict[str, Any]] = []
    for content in contents:
        snapshot = session.scalar(
            select(OwnContentMetricSnapshotRecord)
            .where(OwnContentMetricSnapshotRecord.content_id == content.id)
            .order_by(OwnContentMetricSnapshotRecord.captured_at.desc())
        )
        if snapshot is None:
            continue
        rows.append(
            {
                id_field: content.platform_content_id,
                url_field: content.content_url,
                "user_id": owner_id,
                "nickname": display_name,
                "display_name": display_name,
                "profile_url": profile_url,
                "title": content.title,
                "cover_url": content.cover_url,
                "content_type": content.content_type,
                "create_time": (
                    content.published_at.isoformat() if content.published_at else ""
                ),
                "liked_count": snapshot.likes,
                "comment_count": snapshot.comments,
                "share_count": snapshot.shares,
                "collected_count": snapshot.favorites,
                "source_operation": "own_content_metric_snapshot",
            }
        )
    return rows
