from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit

from app.services.tikhub_service.models import (
    TikHubAccount,
    TikHubContent,
    TikHubPlatform,
)


_COUNT_PATTERN = re.compile(r"^([+-]?\d+(?:\.\d+)?)\s*([万亿]?)\s*\+?$")
_COUNT_MULTIPLIERS = {"": 1, "万": 10_000, "亿": 100_000_000}


def _integer(value: Any) -> int:
    if isinstance(value, (int, float, Decimal)):
        try:
            return max(0, int(value))
        except (TypeError, ValueError, OverflowError):
            return 0
    text = str(value or "").strip().replace(",", "").replace("，", "")
    match = _COUNT_PATTERN.fullmatch(text)
    if not match:
        return 0
    try:
        number = Decimal(match.group(1))
    except InvalidOperation:
        return 0
    return max(0, int(number * _COUNT_MULTIPLIERS[match.group(2)]))


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _metric_value(item: dict[str, Any], *keys: str) -> Any:
    """从平台卡片及常见互动容器读取指标，兼容搜索与详情响应。"""

    queue = [item]
    seen: set[int] = set()
    container_keys = (
        "statistics",
        "interact_info",
        "interaction_info",
        "counts",
        "note_card",
        "note",
        "data",
    )
    while queue:
        node = queue.pop(0)
        if id(node) in seen:
            continue
        seen.add(id(node))
        for key in keys:
            if node.get(key) not in (None, ""):
                return node[key]
        queue.extend(
            node[key]
            for key in container_keys
            if isinstance(node.get(key), dict)
        )
    return 0


def _first(*values: Any) -> str:
    return str(next((value for value in values if value not in (None, "")), ""))


def _string_value(*values: Any) -> str:
    """返回首个非空字符串，避免把上游对象或数组误当成 URL。"""

    return next(
        (
            value.strip()
            for value in values
            if isinstance(value, str) and value.strip()
        ),
        "",
    )


def _media_url(value: Any) -> str:
    """从平台图片对象中读取首个 HTTP(S) 地址，并统一为 HTTPS。"""

    if isinstance(value, str):
        candidate = value.strip()
        if candidate.startswith("http://"):
            candidate = f"https://{candidate.removeprefix('http://')}"
        if not candidate.startswith("https://"):
            return ""
        parsed = urlsplit(candidate)
        # 抖音图片列表通常先给 HEIC/HEIF，后给带独立签名的 JPEG。不能只改
        # 扩展名：CDN 签名包含图片格式，沿用 HEIC 签名请求 JPEG 会返回 403。
        # 返回空值让列表解析继续选择官方提供的浏览器兼容地址。
        if parsed.path.lower().endswith((".heic", ".heif")):
            return ""
        return candidate
    if isinstance(value, list):
        for item in value:
            candidate = _media_url(item)
            if candidate:
                return candidate
        return ""
    if isinstance(value, dict):
        for key in (
            "url_list",
            "url",
            "image",
            "profile_cover_list",
            "cover_list",
            "url_size_large",
            "url_default",
            "url_pre",
        ):
            candidate = _media_url(value.get(key))
            if candidate:
                return candidate
    return ""


def _xiaohongshu_content_url(item: dict[str, Any], content_id: str) -> str:
    """保留搜索结果的访问令牌，构造可直接打开的小红书笔记链接。"""

    encoded_id = quote(content_id, safe="-._~")
    base_url = (
        f"https://www.xiaohongshu.com/explore/{encoded_id}"
        if encoded_id
        else ""
    )
    explicit_url = _string_value(
        item.get("share_url"),
        item.get("note_url"),
        item.get("url"),
        _mapping(item.get("mini_program_info")).get("webpage_url"),
        _mapping(item.get("qq_mini_program_info")).get("webpage_url"),
    )
    candidate = explicit_url or base_url
    token = _string_value(item.get("xsec_token"))
    if not candidate or not token:
        return candidate

    parsed = urlsplit(candidate)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        parsed = urlsplit(base_url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query["xsec_token"] = token
    query["xsec_source"] = _string_value(item.get("xsec_source")) or "pc_search"
    return urlunsplit(
        (parsed.scheme, parsed.netloc, parsed.path, urlencode(query), parsed.fragment)
    )


def _content_type(
    platform: TikHubPlatform,
    item: dict[str, Any],
    video: dict[str, Any],
) -> str:
    explicit = _first(item.get("type"), item.get("note_type")).strip().lower()
    if platform != TikHubPlatform.DOUYIN:
        return explicit

    # 抖音主页作品接口使用 aweme_type 数字枚举，而不是通用 type 字段。
    # 图文响应即使带 video 占位结构，也应优先依据 images/aweme_type 判断。
    image_post_info = _mapping(item.get("image_post_info"))
    has_images = bool(item.get("images") or image_post_info.get("images"))
    raw_aweme_type = item.get("aweme_type")
    aweme_type = "" if raw_aweme_type is None else str(raw_aweme_type).strip()
    if has_images or aweme_type in {"1", "2", "68"}:
        return "image"
    if aweme_type == "0" or video:
        return "video"
    return explicit


def normalize_account(
    platform: TikHubPlatform,
    item: dict[str, Any],
) -> TikHubAccount:
    user = _mapping(item.get("user_info") or item.get("user") or item)
    stats = _mapping(user.get("statistics") or item.get("statistics"))
    user_id = _first(
        user.get("sec_uid"),
        user.get("sec_user_id"),
        user.get("user_id"),
        user.get("userid"),
        user.get("uid"),
        user.get("id"),
        user.get("eid"),
    )
    account_id = _first(
        user.get("unique_id"),
        user.get("short_id"),
        user.get("red_id"),
        user.get("redId"),
        user.get("redid"),
        user.get("account"),
        user_id,
    )
    if platform == TikHubPlatform.DOUYIN and user_id:
        profile_url = f"https://www.douyin.com/user/{user_id}"
    elif platform == TikHubPlatform.XIAOHONGSHU and user_id:
        profile_url = f"https://www.xiaohongshu.com/user/profile/{user_id}"
    elif platform == TikHubPlatform.KUAISHOU and user_id:
        profile_url = f"https://www.kuaishou.com/profile/{user_id}"
    else:
        profile_url = ""
    return TikHubAccount(
        platform=platform,
        accountId=account_id,
        userId=user_id,
        name=_first(user.get("nickname"), user.get("name"), user.get("user_name")),
        avatarUrl=(
            _media_url(user.get("avatar_url"))
            or _media_url(user.get("avatar"))
            or _media_url(user.get("imageb"))
            or _media_url(user.get("images"))
            or _media_url(user.get("avatar_larger"))
            or _media_url(user.get("avatar_medium"))
            or _media_url(user.get("avatar_thumb"))
        ),
        description=_first(user.get("signature"), user.get("desc"), user.get("description")),
        profileUrl=_first(user.get("profile_url"), user.get("author_url"), profile_url),
        followers=_integer(
            user.get("follower_count")
            or user.get("mplatform_followers_count")
            or user.get("fans_count")
            or user.get("fans")
            or stats.get("follower_count")
        ),
        follows=_integer(
            user.get("following_count")
            or user.get("follows")
            or stats.get("following_count")
        ),
        contentCount=_integer(
            user.get("aweme_count")
            or user.get("notes_count")
            or user.get("ndiscovery")
            or user.get("photo_count")
            or stats.get("aweme_count")
        ),
        totalLikes=_integer(
            user.get("total_favorited")
            or user.get("liked_count")
            or user.get("liked")
            or stats.get("total_favorited")
        ),
        ipLocation=_first(user.get("ip_location"), user.get("ipLocation")),
        raw=dict(item),
    )


def normalize_content(
    platform: TikHubPlatform,
    item: dict[str, Any],
    *,
    author_profile_url: str = "",
) -> TikHubContent:
    author = _mapping(item.get("author") or item.get("user") or item.get("user_info"))
    video = _mapping(item.get("video"))
    content_id = _first(
        item.get("aweme_id"),
        item.get("note_id"),
        item.get("photo_id"),
        item.get("id"),
    )
    author_id = _first(
        author.get("sec_uid"),
        author.get("sec_user_id"),
        author.get("userid"),
        author.get("user_id"),
        author.get("uid"),
        author.get("id"),
    )
    if platform == TikHubPlatform.DOUYIN:
        content_url = f"https://www.douyin.com/video/{content_id}" if content_id else ""
        author_url = f"https://www.douyin.com/user/{author_id}" if author_id else ""
    elif platform == TikHubPlatform.XIAOHONGSHU:
        content_url = _xiaohongshu_content_url(item, content_id)
        author_url = f"https://www.xiaohongshu.com/user/profile/{author_id}" if author_id else ""
    else:
        content_url = f"https://www.kuaishou.com/short-video/{content_id}" if content_id else ""
        author_url = f"https://www.kuaishou.com/profile/{author_id}" if author_id else ""
    return TikHubContent(
        platform=platform,
        contentId=content_id,
        title=_first(item.get("title"), item.get("caption"), item.get("desc")),
        description=_first(item.get("desc"), item.get("caption"), item.get("description")),
        contentUrl=(
            content_url
            if platform in {TikHubPlatform.DOUYIN, TikHubPlatform.XIAOHONGSHU}
            else _string_value(item.get("share_url"), item.get("url"), content_url)
        ),
        coverUrl=(
            _media_url(item.get("cover_url"))
            or _media_url(item.get("cover"))
            or _media_url(item.get("image_list"))
            or _media_url(item.get("images_list"))
            or _media_url(item.get("images"))
            or _media_url(video.get("cover"))
            or _media_url(video.get("origin_cover"))
            or _media_url(video.get("dynamic_cover"))
            or _media_url(video.get("animated_cover"))
        ),
        authorId=author_id,
        authorName=_first(author.get("nickname"), author.get("name"), author.get("user_name")),
        authorUrl=_first(
            author.get("profile_url"),
            author.get("author_url"),
            author_profile_url,
            author_url,
        ),
        authorAvatarUrl=(
            _media_url(author.get("avatar_url"))
            or _media_url(author.get("avatar"))
            or _media_url(author.get("imageb"))
            or _media_url(author.get("images"))
            or _media_url(author.get("avatar_larger"))
            or _media_url(author.get("avatar_medium"))
            or _media_url(author.get("avatar_thumb"))
        ),
        authorFollowers=_integer(
            author.get("follower_count")
            or author.get("fans_count")
            or author.get("fans")
        ),
        authorContentCount=_integer(
            author.get("aweme_count")
            or author.get("notes_count")
            or author.get("ndiscovery")
            or author.get("photo_count")
        ),
        authorTotalLikes=_integer(
            author.get("total_favorited")
            or author.get("liked_count")
            or author.get("liked")
        ),
        publishedAt=_first(
            item.get("create_time"),
            item.get("timestamp"),
            item.get("time"),
            item.get("publish_time"),
        ),
        duration=_integer(item.get("duration")),
        likeCount=_integer(
            _metric_value(
                item,
                "digg_count",
                "liked_count",
                "liked_count_str",
                "like_count",
                "likes_count",
                "likes",
            )
        ),
        commentCount=_integer(
            _metric_value(
                item,
                "comment_count",
                "comment_count_str",
                "comments_count",
                "comments",
            )
        ),
        shareCount=_integer(
            _metric_value(
                item,
                "share_count",
                "share_count_str",
                "shares_count",
                "shared_count",
            )
        ),
        collectCount=_integer(
            _metric_value(
                item,
                "collect_count",
                "collected_count",
                "collected_count_str",
                "collects_count",
                "favorite_count",
                "collections",
            )
        ),
        readCount=_integer(
            _metric_value(
                item,
                "play_count",
                "view_count",
                "read_count",
                "views",
            )
        ),
        contentType=_content_type(platform, item, video),
        raw=dict(item),
    )
