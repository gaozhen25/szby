"""StarX 内嵌 MediaSpider 的公开异步服务。"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence

from pydantic import ValidationError

from .models import (
    CrawlResult,
    CrawlerProgressEvent,
    CrawlerRunConfig,
    InvalidCrawlRequestError,
    ProgressCallback,
)
from .platform_resolver import (
    normalize_keywords,
    normalize_platform,
    resolve_content_platform,
    resolve_creator_platform,
)

Runner = Callable[..., Awaitable[CrawlResult]]


async def _default_runner(
    config: CrawlerRunConfig, on_progress: ProgressCallback | None = None
) -> CrawlResult:
    from .runtime.runner import run_crawler

    return await run_crawler(config, on_progress=on_progress)


def _safe_progress_adapter(
    callback: ProgressCallback | None,
) -> ProgressCallback | None:
    if callback is None:
        return None

    async def forward(event: CrawlerProgressEvent) -> None:
        from .runtime.collector import emit_progress

        await emit_progress(callback, event)

    return forward


async def _invoke_runner(
    runner: Runner,
    config: CrawlerRunConfig,
    on_progress: ProgressCallback | None,
) -> CrawlResult:
    callback = _safe_progress_adapter(on_progress)
    if callback is None:
        return await runner(config)
    return await runner(config, on_progress=callback)


class MediaCrawlerService:
    def __init__(self, runner: Runner = _default_runner):
        self._runner = runner

    async def crawl_by_keyword(
        self,
        *,
        keywords: str | Sequence[str],
        platform: str,
        on_progress: ProgressCallback | None = None,
        **runtime_options,
    ) -> CrawlResult:
        config = self._build_config(
            platform=normalize_platform(platform),
            crawl_type="search",
            keywords=normalize_keywords(keywords),
            creator_url=None,
            **runtime_options,
        )
        return await _invoke_runner(self._runner, config, on_progress)

    async def crawl_by_creator(
        self,
        *,
        creator_url: str,
        on_progress: ProgressCallback | None = None,
        **runtime_options,
    ) -> CrawlResult:
        url = creator_url.strip()
        config = self._build_config(
            platform=resolve_creator_platform(url),
            crawl_type="creator",
            keywords=[],
            creator_url=url,
            **runtime_options,
        )
        return await _invoke_runner(self._runner, config, on_progress)

    async def crawl_by_detail(
        self,
        *,
        content_url: str,
        on_progress: ProgressCallback | None = None,
        **runtime_options,
    ) -> CrawlResult:
        url = content_url.strip()
        config = self._build_config(
            platform=resolve_content_platform(url),
            crawl_type="detail",
            keywords=[],
            creator_url=None,
            content_url=url,
            **runtime_options,
        )
        return await _invoke_runner(self._runner, config, on_progress)

    @staticmethod
    def _build_config(**values) -> CrawlerRunConfig:
        try:
            return CrawlerRunConfig(**values, output_mode="memory")
        except InvalidCrawlRequestError:
            raise
        except ValidationError as exc:
            # Pydantic 的输入快照可能包含 Cookie，不把其字符串表示带入异常。
            raise InvalidCrawlRequestError("爬取参数不合法") from None
