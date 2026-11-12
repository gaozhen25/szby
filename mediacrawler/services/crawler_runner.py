# -*- coding: utf-8 -*-
"""
程序化触发爬虫并返回结构化结果。

供 SDK ``keyword_ex`` 使用：直接调用爬虫生成数据，不依赖已有 CSV。
"""

from __future__ import annotations

import contextlib
from typing import Any, Iterator, Optional

import config
from services.sdk_json_export import export_creator_response, export_search_response
from services.xhs_creator_dataset import XhsCreatorDataset, XhsCreatorNote, XhsCreatorProfile
from services.xhs_creator_service import XhsCreatorService
from services.xhs_search_dataset import XhsSearchComment, XhsSearchDataset, XhsSearchNote
from services.xhs_search_service import XhsSearchService
from store.memory_collector import get_memory_collector, reset_memory_collector

SUPPORTED_PLATFORMS = frozenset({"xhs"})


@contextlib.contextmanager
def _override_config(**overrides: Any) -> Iterator[None]:
    saved: dict[str, Any] = {}
    for key, value in overrides.items():
        saved[key] = getattr(config, key)
        setattr(config, key, value)
    try:
        yield
    finally:
        for key, value in saved.items():
            setattr(config, key, value)


def _normalize_creator_id(platform: str, creator_id: str) -> str:
    """将博主 ID 或主页 URL 规范化为爬虫可识别的 creator 参数。"""
    creator_id = creator_id.strip()
    if not creator_id:
        raise ValueError("creator_id 不能为空")
    if platform != "xhs":
        raise ValueError(f"暂不支持的平台: {platform!r}")

    from media_platform.xhs.help import parse_creator_info_from_url

    info = parse_creator_info_from_url(creator_id)
    if info.xsec_token:
        return (
            f"https://www.xiaohongshu.com/user/profile/{info.user_id}"
            f"?xsec_token={info.xsec_token}&xsec_source={info.xsec_source or 'pc_search'}"
        )
    return info.user_id


def _build_creator_dataset_from_memory() -> XhsCreatorDataset:
    collector = get_memory_collector()
    profile = (
        XhsCreatorProfile.model_validate(collector.creator)
        if collector.creator
        else None
    )
    notes = [XhsCreatorNote.model_validate(row) for row in collector.note_list()]
    if profile and profile.user_id:
        notes = [note for note in notes if note.creator_hash == profile.user_id or not note.creator_hash]
    return XhsCreatorDataset(
        profile=profile,
        notes=notes,
        source_file="memory",
        note_count=len(notes),
    )


def _build_dataset_from_memory(keyword: str, with_comments: bool) -> XhsSearchDataset:
    collector = get_memory_collector()
    keyword = keyword.strip()
    notes = [
        XhsSearchNote.model_validate(row)
        for row in collector.note_list()
        if (row.get("source_keyword") or "").strip() == keyword
    ]
    comments: list[XhsSearchComment] = []
    if with_comments:
        note_ids = {note.note_id for note in notes}
        comments = [
            XhsSearchComment.model_validate(row)
            for row in collector.comment_list()
            if row.get("note_id") in note_ids
        ]

    return XhsSearchDataset(
        keywords=[keyword],
        notes=notes,
        comments=comments,
        source_file="memory",
        comments_file="memory" if with_comments else "",
        note_count=len(notes),
        comment_count=len(comments),
    )


async def _run_crawler(platform: str, overrides: dict[str, Any]) -> None:
    reset_memory_collector()
    base_overrides: dict[str, Any] = {
        "PLATFORM": platform,
        "SAVE_DATA_OPTION": "memory",
        "ENABLE_GET_MEIDAS": False,
    }
    base_overrides.update(overrides)

    with _override_config(**base_overrides):
        from main import CrawlerFactory

        crawler = CrawlerFactory.create_crawler(platform=platform)
        await crawler.start()


async def run_keyword_search(
    platform: str,
    keyword: str,
    *,
    login_type: str = "qrcode",
    max_notes_count: Optional[int] = None,
    enable_comments: bool = False,
    enable_sub_comments: bool = False,
    headless: Optional[bool] = None,
    cookies: str = "",
    start_page: int = 1,
) -> dict[str, Any]:
    """
    运行关键词搜索爬虫，返回标准 API dict 并写入 JSON。
    """
    platform = platform.strip().lower()
    keyword = keyword.strip()
    if not platform:
        raise ValueError("platform 不能为空")
    if not keyword:
        raise ValueError("keyword 不能为空")
    if platform not in SUPPORTED_PLATFORMS:
        supported = ", ".join(sorted(SUPPORTED_PLATFORMS))
        raise ValueError(f"暂不支持的平台: {platform!r}，当前支持: {supported}")

    overrides: dict[str, Any] = {
        "CRAWLER_TYPE": "search",
        "KEYWORDS": keyword,
        "LOGIN_TYPE": login_type,
        "ENABLE_GET_COMMENTS": enable_comments,
        "ENABLE_GET_SUB_COMMENTS": enable_sub_comments,
        "START_PAGE": start_page,
        "COOKIES": cookies,
    }
    if max_notes_count is not None:
        overrides["CRAWLER_MAX_NOTES_COUNT"] = max_notes_count
    if headless is not None:
        overrides["HEADLESS"] = headless
        overrides["CDP_HEADLESS"] = headless

    await _run_crawler(platform, overrides)

    dataset = _build_dataset_from_memory(keyword, with_comments=enable_comments)
    service = XhsSearchService()
    response = service.to_api_response(dataset)
    _, file_path = export_search_response(response, platform=platform, keyword=keyword)
    response["data"]["summary"]["source_file"] = file_path
    return response


async def run_creator_crawl(
    platform: str,
    creator_id: str,
    *,
    login_type: str = "qrcode",
    max_notes_count: Optional[int] = None,
    enable_comments: bool = False,
    enable_sub_comments: bool = False,
    headless: Optional[bool] = None,
    cookies: str = "",
) -> dict[str, Any]:
    """
    运行博主爬取，返回标准 API dict 并写入 JSON。
    """
    platform = platform.strip().lower()
    if not platform:
        raise ValueError("platform 不能为空")
    if platform not in SUPPORTED_PLATFORMS:
        supported = ", ".join(sorted(SUPPORTED_PLATFORMS))
        raise ValueError(f"暂不支持的平台: {platform!r}，当前支持: {supported}")

    creator_target = _normalize_creator_id(platform, creator_id)

    overrides: dict[str, Any] = {
        "CRAWLER_TYPE": "creator",
        "LOGIN_TYPE": login_type,
        "ENABLE_GET_COMMENTS": enable_comments,
        "ENABLE_GET_SUB_COMMENTS": enable_sub_comments,
        "COOKIES": cookies,
        "XHS_CREATOR_ID_LIST": [creator_target],
    }
    if max_notes_count is not None:
        overrides["CRAWLER_MAX_NOTES_COUNT"] = max_notes_count
    if headless is not None:
        overrides["HEADLESS"] = headless
        overrides["CDP_HEADLESS"] = headless

    await _run_crawler(platform, overrides)

    dataset = _build_creator_dataset_from_memory()
    service = XhsCreatorService()
    response = service.to_api_response(dataset)
    nickname = (response.get("data", {}).get("profile") or {}).get("nickname") or "unknown_creator"
    _, file_path = export_creator_response(response, platform=platform, nickname=nickname)
    response["data"]["summary"]["source_file"] = file_path
    return response
