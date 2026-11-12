# -*- coding: utf-8 -*-
"""抖音字段对齐 apispider/mediaspider stores/douyin + CrawlResult。"""

from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Any, Dict, List, Optional
from urllib.parse import quote, urlsplit


def _format_publish_time(value: Any) -> str:
    """抖音 create_time 一般为秒级时间戳。"""
    try:
        ts = int(value)
    except (TypeError, ValueError):
        return ""
    if ts <= 0:
        return ""
    if ts > 10_000_000_000:  # 毫秒
        ts //= 1000
    try:
        return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
    except (OverflowError, OSError, ValueError):
        return ""


def anonymize_user_id(user_id: Any) -> str:
    if user_id in (None, ""):
        return ""
    return hashlib.sha256(str(user_id).strip().encode()).hexdigest()[:16]


def mask_nickname(nickname: Any) -> str:
    value = str(nickname or "")
    if not value:
        return ""
    if len(value) <= 1:
        return "*"
    return f"{value[0]}***{value[-1]}" if len(value) > 2 else f"{value[0]}*"


def build_public_profile_url(sec_or_uid: Any) -> str:
    raw = str(sec_or_uid or "").strip()
    if not raw:
        return ""
    return f"https://www.douyin.com/user/{quote(raw, safe='-._~')}"


def _pick_gateway_url(url_list: list) -> str:
    """选 www.douyin.com/aweme/v1/play 网关（浏览器打开会带 Referer 跳转）。"""
    for u in url_list or []:
        if isinstance(u, str) and "douyin.com/aweme/v1/play/?" in u and "play/dash" not in u:
            if "watermark=1" not in u:
                return u
    for u in url_list or []:
        if isinstance(u, str) and "douyin.com/aweme/v1/play/?" in u and "play/dash" not in u:
            return u
    return ""


def _first_http_url(url_list: list) -> str:
    for u in url_list or []:
        if isinstance(u, str) and u.startswith("http") and "play/dash" not in u:
            return u
    return ""


def _extract_video_download_url(aweme_detail: Dict) -> str:
    """优先网关链接；没有再退到其它播放地址。"""
    video_item = aweme_detail.get("video") or {}
    groups = []
    for key in (
        "play_addr",
        "play_addr_h264",
        "play_addr_256",
        "play_addr_lowbr",
        "download_addr",
    ):
        url_list = (video_item.get(key) or {}).get("url_list") or []
        if url_list:
            groups.append(url_list)
    for br in video_item.get("bit_rate") or []:
        url_list = (br.get("play_addr") or {}).get("url_list") or []
        if url_list:
            groups.append(url_list)

    for group in groups:
        gateway = _pick_gateway_url(group)
        if gateway:
            return gateway
    for group in groups:
        fallback = _first_http_url(group)
        if fallback:
            return fallback
    return ""


def _extract_music_download_url(aweme_detail: Dict) -> str:
    play_url = (aweme_detail.get("music") or {}).get("play_url") or {}
    url_list = play_url.get("url_list") or []
    if url_list:
        return url_list[0]
    return play_url.get("uri") or ""


def _pick_cover_from_url_list(url_list: Any) -> str:
    """封面 url_list：优先第 2 条（与 MediaCrawler 一致），否则第一条 http。"""
    if not isinstance(url_list, list):
        return ""
    http_urls = [
        u for u in url_list if isinstance(u, str) and u.startswith("http")
    ]
    if len(http_urls) > 1:
        return http_urls[1]
    return http_urls[0] if http_urls else ""


def _extract_cover_url(aweme_detail: Dict) -> str:
    """视频封面优先；图文取首图。"""
    video_item = aweme_detail.get("video") or {}
    for key in ("raw_cover", "origin_cover", "cover", "dynamic_cover"):
        cover = video_item.get(key) or {}
        if isinstance(cover, dict):
            url = _pick_cover_from_url_list(cover.get("url_list"))
            if url:
                return url

    for img in aweme_detail.get("images") or []:
        if not isinstance(img, dict):
            continue
        url = _pick_cover_from_url_list(img.get("url_list"))
        if url:
            return url

    image_post = aweme_detail.get("image_post_info") or {}
    for img in image_post.get("images") or []:
        if not isinstance(img, dict):
            continue
        display = img.get("display_image") or img.get("origin_image") or img
        if isinstance(display, dict):
            url = _pick_cover_from_url_list(display.get("url_list"))
            if url:
                return url
    return ""


def _extract_author_avatar(author: Dict[str, Any]) -> str:
    for key in ("avatar_300x300", "avatar_medium", "avatar_168x168", "avatar_thumb"):
        avatar = author.get(key) or {}
        if not isinstance(avatar, dict):
            continue
        url_list = avatar.get("url_list") or []
        if isinstance(url_list, list):
            for url in reversed(url_list):
                if not isinstance(url, str) or not url.startswith("http"):
                    continue
                if urlsplit(url).path.lower().endswith((".heic", ".heif")):
                    continue
                return url
    return ""


def normalize_aweme(
    aweme_item: Optional[Dict[str, Any]],
    *,
    source_keyword: str = "",
) -> Optional[Dict[str, Any]]:
    """对齐 mediaspider.stores.douyin.update_douyin_aweme，并保留媒体下载地址。"""
    if not aweme_item:
        return None
    aweme_id = aweme_item.get("aweme_id")
    if not aweme_id:
        return None
    author = aweme_item.get("author") or {}
    stats = aweme_item.get("statistics") or {}
    author_id = author.get("sec_uid") or author.get("sec_user_id") or author.get("uid")
    is_image = bool(aweme_item.get("image_post_info") or aweme_item.get("images"))
    nickname = author.get("nickname")
    return {
        "aweme_id": aweme_id,
        "title": aweme_item.get("desc", "") or "",
        "type": "image" if is_image else "video",
        "desc": aweme_item.get("desc", "") or "",
        "create_time": aweme_item.get("create_time"),
        "publish_time": _format_publish_time(aweme_item.get("create_time")),
        "author_id": str(author_id or ""),
        "creator_hash": anonymize_user_id(author_id),
        "nickname": mask_nickname(nickname),
        "display_name": str(nickname or "").strip()[:100],
        "profile_url": build_public_profile_url(author_id),
        "avatar": _extract_author_avatar(author),
        "liked_count": stats.get("digg_count"),
        "collected_count": stats.get("collect_count"),
        "comment_count": stats.get("comment_count"),
        "share_count": stats.get("share_count"),
        "aweme_url": (
            f"https://www.douyin.com/"
            f"{'note' if is_image else 'video'}/{aweme_id}"
        ),
        "cover_url": _extract_cover_url(aweme_item),
        "video_download_url": _extract_video_download_url(aweme_item),
        "music_download_url": _extract_music_download_url(aweme_item),
        "source_keyword": source_keyword,
    }


def extract_aweme_from_search_item(post_item: Dict) -> Optional[Dict]:
    if not post_item:
        return None
    aweme = post_item.get("aweme_info")
    if aweme:
        return aweme
    mix = post_item.get("aweme_mix_info") or {}
    items = mix.get("mix_items") or []
    if items:
        return items[0]
    return None


def normalize_search_items(
    raw: Dict[str, Any],
    *,
    source_keyword: str = "",
) -> List[Dict[str, Any]]:
    contents: List[Dict[str, Any]] = []
    for item in raw.get("data") or []:
        try:
            aweme = extract_aweme_from_search_item(item)
        except Exception:
            continue
        normalized = normalize_aweme(aweme, source_keyword=source_keyword)
        if normalized:
            contents.append(normalized)
    return contents


def normalize_creator(sec_user_id: str, profile_res: Optional[Dict]) -> Optional[Dict]:
    """对齐 mediaspider build_safe_creator('dy', ...)，并补充可读简介字段。"""
    if not profile_res:
        return None
    raw = profile_res.get("user") or profile_res
    nickname = (
        raw.get("nickname")
        or raw.get("name")
        or raw.get("screen_name")
        or ""
    )
    creator_hash = anonymize_user_id(sec_user_id)
    if not creator_hash:
        return None

    def first_not_none(*values):
        return next((v for v in values if v is not None), None)

    signature = str(
        first_not_none(
            raw.get("signature"),
            raw.get("bio"),
            raw.get("desc"),
            raw.get("description"),
            "",
        )
    ).strip()

    avatar = _extract_author_avatar(raw)

    gender_map = {0: "未知", 1: "男", 2: "女"}
    current_fans_count = first_not_none(
        raw.get("follower_count"),
        raw.get("fans_count"),
        raw.get("fans"),
    )
    max_fans_count = first_not_none(
        raw.get("max_follower_count"),
        raw.get("max_fans_count"),
    )
    return {
        "platform": "dy",
        "creator_hash": creator_hash,
        "nickname": mask_nickname(nickname),
        "display_name": str(nickname).strip()[:100],
        "profile_url": build_public_profile_url(sec_user_id),
        "bio": signature,
        "avatar": avatar,
        "gender": gender_map.get(raw.get("gender"), "未知"),
        "ip_location": raw.get("ip_location") or "",
        "unique_id": raw.get("unique_id") or "",
        "uid": str(raw.get("uid") or ""),
        "following_count": first_not_none(
            raw.get("following_count"),
            raw.get("following"),
            raw.get("follows"),
        ),
        # fans_count 是当前值；最大值必须独立保留，不能作为当前值兜底。
        "fans_count": current_fans_count,
        "max_fans_count": max_fans_count,
        "works_count": first_not_none(
            raw.get("works_count"),
            raw.get("aweme_count"),
        ),
        "liked_count": raw.get("liked_count", raw.get("total_favorited")),
        "interaction_count": raw.get("interaction_count"),
    }


def crawl_result(
    *,
    crawl_type: str,
    keywords: Optional[List[str]] = None,
    creator_url: Optional[str] = None,
    content_url: Optional[str] = None,
    contents: Optional[List[Dict[str, Any]]] = None,
    creators: Optional[List[Dict[str, Any]]] = None,
    comments: Optional[List[Dict[str, Any]]] = None,
    **extra: Any,
) -> Dict[str, Any]:
    from ..common.store import crawl_result as _crawl_result

    return _crawl_result(
        platform="dy",
        crawl_type=crawl_type,
        keywords=keywords,
        creator_url=creator_url,
        content_url=content_url,
        contents=contents,
        creators=creators,
        comments=comments,
        **extra,
    )
