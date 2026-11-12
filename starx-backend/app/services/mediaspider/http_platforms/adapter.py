"""将 HTTP 平台客户端适配为 mediaspider CrawlResult 采集。"""

from __future__ import annotations

import math
import time
from typing import Any

from ..models import (
    CrawlResult,
    CrawlerAuthenticationError,
    CrawlerRunConfig,
    UnsupportedPlatformError,
)
from ..runtime.collector import MemoryResultCollector
from .common.proxy import resolve_requests_proxies
from .common.store import sort_contents_by_time
from .douyin import DouyinClient
from .xhs import XhsClient, parse_creator_url
from .xhs.normalize import normalize_creator


SUPPORTED_HTTP_PLATFORMS = frozenset({"xhs", "dy"})
SOURCE_PROVIDER = "mediaspider"
SOURCE_OPERATIONS = {
    "search": ["search_contents"],
    "creator": ["get_account", "list_account_contents"],
    "detail": ["get_content"],
}
CONTENT_SOURCE_OPERATION = {
    "search": "search_contents",
    "creator": "list_account_contents",
    "detail": "get_content",
}


def _require_cookie(run_config: CrawlerRunConfig) -> str:
    cookie = (run_config.cookies or "").strip()
    if not cookie:
        raise CrawlerAuthenticationError(run_config.platform, "empty cookie")
    return cookie


def _dict_to_partial(
    run_config: CrawlerRunConfig,
    payload: dict[str, Any],
) -> CrawlResult:
    source_operations = SOURCE_OPERATIONS[run_config.crawl_type]
    content_source_operation = CONTENT_SOURCE_OPERATION[run_config.crawl_type]
    contents = sort_contents_by_time(payload.get("contents"))
    creators = list(payload.get("creators") or [])
    comments = list(payload.get("comments") or [])
    for item in contents:
        if run_config.platform == "xhs":
            item.setdefault("content_id", item.get("note_id") or "")
            item.setdefault("public_url", item.get("note_url") or "")
            item.setdefault("author_id", item.get("user_id") or "")
        else:
            item.setdefault("content_id", item.get("aweme_id") or "")
            item.setdefault("public_url", item.get("aweme_url") or "")
        item["source_provider"] = SOURCE_PROVIDER
        item["source_operation"] = content_source_operation
    for item in creators:
        item["source_provider"] = SOURCE_PROVIDER
        item["source_operations"] = list(source_operations)
    for item in comments:
        item["source_provider"] = SOURCE_PROVIDER
    return CrawlResult(
        platform=run_config.platform,
        crawl_type=run_config.crawl_type,
        keywords=list(run_config.keywords),
        creator_url=run_config.creator_url or payload.get("creator_url"),
        content_url=run_config.content_url or payload.get("content_url"),
        contents=contents,
        comments=comments,
        creators=creators,
        content_count=len(contents),
        comment_count=len(comments),
        creator_count=len(creators),
        source_operations=list(source_operations),
    )


def _fill_collector(collector: MemoryResultCollector, result: CrawlResult) -> None:
    for item in result.creators:
        collector.store_creator(item)
    for item in result.contents:
        collector.store_content(item)
    for item in result.comments:
        collector.store_comment(item)


def _crawl_douyin(
    run_config: CrawlerRunConfig,
    collector: MemoryResultCollector,
    *,
    proxies: dict[str, str] | None = None,
) -> dict[str, Any]:
    max_notes = max(1, int(run_config.max_notes_count))
    interval = max(0.0, float(run_config.max_sleep_sec))

    if run_config.crawl_type == "search":
        # 抖音搜索风控与出口 IP 强相关：代理 IP≠登录 IP 时，首搜易过、连搜必 verify_check
        client = DouyinClient(cookie=_require_cookie(run_config), proxies=None)
        page_size = 10
        max_pages = max(1, math.ceil(max_notes / page_size))
        keywords = list(run_config.keywords)
        all_contents: list[dict[str, Any]] = []
        # 默认词间间隔至少 6s，与 search_gate 一致
        gap = max(interval if interval > 0 else 6.0, 6.0)
        for index, keyword in enumerate(keywords):
            page = client.search_pages(
                keyword,
                max_pages=max_pages,
                page_size=page_size,
                page_interval=gap,
            )
            all_contents.extend(page.get("contents") or [])
            if len(all_contents) >= max_notes:
                break
            if index + 1 < len(keywords) and gap > 0:
                time.sleep(gap)
        return {
            "platform": "dy",
            "crawl_type": "search",
            "keywords": keywords,
            "contents": all_contents[:max_notes],
            "creators": [],
            "comments": [],
        }

    client = DouyinClient(cookie=_require_cookie(run_config), proxies=proxies)
    if run_config.crawl_type == "creator":
        url = (run_config.creator_url or "").strip()
        if not url:
            raise ValueError("缺少 creator_url")
        return client.get_creator_bundle(
            url,
            max_notes=max_notes,
            interval=interval or 1.0,
            with_posts=True,
            on_creator=collector.store_creator,
        )

    if run_config.crawl_type == "detail":
        url = (run_config.content_url or "").strip()
        if not url:
            raise ValueError("缺少 content_url")
        return client.get_detail_bundle(url)

    raise ValueError(f"不支持的 crawl_type: {run_config.crawl_type}")


def _crawl_xhs(
    run_config: CrawlerRunConfig,
    collector: MemoryResultCollector,
    *,
    proxies: dict[str, str] | None = None,
) -> dict[str, Any]:
    client = XhsClient(cookie=_require_cookie(run_config), proxies=proxies)
    max_notes = max(1, int(run_config.max_notes_count))
    interval = max(0.0, float(run_config.max_sleep_sec))

    if run_config.crawl_type == "search":
        # 小红书搜索 page_size 需为 20，否则常返回空
        page_size = 20
        max_pages = max(1, math.ceil(max_notes / page_size))
        keywords = list(run_config.keywords)
        all_contents: list[dict[str, Any]] = []
        for keyword in keywords:
            page = client.search_notes_pages(
                keyword,
                start_page=max(1, int(run_config.start_page)),
                max_pages=max_pages,
                page_size=page_size,
                interval=interval or 0.8,
                page_interval=interval or 1.5,
                with_detail=True,
                max_contents=max_notes - len(all_contents),
            )
            all_contents.extend(page.get("contents") or [])
            if len(all_contents) >= max_notes:
                break
        return {
            "platform": "xhs",
            "crawl_type": "search",
            "keywords": keywords,
            "contents": all_contents[:max_notes],
            "creators": [],
            "comments": [],
        }

    if run_config.crawl_type == "creator":
        target = (run_config.creator_url or "").strip()
        if not target:
            raise ValueError("缺少 creator_url")
        if target.startswith("http"):
            info = parse_creator_url(target)
            user_id = info["user_id"]
            xsec_token = info["xsec_token"]
            xsec_source = info["xsec_source"] or "pc_feed"
            creator_url = target.split("?")[0]
        else:
            user_id = target
            xsec_token = ""
            xsec_source = "pc_feed"
            creator_url = f"https://www.xiaohongshu.com/user/profile/{user_id}"

        creators: list[dict[str, Any]] = []
        raw_profile = client.get_creator_info(
            user_id, xsec_token=xsec_token, xsec_source=xsec_source
        )
        creator = normalize_creator(user_id, raw_profile)
        if creator:
            creators.append(creator)
            collector.store_creator(creator)

        raw_notes = client.get_all_notes_by_creator(
            user_id,
            max_notes=max_notes,
            crawl_interval=interval or 1.0,
            xsec_token=xsec_token,
            xsec_source=xsec_source,
        )
        contents = client.enrich_notes_with_detail(
            raw_notes,
            default_xsec_token=xsec_token,
            default_xsec_source=xsec_source,
            interval=interval or 0.8,
            detail_limit=run_config.max_detail_count,
            max_concurrency=run_config.detail_concurrency,
        )
        return {
            "platform": "xhs",
            "crawl_type": "creator",
            "creator_url": creator_url,
            "creators": creators,
            "contents": contents[:max_notes],
            "comments": [],
        }

    if run_config.crawl_type == "detail":
        url = (run_config.content_url or "").strip()
        if not url:
            raise ValueError("缺少 content_url")
        return client.get_detail_bundle(url)

    raise ValueError(f"不支持的 crawl_type: {run_config.crawl_type}")


def crawl_http_sync(
    run_config: CrawlerRunConfig,
    collector: MemoryResultCollector,
    proxies: dict[str, str] | None = None,
) -> CrawlResult:
    """同步执行 HTTP 采集，并把结果写入 collector。"""
    platform = str(run_config.platform)
    if platform == "ks":
        raise UnsupportedPlatformError("快手采集已下线")
    if platform not in SUPPORTED_HTTP_PLATFORMS:
        raise UnsupportedPlatformError("不支持的平台")

    # 开启 IP 代理时禁止直连：未传入则自动租赁 sticky 代理
    proxies = resolve_requests_proxies(
        proxies,
        enabled=bool(run_config.enable_ip_proxy),
    )
    if run_config.enable_ip_proxy and not proxies:
        raise RuntimeError("已开启 IP 代理但未能获取可用代理，拒绝直连")

    if platform == "dy":
        payload = _crawl_douyin(run_config, collector, proxies=proxies)
    else:
        payload = _crawl_xhs(run_config, collector, proxies=proxies)

    result = _dict_to_partial(run_config, payload)
    _fill_collector(collector, result)
    return result
