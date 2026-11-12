"""数据看板的 TikHub 采集、身份缓存与每日快照编排。"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import (
    AccountRecord,
    DashboardAccountSnapshotRecord,
    DashboardContentSnapshotRecord,
)
from app.schemas.dashboards import SocialDashboardSchema
from app.services.tikhub_service import (
    TikHubAccount,
    TikHubAccountContentsRequest,
    TikHubContent,
    TikHubPlatform,
    TikHubProvider,
)

from .aggregation import build_social_dashboard
from .identity import PLATFORM_MAP, resolve_platform_account

BUSINESS_TIMEZONE = ZoneInfo("Asia/Shanghai")


class SocialDashboardService:
    def __init__(self, session: Session, provider: TikHubProvider) -> None:
        self.session = session
        self.provider = provider

    async def build(
        self,
        *,
        user_id: str,
        account_id: str,
        platform_name: str,
        days: int,
        force_refresh: bool = False,
    ) -> SocialDashboardSchema:
        record = self.session.scalar(
            select(AccountRecord).where(
                AccountRecord.id == account_id,
                AccountRecord.user_id == user_id,
                AccountRecord.status == "active",
            )
        )
        if record is None:
            raise StopIteration(account_id)
        platform_accounts = dict(record.platform_accounts or {})
        handle = str(platform_accounts.get(platform_name) or "").strip()
        if not handle:
            return SocialDashboardSchema(
                status="unconfigured",
                platform=platform_name,
                days=days,
                notices=[f"请先在账号档案中配置{platform_name}号"],
            )

        identities = dict(record.platform_account_identities or {})
        observed_date = datetime.now(UTC).astimezone(BUSINESS_TIMEZONE).date()
        if not force_refresh:
            cached = self._build_from_daily_snapshot(
                account_id=account_id,
                platform_name=platform_name,
                platform_account=handle,
                identity=dict(identities.get(platform_name) or {}),
                observed_date=observed_date,
                days=days,
            )
            if cached is not None:
                return cached

        try:
            account, identity = await resolve_platform_account(
                self.provider,
                platform_name=platform_name,
                platform_account=handle,
                cached=identities.get(platform_name),
            )
        except Exception as exc:
            return SocialDashboardSchema(
                status="unavailable",
                platform=platform_name,
                platformAccount=handle,
                days=days,
                notices=[f"TikHub 暂时无法获取{platform_name}账号数据：{type(exc).__name__}"],
            )
        if account is None or identity is None:
            return SocialDashboardSchema(
                status="unresolved",
                platform=platform_name,
                platformAccount=handle,
                days=days,
                notices=[f"未找到与“{handle}”精确匹配的{platform_name}账号"],
            )
        identities[platform_name] = identity
        record.platform_account_identities = identities

        social_platform = PLATFORM_MAP[platform_name]
        try:
            page = await self.provider.list_account_contents(
                TikHubAccountContentsRequest(
                    platform=social_platform,
                    accountId=account.userId,
                    secUserId=(
                        account.userId
                        if social_platform == TikHubPlatform.DOUYIN
                        else ""
                    ),
                    pageSize=20,
                )
            )
        except Exception as exc:
            return SocialDashboardSchema(
                status="unavailable",
                platform=platform_name,
                platformAccount=handle,
                displayName=account.name,
                days=days,
                notices=[f"TikHub 暂时无法获取作品数据：{type(exc).__name__}"],
            )
        contents = page.contents
        notices: list[str] = []

        observed_at = datetime.now(UTC)
        captured_date = observed_at.astimezone(BUSINESS_TIMEZONE).date()
        previous_followers = self._previous_followers(
            account_id, platform_name, days, captured_date
        )
        self._save_snapshots(
            account_id=account_id,
            platform_name=platform_name,
            account=account,
            contents=contents,
            observed_at=observed_at,
            observed_date=captured_date,
        )
        self.session.commit()
        return build_social_dashboard(
            platform_name=platform_name,
            platform_account=handle,
            account=account,
            contents=contents,
            days=days,
            previous_followers=previous_followers,
            now=observed_at,
            notices=notices,
        )

    def _build_from_daily_snapshot(
        self,
        *,
        account_id: str,
        platform_name: str,
        platform_account: str,
        identity: dict[str, object],
        observed_date: date,
        days: int,
    ) -> SocialDashboardSchema | None:
        account_snapshot = self.session.scalar(
            select(DashboardAccountSnapshotRecord).where(
                DashboardAccountSnapshotRecord.account_id == account_id,
                DashboardAccountSnapshotRecord.platform == platform_name,
                DashboardAccountSnapshotRecord.observed_date == observed_date,
            )
        )
        if account_snapshot is None:
            return None

        content_snapshots = self.session.scalars(
            select(DashboardContentSnapshotRecord)
            .where(
                DashboardContentSnapshotRecord.account_id == account_id,
                DashboardContentSnapshotRecord.platform == platform_name,
                DashboardContentSnapshotRecord.observed_date == observed_date,
            )
            .order_by(DashboardContentSnapshotRecord.id)
        ).all()
        social_platform = PLATFORM_MAP[platform_name]
        account = TikHubAccount(
            platform=social_platform,
            accountId=str(identity.get("accountId") or platform_account),
            userId=str(identity.get("userId") or ""),
            name=str(identity.get("displayName") or ""),
            profileUrl=str(identity.get("profileUrl") or ""),
            followers=account_snapshot.followers,
            follows=account_snapshot.follows,
            contentCount=account_snapshot.content_count,
            totalLikes=account_snapshot.total_likes,
        )
        contents = [
            TikHubContent(
                platform=social_platform,
                contentId=item.content_id,
                title=item.title,
                contentUrl=item.content_url,
                coverUrl=item.cover_url,
                contentType=item.content_type,
                publishedAt=item.published_at,
                readCount=item.views,
                likeCount=item.likes,
                commentCount=item.comments,
                shareCount=item.shares,
                collectCount=item.favorites,
            )
            for item in content_snapshots
        ]
        observed_at = account_snapshot.observed_at
        if observed_at.tzinfo is None:
            observed_at = observed_at.replace(tzinfo=UTC)
        return build_social_dashboard(
            platform_name=platform_name,
            platform_account=platform_account,
            account=account,
            contents=contents,
            days=days,
            previous_followers=self._previous_followers(
                account_id, platform_name, days, observed_date
            ),
            now=observed_at,
        )

    def _previous_followers(
        self,
        account_id: str,
        platform_name: str,
        days: int,
        observed_date: date,
    ) -> int | None:
        cutoff = observed_date - timedelta(days=days)
        snapshot = self.session.scalar(
            select(DashboardAccountSnapshotRecord)
            .where(
                DashboardAccountSnapshotRecord.account_id == account_id,
                DashboardAccountSnapshotRecord.platform == platform_name,
                DashboardAccountSnapshotRecord.observed_date <= cutoff,
            )
            .order_by(DashboardAccountSnapshotRecord.observed_date.desc())
        )
        return snapshot.followers if snapshot is not None else None

    def _save_snapshots(
        self,
        *,
        account_id: str,
        platform_name: str,
        account,
        contents,
        observed_at: datetime,
        observed_date: date,
    ) -> None:
        account_snapshot = self.session.scalar(
            select(DashboardAccountSnapshotRecord).where(
                DashboardAccountSnapshotRecord.account_id == account_id,
                DashboardAccountSnapshotRecord.platform == platform_name,
                DashboardAccountSnapshotRecord.observed_date == observed_date,
            )
        )
        if account_snapshot is None:
            account_snapshot = DashboardAccountSnapshotRecord(
                account_id=account_id,
                platform=platform_name,
                observed_date=observed_date,
            )
            self.session.add(account_snapshot)
        account_snapshot.followers = account.followers
        account_snapshot.follows = account.follows
        account_snapshot.content_count = account.contentCount
        account_snapshot.total_likes = account.totalLikes
        account_snapshot.observed_at = observed_at

        for content in contents:
            snapshot = self.session.scalar(
                select(DashboardContentSnapshotRecord).where(
                    DashboardContentSnapshotRecord.account_id == account_id,
                    DashboardContentSnapshotRecord.platform == platform_name,
                    DashboardContentSnapshotRecord.content_id == content.contentId,
                    DashboardContentSnapshotRecord.observed_date == observed_date,
                )
            )
            if snapshot is None:
                snapshot = DashboardContentSnapshotRecord(
                    account_id=account_id,
                    platform=platform_name,
                    content_id=content.contentId,
                    observed_date=observed_date,
                )
                self.session.add(snapshot)
            snapshot.title = content.title or content.description
            snapshot.content_url = content.contentUrl
            snapshot.cover_url = content.coverUrl
            snapshot.content_type = content.contentType or "unknown"
            snapshot.published_at = content.publishedAt
            snapshot.views = content.readCount
            snapshot.likes = content.likeCount
            snapshot.comments = content.commentCount
            snapshot.shares = content.shareCount
            snapshot.favorites = content.collectCount
            snapshot.observed_at = observed_at
