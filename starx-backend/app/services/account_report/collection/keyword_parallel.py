"""账号报告 MediaSpider 多关键词并行采集。

每个关键词独立申请 Cookie 租约。
- 多 Cookie：按关键词并行（同一 Cookie 同时只服务一个词）
- 单 Cookie：串行一词一采，词间休眠，避免短时间连打触发风控
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from typing import Any

from app.services.mediaspider.cookie_pool import run_with_cookie_candidates
from app.services.mediaspider.models import CrawlResult

# 单 Cookie 连续搜词时的间隔（秒）；需 ≥ search_gate.MIN_INTERVAL_SEC
_SINGLE_COOKIE_KEYWORD_GAP_SEC = 6.0


def _cookie_count(cookie_pool: Any, platform: str) -> int:
    counter = getattr(cookie_pool, "cookie_count", None)
    if callable(counter):
        return max(int(counter(platform)), 0)
    return len(tuple(cookie_pool.candidates(platform)))


def _record_key(item: dict[str, Any], fields: tuple[str, ...], index: int) -> str:
    for field in fields:
        value = str(item.get(field) or "").strip()
        if value:
            return f"{field}:{value}"
    return f"anonymous:{index}:{repr(sorted(item.items()))}"


def _merge_records(
    results: Sequence[CrawlResult],
    field: str,
    identity_fields: tuple[str, ...],
) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    positions: dict[str, int] = {}
    for result in results:
        source_keyword = result.keywords[0] if len(result.keywords) == 1 else ""
        for item in getattr(result, field):
            normalized = dict(item)
            if source_keyword and field == "contents":
                normalized.setdefault("source_keyword", source_keyword)
            key = _record_key(normalized, identity_fields, len(merged))
            if key in positions:
                existing = merged[positions[key]]
                for name, value in normalized.items():
                    if existing.get(name) in (None, "", [], {}) and value not in (
                        None,
                        "",
                        [],
                        {},
                    ):
                        existing[name] = value
                continue
            positions[key] = len(merged)
            merged.append(normalized)
    return merged


def merge_keyword_results(
    *,
    platform: str,
    keywords: Sequence[str],
    results: Sequence[CrawlResult],
    warnings: Sequence[str] = (),
) -> CrawlResult:
    """按关键词输入顺序合并结果并去重。"""

    contents = _merge_records(
        results,
        "contents",
        ("content_id", "note_id", "aweme_id", "video_id", "public_url"),
    )
    creators = _merge_records(
        results,
        "creators",
        ("creator_hash", "user_id", "author_id", "id", "profile_url"),
    )
    comments = _merge_records(
        results,
        "comments",
        ("comment_id", "id"),
    )
    source_operations = list(
        dict.fromkeys(
            operation
            for result in results
            for operation in result.source_operations
            if operation
        )
    )
    discovery_warnings = list(
        dict.fromkeys(
            [
                *(
                    warning
                    for result in results
                    for warning in result.discovery_warnings
                    if warning
                ),
                *(warning for warning in warnings if warning),
            ]
        )
    )
    return CrawlResult(
        platform=platform,
        crawl_type="search",
        keywords=list(keywords),
        contents=contents,
        creators=creators,
        comments=comments,
        content_count=len(contents),
        creator_count=len(creators),
        comment_count=len(comments),
        source_operations=source_operations,
        discovery_warnings=discovery_warnings,
    )


async def crawl_keywords_with_cookie_pool(
    *,
    crawler: Any,
    cookie_pool: Any,
    platform: str,
    keywords: Sequence[str],
    runtime_options: dict[str, object],
    on_progress: Callable[[Any], Awaitable[None]] | None = None,
) -> CrawlResult:
    """按 Cookie 数决定并行；始终一词一采，避免单 Cookie 批量连打。"""

    normalized_keywords = [str(keyword).strip() for keyword in keywords if str(keyword).strip()]

    async def crawl(cookie: str, selected_keywords: Sequence[str]) -> CrawlResult:
        return await crawler.crawl_by_keyword(
            keywords=list(selected_keywords),
            platform=platform,
            on_progress=on_progress,
            cookies=cookie,
            **runtime_options,
        )

    if not normalized_keywords:
        return merge_keyword_results(
            platform=platform, keywords=[], results=[], warnings=[]
        )

    if len(normalized_keywords) == 1:
        return await run_with_cookie_candidates(
            cookie_pool,
            platform,
            lambda cookie: crawl(cookie, normalized_keywords),
        )

    async def crawl_one(keyword: str) -> CrawlResult:
        return await run_with_cookie_candidates(
            cookie_pool,
            platform,
            lambda cookie: crawl(cookie, [keyword]),
        )

    cookie_n = _cookie_count(cookie_pool, platform)
    results: list[CrawlResult] = []
    failures: list[BaseException] = []
    warnings: list[str] = []

    if cookie_n <= 1:
        for index, keyword in enumerate(normalized_keywords):
            try:
                results.append(await crawl_one(keyword))
            except asyncio.CancelledError:
                raise
            except BaseException as exc:
                failures.append(exc)
                failure = getattr(exc, "failure", None)
                failure_code = str(
                    getattr(failure, "code", "") or type(exc).__name__
                )
                warnings.append(
                    f"keyword_search_failed:{platform}:{index}:{failure_code}"
                )
            if index + 1 < len(normalized_keywords):
                await asyncio.sleep(_SINGLE_COOKIE_KEYWORD_GAP_SEC)
    else:
        outcomes = await asyncio.gather(
            *(crawl_one(keyword) for keyword in normalized_keywords),
            return_exceptions=True,
        )
        for index, outcome in enumerate(outcomes):
            if isinstance(outcome, asyncio.CancelledError):
                raise outcome
            if isinstance(outcome, BaseException):
                failures.append(outcome)
                failure = getattr(outcome, "failure", None)
                failure_code = str(
                    getattr(failure, "code", "") or type(outcome).__name__
                )
                warnings.append(
                    f"keyword_search_failed:{platform}:{index}:{failure_code}"
                )
                continue
            results.append(outcome)

    if not results:
        raise failures[0]
    return merge_keyword_results(
        platform=platform,
        keywords=normalized_keywords,
        results=results,
        warnings=warnings,
    )
