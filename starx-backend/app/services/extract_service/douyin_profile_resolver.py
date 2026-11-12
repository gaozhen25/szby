from __future__ import annotations

import asyncio
from collections.abc import Awaitable
from concurrent.futures import ThreadPoolExecutor
from typing import Any
from urllib.parse import urlparse

from app.core.config import settings
from app.services.mediaspider.cookie_pool import (
    load_cookie_pool,
    run_with_cookie_candidates,
)
from app.services.mediaspider.models import CrawlResult, CrawlerExecutionError
from app.services.mediaspider.service import MediaCrawlerService
from app.services.social_retrieval import RetrievalBackend, backend_for_platform
from app.services.tikhub_service import (
    TikHubBusinessConfigError,
    TikHubCrawlService,
)


def resolve_douyin_profile_url(douyin_id: str, nickname: str = "") -> dict[str, Any]:
    """同步入口：使用抖音号搜索并解析稳定的 sec_uid 主页地址。"""

    if not str(douyin_id or "").strip():
        return _unresolved("douyin_id_missing")
    try:
        return _run_async(
            resolve_douyin_profile_url_async(
                douyin_id=str(douyin_id).strip(),
                nickname=str(nickname or "").strip(),
            )
        )
    except TikHubBusinessConfigError:
        return _unresolved("credentials_missing")
    except CrawlerExecutionError as exc:
        return _unresolved(exc.failure.code)
    except Exception:
        return _unresolved("crawler_failed")


async def resolve_douyin_profile_url_async(
    *,
    douyin_id: str,
    nickname: str = "",
    crawler_service: Any | None = None,
    cookie_pool: Any | None = None,
) -> dict[str, Any]:
    backend = (
        (
            RetrievalBackend.MEDIASPIDER
            if cookie_pool is not None
            else RetrievalBackend.TIKHUB
        )
        if crawler_service is not None
        else backend_for_platform(settings, "dy")
    )
    use_mediaspider = backend == RetrievalBackend.MEDIASPIDER
    crawler = crawler_service or (
        MediaCrawlerService() if use_mediaspider else TikHubCrawlService()
    )
    if use_mediaspider:
        pool = cookie_pool or load_cookie_pool()
        if not pool.has_cookies("dy"):
            return _unresolved("credentials_missing")
        result = await run_with_cookie_candidates(
            pool,
            "dy",
            lambda cookie: crawler.crawl_by_keyword(
                keywords=[douyin_id],
                platform="dy",
                cookies=cookie,
                enable_comments=False,
                max_notes_count=5,
            ),
        )
    else:
        result = await crawler.crawl_by_keyword(
            keywords=[douyin_id],
            platform="dy",
            enable_comments=False,
            max_notes_count=5,
        )
    return profile_resolution_from_search(result, expected_nickname=nickname)


def profile_resolution_from_search(
    result: CrawlResult,
    *,
    expected_nickname: str = "",
) -> dict[str, Any]:
    expected = _normalized_name(expected_nickname)
    candidates: list[tuple[str, str]] = []
    for item in [*result.contents, *result.creators]:
        url = canonical_douyin_profile_url(item.get("profile_url"))
        if not url:
            continue
        display_name = str(item.get("display_name") or item.get("name") or "").strip()
        candidates.append((url, display_name))

    if expected:
        matched_urls = {
            url for url, display_name in candidates
            if _normalized_name(display_name) == expected
        }
    else:
        matched_urls = {url for url, _ in candidates}

    if len(matched_urls) != 1:
        return _unresolved("not_found" if not matched_urls else "ambiguous_result")
    return {
        "status": "resolved",
        "method": "douyin_id_search",
        "profile_url": next(iter(matched_urls)),
        "reason": None,
    }


def canonical_douyin_profile_url(value: Any) -> str | None:
    parsed = urlparse(str(value or "").strip())
    hostname = (parsed.hostname or "").lower()
    if not (hostname == "douyin.com" or hostname.endswith(".douyin.com")):
        return None
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) != 2 or parts[0] != "user" or not parts[1].startswith("MS4wLjAB"):
        return None
    return f"https://www.douyin.com/user/{parts[1]}"


def _run_async(awaitable: Awaitable[dict[str, Any]]) -> dict[str, Any]:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(awaitable)

    # ExtractService 也可能被异步工作流直接调用；避免在已有事件循环中嵌套 asyncio.run。
    with ThreadPoolExecutor(max_workers=1) as executor:
        return executor.submit(asyncio.run, awaitable).result()


def _normalized_name(value: str) -> str:
    return "".join(str(value or "").split()).casefold()


def _unresolved(reason: str) -> dict[str, Any]:
    return {
        "status": "unresolved",
        "method": "douyin_id_search",
        "profile_url": None,
        "reason": reason,
    }
