"""竞品监控用例编排。"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any, Callable

from app.core.config import settings
from app.core.database import SessionLocal
from app.core.logging import get_logger
from app.services.mediaspider.cookie_pool import (
    load_cookie_pool,
    run_with_cookie_candidates,
)
from app.services.mediaspider.service import MediaCrawlerService
from app.services.mediaspider.models import CrawlResult, CrawlerExecutionError
from app.services.mediaspider.platform_resolver import (
    extract_douyin_sec_user_id,
    normalize_platform,
    normalize_public_url,
    resolve_content_platform,
    resolve_creator_platform,
)
from app.services.social_retrieval import RetrievalBackend, backend_for_platform
from app.services.tikhub_service import TikHubCrawlService

from .models import NormalizedCompetitor, TargetType
from .normalizers import normalize_account, normalize_account_videos, normalize_video
from .repository import (
    CompetitorRepository,
    CompetitorTargetNotFound,
    DuplicateCompetitorTarget,
    StaleCompetitorWorkflow,
)
from .schedule import next_daily_refresh_at

logger = get_logger(__name__)

_RETRYABLE_FAILURE_CODES = frozenset(
    {"platform_blocked", "browser_timeout", "crawler_failed"}
)
_RETRYABLE_CAUSE_TYPES = frozenset({"ProcessExitedWithNonZeroStatus"})


class CompetitorMonitoringService:
    def __init__(
        self,
        session_factory: Callable[[], Any] = SessionLocal,
        *,
        crawl_max_attempts: int | None = None,
        crawl_retry_backoff_seconds: float | None = None,
        retry_sleep: Callable[[float], Any] = asyncio.sleep,
    ) -> None:
        self.session_factory = session_factory

        def next_refresh(now: datetime) -> datetime:
            return next_daily_refresh_at(
                now,
                hour=settings.COMPETITOR_REFRESH_HOUR,
                timezone_name=settings.COMPETITOR_REFRESH_TIMEZONE,
            )

        self.repository = CompetitorRepository(
            session_factory,
            next_refresh_at=next_refresh,
        )
        self.crawl_max_attempts = max(
            int(
                crawl_max_attempts
                if crawl_max_attempts is not None
                else settings.COMPETITOR_CRAWL_MAX_ATTEMPTS
            ),
            1,
        )
        self.crawl_retry_backoff_seconds = max(
            float(
                crawl_retry_backoff_seconds
                if crawl_retry_backoff_seconds is not None
                else settings.COMPETITOR_CRAWL_RETRY_BACKOFF_SECONDS
            ),
            0,
        )
        self.retry_sleep = retry_sleep

    def list_accounts(self, user_id: str, account_id: str):
        return self.repository.list_targets(user_id, account_id, "account")

    def list_videos(self, user_id: str, account_id: str):
        return self.repository.list_targets(user_id, account_id, "video")

    def get_account(self, user_id: str, account_id: str, target_id: str):
        return self.repository.get_target(user_id, account_id, "account", target_id)

    def get_video(self, user_id: str, account_id: str, target_id: str):
        return self.repository.get_target(user_id, account_id, "video", target_id)

    def list_account_content_trends(
        self, user_id: str, account_id: str, target_id: str, *, days: int
    ):
        return self.repository.list_account_content_trends(
            user_id, account_id, target_id, days=days
        )

    def list_account_metric_trends(
        self, user_id: str, account_id: str, target_id: str, *, days: int
    ):
        return self.repository.list_account_metric_trends(
            user_id, account_id, target_id, days=days
        )

    def add_account(
        self,
        user_id: str,
        account_id: str,
        profile_url: str,
        *,
        platform: str = "",
    ):
        url = normalize_public_url(profile_url)
        detected_platform = resolve_creator_platform(url)
        if platform:
            requested_platform = normalize_platform(platform)
            if requested_platform != detected_platform:
                raise InvalidCrawlRequestError("platform 与主页链接平台不一致")
        sec_user_id = (
            extract_douyin_sec_user_id(url) if detected_platform == "dy" else ""
        )
        return self.repository.add_target(
            user_id,
            account_id,
            "account",
            detected_platform,
            url,
            sec_user_id=sec_user_id,
        )

    def add_video(self, user_id: str, account_id: str, content_url: str):
        url = normalize_public_url(content_url)
        platform = resolve_content_platform(url)
        return self.repository.add_target(user_id, account_id, "video", platform, url)

    def delete_account(self, user_id: str, account_id: str, target_id: str) -> None:
        self.repository.delete_target(user_id, account_id, "account", target_id)

    def delete_video(self, user_id: str, account_id: str, target_id: str) -> None:
        self.repository.delete_target(user_id, account_id, "video", target_id)

    def create_refresh(
        self,
        user_id: str,
        account_id: str,
        target_type: TargetType,
        target_id: str,
        trigger: str,
    ):
        return self.repository.create_refresh(
            user_id, account_id, target_type, target_id, trigger
        )

    def create_batch_refresh(
        self, user_id: str, account_id: str, target_type: TargetType
    ):
        targets = self.repository.list_targets(user_id, account_id, target_type)
        return [
            self.repository.create_refresh(
                user_id, account_id, target_type, target.id, "manual_batch"
            )
            for target in targets
        ]

    def get_workflow(self, user_id: str, account_id: str, workflow_id: str):
        return self.repository.get_workflow(user_id, account_id, workflow_id)

    def mark_submission_failed(self, workflow_id: str) -> None:
        self.repository.mark_submission_failed(workflow_id)

    def claim_due_targets(self, now: datetime, limit: int):
        return self.repository.claim_due_targets(now, limit)

    def release_terminal_claims(self, now: datetime, stale_seconds: int) -> int:
        return self.repository.release_terminal_claims(now, stale_seconds)

    def touch_refresh(self, workflow_id: str, now: datetime) -> bool:
        return self.repository.touch_refresh(workflow_id, now)

    def complete_refresh(
        self, workflow_id: str, normalized: NormalizedCompetitor
    ):
        return self.repository.complete_refresh(workflow_id, normalized)

    def update_account_profile(
        self, workflow_id: str, normalized: NormalizedCompetitor
    ):
        return self.repository.update_account_profile(workflow_id, normalized)

    def fail_refresh(self, workflow_id: str, code: str, message: str) -> None:
        self.repository.fail_refresh(workflow_id, code, message)

    async def execute_refresh(
        self,
        workflow_id: str,
        *,
        crawler_service: Any = None,
        cookie_pool_loader: Callable[[], Any] | None = None,
        runtime_options_loader: Callable[[str], dict[str, object]] | None = None,
    ) -> dict[str, object]:
        context = self.repository.refresh_context(workflow_id)
        platform = context["platform"]
        target_type = context["targetType"]
        backend = (
            (
                RetrievalBackend.MEDIASPIDER
                if cookie_pool_loader is not None
                else RetrievalBackend.TIKHUB
            )
            if crawler_service is not None
            else backend_for_platform(settings, platform)
        )
        use_mediaspider = backend == RetrievalBackend.MEDIASPIDER
        if use_mediaspider and cookie_pool_loader is None:
            cookie_pool_loader = load_cookie_pool
        crawler = (
            crawler_service
            or (
                MediaCrawlerService()
                if use_mediaspider
                else TikHubCrawlService()
            )
        )
        cookie_pool = cookie_pool_loader() if use_mediaspider else None
        if use_mediaspider:
            load_options = runtime_options_loader or settings.mediaspider_runtime_options
            runtime_options = {
                **load_options(platform),
                "enable_comments": False,
                "enable_sub_comments": False,
            }
        else:
            runtime_options = {
                "enable_comments": False,
                "max_comments_count": settings.MEDIASPIDER_MAX_COMMENTS_COUNT,
            }
        if target_type == "account":
            # 趋势卡只展示近期作品。限制列表为一个标准首屏，并仅补全最新作品
            # 的详情，避免高频账号因逐条详情请求导致首次刷新耗时线性增长。
            runtime_options["max_notes_count"] = (
                settings.COMPETITOR_ACCOUNT_MAX_NOTES_COUNT
            )
            runtime_options["max_detail_count"] = (
                settings.COMPETITOR_ACCOUNT_DETAIL_LIMIT
            )
            runtime_options["detail_concurrency"] = (
                settings.COMPETITOR_ACCOUNT_DETAIL_CONCURRENCY
            )
            if not use_mediaspider:
                runtime_options["sec_user_id"] = context.get("secUserId", "")
                runtime_options["recent_since"] = datetime.now(UTC) - timedelta(days=7)
                # TikHub 不接收 MediaSpider 专用并发参数。
                runtime_options.pop("detail_concurrency", None)

        async def crawl(cookie: str):
            credential_options = {"cookies": cookie} if use_mediaspider else {}
            if target_type == "account":
                def persist_profile(partial: CrawlResult) -> None:
                    if not partial.creators:
                        return
                    profile = normalize_account(platform, partial.creators[0])
                    self.update_account_profile(workflow_id, profile)

                return await crawler.crawl_by_creator(
                    creator_url=context["url"],
                    on_partial_result=persist_profile,
                    **credential_options,
                    **runtime_options,
                )
            return await crawler.crawl_by_detail(
                content_url=context["url"],
                **credential_options,
                **runtime_options,
            )

        result = await self._crawl_with_retry(
            workflow_id,
            platform,
            target_type,
            cookie_pool,
            use_mediaspider,
            crawl,
        )
        if target_type == "account":
            if not result.creators:
                raise ValueError("未采集到公开账号数据")
            normalized = normalize_account(platform, result.creators[0]).model_copy(
                update={
                    "videos": normalize_account_videos(
                        platform, result.contents, limit=100
                    )
                }
            )
        else:
            if not result.contents:
                raise ValueError("未采集到公开内容数据")
            normalized = normalize_video(platform, result.contents[0])
        target = self.complete_refresh(workflow_id, normalized)
        return {
            "targetType": target_type,
            "targetId": target.id,
            "refreshedAt": target.last_refreshed_at.isoformat()
            if target.last_refreshed_at
            else "",
        }

    async def _crawl_with_retry(
        self,
        workflow_id: str,
        platform: str,
        target_type: TargetType,
        cookie_pool: Any,
        use_mediaspider: bool,
        crawl: Callable[[str], Any],
    ) -> CrawlResult:
        best_partial: CrawlResult | None = None
        for attempt in range(1, self.crawl_max_attempts + 1):
            try:
                if use_mediaspider:
                    return await run_with_cookie_candidates(cookie_pool, platform, crawl)
                return await crawl("")
            except CrawlerExecutionError as exc:
                partial = exc._recoverable_result_copy()
                if best_partial is None or (
                    partial.creator_count + partial.content_count
                    > best_partial.creator_count + best_partial.content_count
                ):
                    best_partial = partial
                retryable = (
                    exc.failure.code in _RETRYABLE_FAILURE_CODES
                    or exc.cause_type in _RETRYABLE_CAUSE_TYPES
                )
                exhausted = attempt >= self.crawl_max_attempts
                logger.warning(
                    "competitor crawl attempt failed workflow_id=%s platform=%s "
                    "target_type=%s attempt=%s/%s failure_code=%s cause_type=%s "
                    "cause_exit_status=%s cause_diagnostic=%s "
                    "partial_creators=%s partial_contents=%s retrying=%s",
                    workflow_id,
                    platform,
                    target_type,
                    attempt,
                    self.crawl_max_attempts,
                    exc.failure.code,
                    exc.cause_type,
                    exc.cause_exit_status,
                    exc.cause_diagnostic,
                    partial.creator_count,
                    partial.content_count,
                    retryable and not exhausted,
                )
                if not retryable or exhausted:
                    if (
                        target_type == "account"
                        and best_partial is not None
                        and best_partial.creators
                    ):
                        logger.info(
                            "competitor crawl using partial creator result "
                            "workflow_id=%s creators=%s contents=%s",
                            workflow_id,
                            best_partial.creator_count,
                            best_partial.content_count,
                        )
                        return best_partial
                    raise
                delay = self.crawl_retry_backoff_seconds * (2 ** (attempt - 1))
                if delay:
                    await self.retry_sleep(delay)

        raise RuntimeError("competitor crawl retry loop exited unexpectedly")


__all__ = [
    "CompetitorMonitoringService",
    "CompetitorTargetNotFound",
    "DuplicateCompetitorTarget",
    "StaleCompetitorWorkflow",
]
