# -*- coding: utf-8 -*-
"""抖音字段对齐 apispider/mediaspider stores/douyin + CrawlResult。"""

from __future__ import annotations

import hashlib
import re
from typing import Any, Dict, List, Optional
from urllib.parse import quote

_HASHTAG_RE = re.compile(r"#([^\s#@]{1,40})")


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


def _url_is_watermarked(url: str) -> bool:
    u = (url or "").lower()
    return "tplv-dy-water" in u or "watermark" in u


def _pick_best_url(urls: List[str]) -> str:
    """优先无水印、jpeg/原图清晰链接。"""
    cands = [u for u in urls if isinstance(u, str) and u.startswith("http")]
    if not cands:
        return ""
    clean = [u for u in cands if not _url_is_watermarked(u)]
    pool = clean or cands
    # jpeg 通常比 webp 更通用
    for u in reversed(pool):
        if ".jpeg" in u.split("?", 1)[0] or u.split("?", 1)[0].endswith(".jpg"):
            return u
    return pool[-1]


def _url_from_addr(addr: Any) -> str:
    if not isinstance(addr, dict):
        return ""
    return _pick_best_url(list(addr.get("url_list") or []))


def _extract_cover_url(aweme_detail: Dict) -> str:
    """作品封面：视频 cover / 图文首图。"""
    video = aweme_detail.get("video") or {}
    for key in ("cover", "origin_cover", "dynamic_cover", "ai_dynamic_cover"):
        url = _url_from_addr(video.get(key))
        if url:
            return url
    # 图文：image_post_info 或 images
    post = aweme_detail.get("image_post_info") or {}
    cover = post.get("cover") or {}
    url = _url_from_addr(cover.get("thumbnail") or cover) or _url_from_addr(cover)
    if url:
        return url
    images = aweme_detail.get("images") or post.get("images") or []
    for img in images:
        if not isinstance(img, dict):
            continue
        url = _image_origin_url(img)
        if url:
            return url
    return ""


def _image_origin_url(img: Dict[str, Any]) -> str:
    """单张图文：优先无水印原图（url_list），避免 download_url_list 水印版。"""
    candidates: List[str] = []

    for key in ("display_image", "origin_image", "large_image", "thumb"):
        node = img.get(key)
        if isinstance(node, dict):
            u = _url_from_addr(node)
            if u:
                candidates.append(u)

    for u in img.get("url_list") or []:
        if isinstance(u, str) and u.startswith("http"):
            candidates.append(u)

    node = img.get("download_url_list")
    if isinstance(node, list):
        candidates.extend(
            u for u in node if isinstance(u, str) and u.startswith("http")
        )
    elif isinstance(node, dict):
        u = _url_from_addr(node)
        if u:
            candidates.append(u)

    return _pick_best_url(candidates)


def _extract_image_list(aweme_detail: Dict) -> List[str]:
    """图文多图 URL 列表（无水印优先）；视频为空。"""
    out: List[str] = []
    post = aweme_detail.get("image_post_info") or {}
    images = aweme_detail.get("images") or post.get("images") or []
    for img in images:
        if not isinstance(img, dict):
            continue
        url = _image_origin_url(img)
        if url and url not in out:
            out.append(url)
    return out


def extract_hashtags(*texts: Any) -> List[str]:
    """从文案 / text_extra / cha_list 抽标签，去重保序。"""
    seen: set[str] = set()
    out: List[str] = []

    def add(tag: Any) -> None:
        name = str(tag or "").strip().lstrip("#")
        if not name or name in seen:
            return
        seen.add(name)
        out.append(name)

    for text in texts:
        if isinstance(text, dict):
            for te in text.get("text_extra") or []:
                if isinstance(te, dict):
                    add(te.get("hashtag_name") or te.get("hashtagName"))
            for cha in text.get("cha_list") or []:
                if isinstance(cha, dict):
                    add(cha.get("cha_name") or cha.get("chaName") or cha.get("title"))
            for m in _HASHTAG_RE.findall(str(text.get("desc") or text.get("title") or "")):
                add(m)
        else:
            for m in _HASHTAG_RE.findall(str(text or "")):
                add(m)
    return out


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
    image_list = _extract_image_list(aweme_item) if is_image else []
    title = aweme_item.get("desc", "") or ""
    return {
        "aweme_id": aweme_id,
        "title": title,
        "type": "image" if is_image else "video",
        "desc": title,
        "tags": extract_hashtags(aweme_item, title),
        "create_time": aweme_item.get("create_time"),
        "creator_hash": anonymize_user_id(author_id),
        "nickname": mask_nickname(nickname),
        "display_name": str(nickname or "").strip()[:100],
        "profile_url": build_public_profile_url(author_id),
        "liked_count": stats.get("digg_count"),
        "collected_count": stats.get("collect_count"),
        "comment_count": stats.get("comment_count"),
        "share_count": stats.get("share_count"),
        "aweme_url": (
            f"https://www.douyin.com/"
            f"{'note' if is_image else 'video'}/{aweme_id}"
        ),
        "cover_url": _extract_cover_url(aweme_item),
        "image_list": image_list,
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

    avatar = ""
    for key in ("avatar_300x300", "avatar_medium", "avatar_168x168", "avatar_thumb"):
        url_list = (raw.get(key) or {}).get("url_list") or []
        if url_list:
            avatar = url_list[-1]
            break

    gender_map = {0: "未知", 1: "男", 2: "女"}
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
        "fans_count": first_not_none(
            raw.get("fans_count"),
            raw.get("max_follower_count"),
            raw.get("follower_count"),
            raw.get("fans"),
        ),
        "works_count": first_not_none(
            raw.get("works_count"),
            raw.get("aweme_count"),
        ),
        "liked_count": raw.get("liked_count", raw.get("total_favorited")),
        "interaction_count": raw.get("interaction_count"),
    }


def normalize_comment(
    comment_item: Optional[Dict[str, Any]],
    *,
    aweme_id: str = "",
    creator_sec_uid: str = "",
    parent_comment_id: str = "",
    reply_to_comment_id: str = "",
    reply_to_text: str = "",
    reply_to_display_name: str = "",
) -> Optional[Dict[str, Any]]:
    """归一化抖音评论（一级或二级）。

    二级评论会带 reply_to_*；is_creator=True 表示博主本人回复。
    """
    if not comment_item:
        return None
    cid = comment_item.get("cid") or comment_item.get("comment_id")
    if not cid:
        return None
    user = comment_item.get("user") or {}
    sec = str(user.get("sec_uid") or user.get("sec_user_id") or "").strip()
    uid = str(user.get("uid") or "")
    nickname = user.get("nickname") or ""
    creator_sec = (creator_sec_uid or "").strip()
    is_creator = bool(creator_sec and sec and sec == creator_sec)

    # 接口偶发自带回复对象
    reply_to_id = str(
        reply_to_comment_id
        or comment_item.get("reply_id")
        or comment_item.get("reply_to_reply_id")
        or parent_comment_id
        or ""
    )
    if reply_to_id in ("0", "None"):
        reply_to_id = parent_comment_id or ""
    reply_name = (
        reply_to_display_name
        or comment_item.get("reply_to_username")
        or comment_item.get("reply_to_user_name")
        or ""
    )
    reply_text = reply_to_text or ""

    return {
        "comment_id": str(cid),
        "aweme_id": str(aweme_id or comment_item.get("aweme_id") or ""),
        "text": str(comment_item.get("text") or ""),
        "create_time": comment_item.get("create_time"),
        "liked_count": comment_item.get("digg_count"),
        "reply_count": comment_item.get("reply_comment_total")
        or comment_item.get("reply_count")
        or 0,
        "creator_hash": anonymize_user_id(sec or uid),
        "nickname": mask_nickname(nickname),
        "display_name": str(nickname).strip()[:100],
        "profile_url": build_public_profile_url(sec),
        "sec_uid": sec,
        "uid": uid,
        "ip_location": comment_item.get("ip_label")
        or comment_item.get("ip_location")
        or "",
        "parent_comment_id": str(parent_comment_id or ""),
        "reply_to_comment_id": reply_to_id,
        "reply_to_text": str(reply_text)[:200],
        "reply_to_display_name": str(reply_name).strip()[:100],
        "is_creator": is_creator,
        "replies": [],
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
    from platforms.common.store import crawl_result as _crawl_result

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
