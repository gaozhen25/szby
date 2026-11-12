"""自有作品采集、小时快照与看板聚合。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models import (
    AccountRecord,
    OwnContentMetricSnapshotRecord,
    OwnDashboardSyncStateRecord,
    OwnSocialContentRecord,
)
from app.schemas.dashboards import (
    DashboardContentStructureSchema,
    DashboardContentTrendSchema,
    DashboardInsightSchema,
    DashboardMetricSchema,
    DashboardTopContentSchema,
    DashboardTrendPointSchema,
    SocialDashboardSchema,
)
from app.services.competitor_monitoring.normalizers import normalize_video
from app.services.mediaspider.account_lookup import MediaSpiderAccountLookup
from app.services.mediaspider.cookie_pool import (
    PROCESS_COOKIE_CURSOR,
    WorkflowCookiePool,
    load_cookie_pool,
    run_with_cookie_candidates,
)
from app.services.mediaspider.http_platforms.common.cookies import (
    get_user_bound_platform_entry,
    preferred_cookies_for_user,
)
from app.services.mediaspider.service import MediaCrawlerService
from app.services.social_dashboard.identity import PLATFORM_MAP, resolve_platform_account
from app.services.social_retrieval import RetrievalBackend, backend_for_platform
from app.services.tikhub_service import (
    TikHubAccountContentsRequest,
    TikHubPlatform,
    TikHubProvider,
    default_tikhub_provider,
)

PLATFORM_CODES = {"抖音": "dy", "小红书": "xhs"}
PLATFORM_NAMES = {"dy": "抖音", "xhs": "小红书"}
CONTENT_TYPES = {
    "video": "视频",
    "视频": "视频",
    "image": "图文",
    "images": "图文",
    "normal": "图文",
    "图文": "图文",
}


def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _hour(value: datetime) -> datetime:
    return value.astimezone(UTC).replace(minute=0, second=0, microsecond=0)


def _parse_time(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        numeric = int(float(text))
        if numeric > 10_000_000_000:
            numeric //= 1000
        return datetime.fromtimestamp(numeric, tz=UTC)
    except (TypeError, ValueError, OverflowError):
        pass
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return _utc(parsed)
    except ValueError:
        return None


def _metric_sum(values: dict[str, int | None]) -> int | None:
    available = [value for value in values.values() if isinstance(value, int)]
    return sum(available) if available else None


class OwnContentAnalyticsService:
    def __init__(
        self,
        session: Session,
        *,
        tikhub_provider: TikHubProvider = default_tikhub_provider,
        mediaspider: MediaCrawlerService | None = None,
        account_lookup: MediaSpiderAccountLookup | None = None,
        runtime_settings: Any = settings,
    ) -> None:
        self.session = session
        self.tikhub_provider = tikhub_provider
        self.mediaspider = mediaspider or MediaCrawlerService()
        self.account_lookup = account_lookup or MediaSpiderAccountLookup()
        self.settings = runtime_settings

    def _account(self, user_id: str, account_id: str) -> AccountRecord:
        record = self.session.scalar(
            select(AccountRecord).where(
                AccountRecord.id == account_id,
                AccountRecord.user_id == user_id,
                AccountRecord.status == "active",
            )
        )
        if record is None:
            raise StopIteration(account_id)
        return record

    def _state(
        self, account_id: str, platform_name: str, *, create: bool = True
    ) -> OwnDashboardSyncStateRecord | None:
        state = self.session.scalar(
            select(OwnDashboardSyncStateRecord).where(
                OwnDashboardSyncStateRecord.account_id == account_id,
                OwnDashboardSyncStateRecord.platform == platform_name,
            )
        )
        if state is None and create:
            state = OwnDashboardSyncStateRecord(
                account_id=account_id,
                platform=platform_name,
                next_refresh_at=datetime.now(UTC),
            )
            self.session.add(state)
            self.session.flush()
        return state

    def _resolve_platform_handle(
        self, account: AccountRecord, *, user_id: str, platform_name: str
    ) -> str:
        """优先账号档案平台号；为空则回退到该用户扫码绑定的 accountId。"""

        handle = str((account.platform_accounts or {}).get(platform_name) or "").strip()
        if handle:
            return handle
        code = PLATFORM_CODES.get(platform_name)
        if not code:
            return ""
        bound = get_user_bound_platform_entry(user_id, code)
        return str((bound or {}).get("accountId") or "").strip()

    def _ensure_platform_handle(
        self, account: AccountRecord, *, user_id: str, platform_name: str
    ) -> str:
        """解析平台号；若来自扫码绑定则写回账号档案，便于看板后续识别。"""

        handle = self._resolve_platform_handle(
            account, user_id=user_id, platform_name=platform_name
        )
        if not handle:
            return ""
        current = str((account.platform_accounts or {}).get(platform_name) or "").strip()
        if current == handle:
            return handle
        # 重新挂到 session 内账号再写库
        live = self._account(user_id, account.id)
        platform_accounts = dict(live.platform_accounts or {})
        platform_accounts[platform_name] = handle
        live.platform_accounts = platform_accounts
        account.platform_accounts = platform_accounts
        self.session.flush()
        return handle

    def _cookie_pool_for_user(
        self, *, user_id: str, code: str, handle: str
    ) -> WorkflowCookiePool:
        preferred = preferred_cookies_for_user(user_id, code, account_id=handle)
        pool = load_cookie_pool()
        fallback = list(pool.candidates(code) if pool.has_cookies(code) else ())
        ordered = tuple(dict.fromkeys([*preferred, *fallback]))
        cookies = {platform: () for platform in ("xhs", "dy", "ks")}
        cookies[code] = ordered
        return WorkflowCookiePool(cookies, PROCESS_COOKIE_CURSOR)

    async def refresh(
        self, *, user_id: str, account_id: str, platform_name: str
    ) -> int:
        account = self._account(user_id, account_id)
        handle = self._ensure_platform_handle(
            account, user_id=user_id, platform_name=platform_name
        )
        if not handle:
            raise ValueError(
                f"请先配置{platform_name}号，或先完成{platform_name}浏览器扫码登录"
            )
        code = PLATFORM_CODES[platform_name]
        backend = backend_for_platform(self.settings, code)
        state = self._state(account_id, platform_name)
        assert state is not None
        now = datetime.now(UTC)
        state.last_attempt_at = now
        state.provider = backend.value
        # 采集可能持续数分钟。进入外部 I/O 前结束当前数据库事务，避免长时间
        # 占用 PgBouncer 连接，最终让采集后的首条写库查询超时。
        # account 先脱离 Session，使 commit 后仍可作为采集所需的只读快照使用。
        _ = (
            account.platform_accounts,
            account.platform_account_identities,
            account.account_links,
        )
        self.session.expunge(account)
        self.session.commit()
        try:
            raw_items = (
                await self._collect_mediaspider(
                    account, platform_name, code, handle, user_id=user_id
                )
                if backend == RetrievalBackend.MEDIASPIDER
                else await self._collect_tikhub(account, platform_name, handle)
            )
            self._merge_platform_identity(
                user_id=user_id,
                account_id=account_id,
                platform_name=platform_name,
                collected_account=account,
            )
            self._persist(account_id, code, backend.value, raw_items, now)
        except Exception as exc:
            # 写库异常会使 PostgreSQL 事务进入 failed 状态，必须先回滚，才能
            # 在一个干净事务中持久化失败原因和下一次重试时间。
            self.session.rollback()
            state = self._state(account_id, platform_name)
            assert state is not None
            state.consecutive_failures += 1
            state.last_error_code = type(exc).__name__
            state.last_error_message = str(exc)[:500] or type(exc).__name__
            delay = (5, 15, 30)[min(state.consecutive_failures - 1, 2)]
            state.next_refresh_at = now + timedelta(minutes=delay)
            state.locked_until = None
            state.updated_at = now
            self.session.commit()
            raise
        state = self._state(account_id, platform_name)
        assert state is not None
        state.last_success_at = now
        state.next_refresh_at = now + timedelta(
            seconds=self.settings.OWN_DASHBOARD_REFRESH_SECONDS
        )
        state.locked_until = None
        state.consecutive_failures = 0
        state.last_error_code = ""
        state.last_error_message = ""
        state.updated_at = now
        self.session.commit()
        return len(raw_items)

    def _merge_platform_identity(
        self,
        *,
        user_id: str,
        account_id: str,
        platform_name: str,
        collected_account: AccountRecord,
    ) -> None:
        """只合并本次平台解析出的身份，避免覆盖账号的并发配置变更。"""

        collected = dict(collected_account.platform_account_identities or {})
        identity = dict(collected.get(platform_name) or {})
        if not identity:
            return
        current_account = self._account(user_id, account_id)
        identities = dict(current_account.platform_account_identities or {})
        identities[platform_name] = identity
        current_account.platform_account_identities = identities

    async def _collect_mediaspider(
        self,
        account: AccountRecord,
        platform_name: str,
        code: str,
        handle: str,
        *,
        user_id: str = "",
    ) -> list[dict[str, Any]]:
        pool = self._cookie_pool_for_user(
            user_id=user_id, code=code, handle=handle
        )
        if not pool.has_cookies(code):
            raise ValueError(f"未配置{platform_name}采集凭证")
        identities = dict(account.platform_account_identities or {})
        identity = dict(identities.get(platform_name) or {})
        creator_url = str(
            (account.account_links or {}).get(platform_name)
            or (account.account_links or {}).get(code)
            or identity.get("profileUrl")
            or ""
        ).strip()
        if not creator_url:
            async def resolve(cookie: str):
                return await self.account_lookup.resolve(
                    platform=code, target=handle, cookies=cookie
                )

            creator = await run_with_cookie_candidates(pool, code, resolve)
            creator_url = str(creator["profile_url"])
            identities[platform_name] = {
                **identity,
                "input": handle,
                "profileUrl": creator_url,
                "displayName": str(creator.get("display_name") or ""),
            }
            account.platform_account_identities = identities

        options = {
            **self.settings.mediaspider_runtime_options(code),
            "max_notes_count": self.settings.OWN_DASHBOARD_RECENT_CONTENT_LIMIT,
            "max_detail_count": self.settings.OWN_DASHBOARD_RECENT_CONTENT_LIMIT,
            "enable_comments": False,
            "enable_sub_comments": False,
        }

        async def crawl(cookie: str):
            return await self.mediaspider.crawl_by_creator(
                creator_url=creator_url, cookies=cookie, **options
            )

        result = await run_with_cookie_candidates(pool, code, crawl)
        return [self._normalized_raw(code, item) for item in result.contents]

    async def _collect_tikhub(
        self, account_record: AccountRecord, platform_name: str, handle: str
    ) -> list[dict[str, Any]]:
        identities = dict(account_record.platform_account_identities or {})
        account, identity = await resolve_platform_account(
            self.tikhub_provider,
            platform_name=platform_name,
            platform_account=handle,
            cached=identities.get(platform_name),
        )
        if account is None or identity is None:
            raise ValueError(f"未找到与“{handle}”精确匹配的{platform_name}账号")
        identities[platform_name] = identity
        account_record.platform_account_identities = identities
        platform = PLATFORM_MAP[platform_name]
        page = await self.tikhub_provider.list_account_contents(
            TikHubAccountContentsRequest(
                platform=platform,
                accountId=account.userId,
                secUserId=account.userId if platform == TikHubPlatform.DOUYIN else "",
                pageSize=self.settings.OWN_DASHBOARD_RECENT_CONTENT_LIMIT,
            )
        )
        return [
            {
                "platform_content_id": item.contentId,
                "title": item.title or item.description,
                "content_url": item.contentUrl,
                "cover_url": item.coverUrl,
                "content_type": item.contentType,
                "published_at": _parse_time(item.publishedAt),
                "likes": item.likeCount,
                "comments": item.commentCount,
                "favorites": item.collectCount,
                "shares": item.shareCount,
            }
            for item in page.contents
            if item.contentId
        ]

    @staticmethod
    def _normalized_raw(code: str, raw: dict[str, Any]) -> dict[str, Any]:
        normalized = normalize_video(code, raw)
        return {
            "platform_content_id": normalized.platform_content_id,
            "title": normalized.title or normalized.description,
            "content_url": normalized.content_url,
            "cover_url": normalized.cover_url,
            "content_type": str(raw.get("type") or raw.get("note_type") or "unknown"),
            "published_at": normalized.published_at,
            "likes": normalized.metrics.get("likes"),
            "comments": normalized.metrics.get("comments"),
            "favorites": normalized.metrics.get("collects"),
            "shares": normalized.metrics.get("shares"),
        }

    def _persist(
        self,
        account_id: str,
        platform: str,
        provider: str,
        items: list[dict[str, Any]],
        captured_at: datetime,
    ) -> None:
        captured_hour = _hour(captured_at)
        for item in items:
            platform_content_id = str(item.get("platform_content_id") or "").strip()
            if not platform_content_id:
                continue
            content = self.session.scalar(
                select(OwnSocialContentRecord).where(
                    OwnSocialContentRecord.account_id == account_id,
                    OwnSocialContentRecord.platform == platform,
                    OwnSocialContentRecord.platform_content_id == platform_content_id,
                )
            )
            if content is None:
                content = OwnSocialContentRecord(
                    account_id=account_id,
                    platform=platform,
                    platform_content_id=platform_content_id,
                    first_seen_at=captured_at,
                )
                self.session.add(content)
                self.session.flush()
            content.title = str(item.get("title") or "")
            content.content_url = str(item.get("content_url") or "")
            content.cover_url = str(item.get("cover_url") or "")
            content.content_type = str(item.get("content_type") or "unknown")
            content.published_at = _utc(item.get("published_at"))
            content.last_seen_at = captured_at
            snapshot = self.session.scalar(
                select(OwnContentMetricSnapshotRecord).where(
                    OwnContentMetricSnapshotRecord.content_id == content.id,
                    OwnContentMetricSnapshotRecord.captured_hour == captured_hour,
                )
            )
            if snapshot is None:
                snapshot = OwnContentMetricSnapshotRecord(
                    content_id=content.id,
                    captured_hour=captured_hour,
                    captured_at=captured_at,
                    provider=provider,
                )
                self.session.add(snapshot)
            snapshot.captured_at = captured_at
            snapshot.provider = provider
            snapshot.likes = item.get("likes")
            snapshot.comments = item.get("comments")
            snapshot.favorites = item.get("favorites")
            snapshot.shares = item.get("shares")

    def build(
        self, *, user_id: str, account_id: str, platform_name: str, days: int
    ) -> SocialDashboardSchema:
        account = self._account(user_id, account_id)
        handle = self._resolve_platform_handle(
            account, user_id=user_id, platform_name=platform_name
        )
        if not handle:
            return SocialDashboardSchema(
                status="unconfigured",
                platform=platform_name,
                days=days,
                notices=[
                    f"请先配置{platform_name}号，或先完成{platform_name}浏览器扫码登录"
                ],
            )
        code = PLATFORM_CODES[platform_name]
        state = self._state(account_id, platform_name)
        self.session.commit()
        cutoff = datetime.now(UTC) - timedelta(days=days)
        contents = self.session.scalars(
            select(OwnSocialContentRecord)
            .where(
                OwnSocialContentRecord.account_id == account_id,
                OwnSocialContentRecord.platform == code,
                or_(
                    OwnSocialContentRecord.published_at.is_(None),
                    OwnSocialContentRecord.published_at >= cutoff,
                ),
            )
            .order_by(OwnSocialContentRecord.published_at.desc().nullslast())
        ).all()
        if not contents:
            return SocialDashboardSchema(
                status="unavailable",
                platform=platform_name,
                platformAccount=handle,
                provider=state.provider if state else "",
                days=days,
                nextRefreshAt=state.next_refresh_at.isoformat() if state else None,
                notices=[
                    state.last_error_message
                    if state and state.last_error_message
                    else "尚未完成首次小时数据采集"
                ],
            )
        rows = [self._content_view(content) for content in contents]
        delta24 = {
            key: (
                sum(
                    int(row["delta24"][key])
                    for row in rows
                    if row["delta24"].get(key) is not None
                )
                if any(row["delta24"].get(key) is not None for row in rows)
                else None
            )
            for key in ("likes", "comments", "favorites", "shares")
        }
        type_counts: dict[str, int] = {}
        for content in contents:
            label = CONTENT_TYPES.get(content.content_type.lower(), "其他")
            type_counts[label] = type_counts.get(label, 0) + 1
        structure = [
            DashboardContentStructureSchema(
                label=label,
                count=count,
                percentage=round(count / len(contents) * 100, 1),
            )
            for label, count in sorted(type_counts.items(), key=lambda pair: pair[1], reverse=True)
        ]
        ranked = sorted(
            rows,
            key=lambda row: (
                row["delta24Total"] is not None,
                row["delta24Total"] or 0,
            ),
            reverse=True,
        )
        top_contents = [
            DashboardTopContentSchema(
                rank=index,
                contentId=str(row["content"].id),
                title=row["content"].title or "未命名内容",
                contentType=CONTENT_TYPES.get(row["content"].content_type.lower(), "其他"),
                contentUrl=row["content"].content_url,
                coverUrl=row["content"].cover_url,
                publishedAt=(
                    row["content"].published_at.isoformat()
                    if row["content"].published_at else None
                ),
                **row["current"],
                delta1h=row["delta1hTotal"],
                delta24h=row["delta24Total"],
            )
            for index, row in enumerate(ranked, start=1)
        ]
        best = top_contents[0] if top_contents else None
        notices = []
        if state and state.last_error_message:
            notices.append(f"最近一次同步失败，正在使用历史数据：{state.last_error_message}")
        return SocialDashboardSchema(
            status="ready",
            platform=platform_name,
            platformAccount=handle,
            provider=state.provider if state else "",
            days=days,
            updatedAt=state.last_success_at.isoformat() if state and state.last_success_at else None,
            nextRefreshAt=state.next_refresh_at.isoformat() if state else None,
            metrics=[
                DashboardMetricSchema(key="contents", label="近期作品", value=len(contents), note=f"近 {days} 天"),
                DashboardMetricSchema(key="likes", label="24h 新增点赞", value=delta24["likes"], change=delta24["likes"]),
                DashboardMetricSchema(key="comments", label="24h 新增评论", value=delta24["comments"], change=delta24["comments"]),
                DashboardMetricSchema(key="favorites", label="24h 新增收藏", value=delta24["favorites"], change=delta24["favorites"]),
                DashboardMetricSchema(key="shares", label="24h 新增分享", value=delta24["shares"], change=delta24["shares"]),
            ],
            contentStructure=structure,
            topContents=top_contents,
            insights=(
                [DashboardInsightSchema(
                    title=f"24小时增长最快：{best.title}",
                    description=(
                        f"点赞、评论、收藏、分享合计变化 {best.delta24h:+d}。"
                        if best.delta24h is not None
                        else "小时快照正在积累，下一次采集后开始展示变化。"
                    ),
                )]
                if best else []
            ),
            notices=notices,
        )

    def _content_view(self, content: OwnSocialContentRecord) -> dict[str, Any]:
        snapshots = self.session.scalars(
            select(OwnContentMetricSnapshotRecord)
            .where(OwnContentMetricSnapshotRecord.content_id == content.id)
            .order_by(OwnContentMetricSnapshotRecord.captured_at.desc())
            .limit(25)
        ).all()
        current = snapshots[0] if snapshots else None
        previous = snapshots[1] if len(snapshots) > 1 else None
        day_ago_cutoff = datetime.now(UTC) - timedelta(hours=24)
        day_ago = next(
            (item for item in snapshots if _utc(item.captured_at) <= day_ago_cutoff),
            snapshots[-1] if len(snapshots) > 1 else None,
        )
        keys = ("likes", "comments", "favorites", "shares")

        def values(snapshot):
            return {key: getattr(snapshot, key) if snapshot else None for key in keys}

        def delta(left, right):
            return {
                key: (
                    getattr(left, key) - getattr(right, key)
                    if left and right
                    and getattr(left, key) is not None
                    and getattr(right, key) is not None
                    else None
                )
                for key in keys
            }

        current_values = values(current)
        delta1h = delta(current, previous)
        delta24 = delta(current, day_ago)
        return {
            "content": content,
            "current": current_values,
            "delta1h": delta1h,
            "delta24": delta24,
            "delta1hTotal": _metric_sum(delta1h),
            "delta24Total": _metric_sum(delta24),
        }

    def trend(
        self,
        *,
        user_id: str,
        account_id: str,
        content_id: int,
        days: int,
    ) -> DashboardContentTrendSchema:
        self._account(user_id, account_id)
        content = self.session.scalar(
            select(OwnSocialContentRecord).where(
                OwnSocialContentRecord.id == content_id,
                OwnSocialContentRecord.account_id == account_id,
            )
        )
        if content is None:
            raise StopIteration(content_id)
        snapshots = self.session.scalars(
            select(OwnContentMetricSnapshotRecord)
            .where(
                OwnContentMetricSnapshotRecord.content_id == content.id,
                OwnContentMetricSnapshotRecord.captured_at
                >= datetime.now(UTC) - timedelta(days=days),
            )
            .order_by(OwnContentMetricSnapshotRecord.captured_at)
        ).all()
        return DashboardContentTrendSchema(
            contentId=str(content.id),
            title=content.title,
            platform=content.platform,
            provider=snapshots[-1].provider if snapshots else "",
            points=[
                DashboardTrendPointSchema(
                    timestamp=item.captured_at.isoformat(),
                    likes=item.likes,
                    comments=item.comments,
                    favorites=item.favorites,
                    shares=item.shares,
                )
                for item in snapshots
            ],
        )
