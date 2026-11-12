# -*- coding: utf-8 -*-
"""
把小红书接口原始数据整理成 MediaCrawler store/xhs 同款结构。

参考:
- MediaCrawler/store/xhs/__init__.py  update_xhs_note / save_creator
"""

from __future__ import annotations

import json
import time
from typing import Any, Dict, List, Optional
from urllib.parse import quote, urlencode


def _now_ts() -> int:
    return int(time.time() * 1000)


def _parse_media_v2(video_dict: Dict) -> Dict:
    media_v2 = video_dict.get("media_v2")
    if isinstance(media_v2, str) and media_v2.strip():
        try:
            return json.loads(media_v2)
        except json.JSONDecodeError:
            return {}
    return media_v2 if isinstance(media_v2, dict) else {}


def _collect_streams(video_dict: Dict) -> List[Dict]:
    """收集 media / media_v2 下各编码流。"""
    streams: List[Dict] = []
    candidates = [video_dict.get("media") or {}, _parse_media_v2(video_dict)]
    for media in candidates:
        stream = (media.get("stream") or {}) if isinstance(media, dict) else {}
        if not isinstance(stream, dict):
            continue
        for codec_list in stream.values():
            if isinstance(codec_list, list):
                streams.extend([s for s in codec_list if isinstance(s, dict)])
    return streams


def get_video_url_arr(note_item: Dict) -> List[str]:
    """对齐 MediaCrawler：优先无水印 origin，其次非 WM 转码流。"""
    if note_item.get("type") != "video":
        return []
    video_dict = note_item.get("video") or {}
    if not video_dict:
        return []

    # 1) MediaCrawler 主路径：consumer.origin_video_key（无水印原片）
    consumer = video_dict.get("consumer") or {}
    origin_video_key = consumer.get("origin_video_key") or consumer.get("originVideoKey") or ""
    if origin_video_key:
        return [f"http://sns-video-bd.xhscdn.com/{origin_video_key}"]

    # 2) 从流列表里挑：排除 stream_desc 含 WM_ 的水印流
    streams = _collect_streams(video_dict)
    if not streams:
        return []

    def score(item: Dict) -> tuple:
        desc = str(item.get("stream_desc") or "")
        is_wm = 1 if "WM" in desc.upper() else 0
        # 非水印优先；同档按 weight / 分辨率 / 码率
        width = int(item.get("width") or 0)
        height = int(item.get("height") or 0)
        weight = int(item.get("weight") or 0)
        bitrate = int(item.get("avg_bitrate") or item.get("video_bitrate") or 0)
        return (is_wm, -weight, -(width * height), -bitrate)

    ranked = sorted(
        [s for s in streams if s.get("master_url")],
        key=score,
    )
    if not ranked:
        return []

    # 只返回最优一条。多条用逗号拼接后整段打开会 403。
    return [ranked[0]["master_url"]]


def build_note_url(
    note_id: str,
    xsec_token: str = "",
    xsec_source: str = "pc_search",
) -> str:
    note_id = quote(str(note_id or ""), safe="-._~")
    base = f"https://www.xiaohongshu.com/explore/{note_id}"
    token = (xsec_token or "").strip()
    source = (xsec_source or "").strip()
    if not token:
        return base
    return f"{base}?{urlencode({'xsec_token': token, 'xsec_source': source or 'pc_search'})}"


def _live_photo_url(img: Dict[str, Any]) -> str:
    """live 图动图流：优先 h264 master_url。"""
    stream = img.get("stream") or {}
    if not isinstance(stream, dict):
        return ""
    for codec in ("h264", "h265", "h266", "av1"):
        items = stream.get(codec) or []
        if not isinstance(items, list):
            continue
        for item in items:
            if isinstance(item, dict) and item.get("master_url"):
                return str(item["master_url"])
    return ""


def _image_export_url(img: Dict[str, Any]) -> str:
    """普通图用静图 URL；live 图优先保存 live 视频流。"""
    if img.get("live_photo"):
        live_url = _live_photo_url(img)
        if live_url:
            return live_url
    return (
        img.get("url")
        or img.get("url_default")
        or ""
    )


def build_profile_url(user_id: str) -> str:
    uid = str(user_id or "").strip()
    if not uid:
        return ""
    return f"https://www.xiaohongshu.com/user/profile/{quote(uid, safe='-._~')}"


def normalize_note_item(
    note_item: Dict[str, Any],
    *,
    source_keyword: str = "",
    xsec_source: str = "pc_search",
) -> Optional[Dict[str, Any]]:
    """对齐 MediaCrawler.update_xhs_note 的 local_db_item。"""
    if not note_item:
        return None

    note_id = note_item.get("note_id") or note_item.get("id")
    if not note_id:
        return None

    user_info = note_item.get("user") or {}
    interact_info = note_item.get("interact_info") or {}
    image_list: List[Dict] = list(note_item.get("image_list") or [])
    tag_list: List[Dict] = list(note_item.get("tag_list") or [])

    for img in image_list:
        if img.get("url_default"):
            img["url"] = img.get("url_default")

    xsec_token = note_item.get("xsec_token") or ""
    xsec_source = note_item.get("xsec_source") or xsec_source

    image_urls = [
        url for url in (_image_export_url(img) for img in image_list) if url
    ]

    user_id = str(user_info.get("user_id") or "")
    nickname = user_info.get("nickname") or user_info.get("nick_name") or ""

    return {
        "note_id": note_id,
        "type": note_item.get("type"),
        "title": note_item.get("title")
        or note_item.get("display_title")
        or (note_item.get("desc") or "")[:255],
        "desc": note_item.get("desc") or "",
        "video_url": (get_video_url_arr(note_item) or [""])[0],
        "time": note_item.get("time"),
        "last_update_time": note_item.get("last_update_time", 0),
        "user_id": user_id,
        "nickname": nickname,
        "profile_url": build_profile_url(user_id),
        "liked_count": interact_info.get("liked_count"),
        "collected_count": interact_info.get("collected_count"),
        "comment_count": interact_info.get("comment_count"),
        "share_count": interact_info.get("share_count")
        or interact_info.get("shared_count"),
        "image_list": ",".join(image_urls),
        "tag_list": ",".join(
            tag.get("name", "") for tag in tag_list if tag.get("type") == "topic"
        ),
        "last_modify_ts": _now_ts(),
        "note_url": build_note_url(str(note_id), xsec_token, xsec_source),
        "source_keyword": source_keyword,
        "xsec_token": xsec_token,
        "xsec_source": xsec_source,
    }


def normalize_search_item(
    post_item: Dict[str, Any],
    *,
    source_keyword: str = "",
) -> Optional[Dict[str, Any]]:
    """搜索列表项 → MediaCrawler 笔记结构。

    跳过 rec_query / hot_query（与 MediaCrawler.search 过滤一致）。
    """
    if not post_item:
        return None
    if post_item.get("model_type") in ("rec_query", "hot_query"):
        return None

    note_card = dict(post_item.get("note_card") or {})
    if not note_card and post_item.get("note_id"):
        note_card = dict(post_item)

    note_card.setdefault("note_id", post_item.get("id") or post_item.get("note_id"))
    note_card.setdefault("xsec_token", post_item.get("xsec_token") or "")
    note_card.setdefault(
        "xsec_source", post_item.get("xsec_source") or "pc_search"
    )
    return normalize_note_item(
        note_card, source_keyword=source_keyword, xsec_source="pc_search"
    )


def normalize_search_response(
    data: Dict[str, Any],
    *,
    source_keyword: str = "",
) -> Dict[str, Any]:
    from .store import crawl_result

    items = []
    for post_item in data.get("items") or []:
        note = normalize_search_item(post_item, source_keyword=source_keyword)
        if note:
            items.append(note)
    return crawl_result(
        platform="xhs",
        crawl_type="search",
        keywords=[source_keyword] if source_keyword else [],
        contents=items,
        has_more=bool(data.get("has_more")),
    )


def normalize_creator(user_id: str, creator: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """对齐 mediaspider build_safe_creator('xhs', ...)。"""
    if not creator:
        return None

    user_info = creator.get("basicInfo") or {}
    follows = fans = interaction = None
    for item in creator.get("interactions") or []:
        t = item.get("type")
        if t == "follows":
            follows = item.get("count")
        elif t == "fans":
            fans = item.get("count")
        elif t == "interaction":
            interaction = item.get("count")

    nickname = user_info.get("nickname") or ""
    bio = user_info.get("desc") or user_info.get("description") or ""
    red_id = user_info.get("redId") or user_info.get("red_id") or ""
    return {
        "platform": "xhs",
        "creator_hash": str(user_id or ""),
        "user_id": str(user_id or ""),
        "red_id": red_id,
        "nickname": nickname,
        "display_name": str(nickname).strip()[:100],
        "profile_url": build_profile_url(user_id),
        "bio": bio,
        "avatar": user_info.get("images") or "",
        "gender": {0: "男", 1: "女"}.get(user_info.get("gender"), "未知"),
        "ip_location": user_info.get("ipLocation") or "",
        "following_count": follows,
        "fans_count": fans,
        "works_count": None,
        "liked_count": None,
        "interaction_count": interaction,
    }


def normalize_creator_notes(
    notes: List[Dict[str, Any]],
    *,
    xsec_source: str = "pc_feed",
) -> List[Dict[str, Any]]:
    result = []
    for note in notes or []:
        item = dict(note)
        item.setdefault("xsec_source", note.get("xsec_source") or xsec_source)
        normalized = normalize_note_item(item, xsec_source=xsec_source)
        if normalized:
            result.append(normalized)
    return result
