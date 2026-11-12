from __future__ import annotations

import asyncio
import threading

from ..error_classifier import classify_crawler_error
from ..models import (
    CrawlResult,
    CrawlerExecutionError,
    CrawlerProgressEvent,
    CrawlerRunConfig,
    ProgressCallback,
)
from ..progress_safety import safe_creator_subject, safe_keyword_subject
from .config_scope import CrawlerConfigScope
from .collector import (
    MemoryResultCollector,
    bind_collector,
    emit_progress,
    reset_collector,
)
from .context import (
    comment_tasks_var, crawler_type_var, creator_profile_var,
    request_keyword_var, source_keyword_var,
)
from ..platforms.douyin import DouYinCrawler
from ..platforms.kuaishou import KuaishouCrawler
from ..platforms.xhs import XiaoHongShuCrawler


class ProcessAsyncLock:
    def __init__(self):
        self._lock = threading.Lock()

    async def __aenter__(self):
        delay = 0.001
        while not self._lock.acquire(blocking=False):
            await asyncio.sleep(delay)
            delay = min(delay * 2, 0.05)
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        self._lock.release()


class CrawlerFactory:
    CRAWLERS = {
        "xhs": XiaoHongShuCrawler,
        "dy": DouYinCrawler,
        "ks": KuaishouCrawler,
    }

    @classmethod
    def create_crawler(cls, platform):
        crawler_class = cls.CRAWLERS.get(platform)
        if crawler_class is None:
            raise ValueError("不支持的平台")
        return crawler_class()


crawler_run_locks = {
    platform: ProcessAsyncLock()
    for platform in CrawlerFactory.CRAWLERS
}


async def cleanup_crawler(crawler):
    if crawler is None:
        return
    try:
        if getattr(crawler, "cdp_manager", None) is not None:
            await crawler.cdp_manager.cleanup(force=True)
        elif getattr(crawler, "browser_context", None) is not None:
            await crawler.browser_context.close()
    except Exception as exc:
        if "closed" not in str(exc).lower() and "disconnected" not in str(exc).lower():
            raise


def _lifecycle_event(
    run_config: CrawlerRunConfig,
    collector: MemoryResultCollector,
    *,
    action: str,
    status: str,
    message: str,
    subject: str = "",
) -> CrawlerProgressEvent:
    result = collector.to_result()
    return CrawlerProgressEvent(
        platform=run_config.platform,
        crawlType=run_config.crawl_type,
        action=action,
        status=status,
        message=message,
        subject=subject,
        contentCount=result.content_count,
        creatorCount=result.creator_count,
        commentCount=result.comment_count,
    )


async def run_crawler(
    run_config: CrawlerRunConfig,
    *,
    on_progress: ProgressCallback | None = None,
    factory=CrawlerFactory,
) -> CrawlResult:
    collector = MemoryResultCollector(
        run_config.platform,
        run_config.crawl_type,
        run_config.keywords,
        run_config.creator_url,
        on_progress,
    )
    crawler = None
    await emit_progress(
        on_progress,
        _lifecycle_event(
            run_config,
            collector,
            action="waiting_for_slot",
            status="pending",
            message="等待运行槽位",
        ),
    )
    async with crawler_run_locks[run_config.platform]:
        tokens = (
            (source_keyword_var, source_keyword_var.set("")),
            (crawler_type_var, crawler_type_var.set(run_config.crawl_type)),
            (request_keyword_var, request_keyword_var.set("")),
            (creator_profile_var, creator_profile_var.set({})),
            (comment_tasks_var, comment_tasks_var.set([])),
        )
        collector_token = bind_collector(collector)
        primary_error = None
        try:
            await emit_progress(
                on_progress,
                _lifecycle_event(
                    run_config,
                    collector,
                    action="run_started",
                    status="running",
                    message="开始平台采集",
                ),
            )
            await emit_progress(
                on_progress,
                _lifecycle_event(
                    run_config,
                    collector,
                    action={
                        "search": "keyword_started",
                        "creator": "creator_started",
                        "detail": "detail_started",
                    }[run_config.crawl_type],
                    status="running",
                    message={
                        "search": "开始关键词采集",
                        "creator": "开始博主采集",
                        "detail": "开始指定内容采集",
                    }[run_config.crawl_type],
                    subject=(
                        safe_keyword_subject(run_config.keywords)
                        if run_config.crawl_type == "search"
                        else safe_creator_subject(run_config.platform)
                    ),
                ),
            )
            with CrawlerConfigScope(run_config):
                crawler = factory.create_crawler(run_config.platform)
                await crawler.start()
        except asyncio.CancelledError as exc:
            primary_error = exc
            raise
        except Exception as exc:
            failure = classify_crawler_error(run_config.platform, exc)
            primary_error = CrawlerExecutionError(
                run_config.platform,
                exc,
                collector.to_result(),
                failure=failure,
            )
            await emit_progress(
                on_progress,
                _lifecycle_event(
                    run_config,
                    collector,
                    action="run_failed",
                    status="failed",
                    message=failure.message,
                ),
            )
        finally:
            try:
                await cleanup_crawler(crawler)
            except Exception as cleanup_error:
                if primary_error is None:
                    failure = classify_crawler_error(
                        run_config.platform, cleanup_error
                    )
                    await emit_progress(
                        on_progress,
                        _lifecycle_event(
                            run_config,
                            collector,
                            action="run_failed",
                            status="failed",
                            message=failure.message,
                        ),
                    )
                    primary_error = CrawlerExecutionError(
                        run_config.platform,
                        cleanup_error,
                        collector.to_result(),
                        failure=failure,
                    )
            finally:
                reset_collector(collector_token)
                for variable, token in reversed(tokens):
                    variable.reset(token)
        if primary_error is not None:
            raise primary_error from None
        await emit_progress(
            on_progress,
            _lifecycle_event(
                run_config,
                collector,
                action="run_completed",
                status="completed",
                message="平台采集完成",
            ),
        )
    return collector.to_result()
