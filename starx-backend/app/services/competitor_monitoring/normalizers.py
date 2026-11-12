"""把 MediaSpider 公开记录映射为竞品监控白名单字段。"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from .models import NormalizedCompetitor, NormalizedCompetitorVideo

ACCOUNT_METRICS = ("followers", "following", "works", "liked")
VIDEO_METRICS = ("likes", "comments", "shares", "plays", "collects")


def _count(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    if isinstance(value, float):
        return int(value) if value >= 0 else None
    text = str(value).strip().lower().replace(",", "")
    if not text:
        return None
    multiplier = 1
    for suffix, scale in (("万", 10_000), ("w", 10_000), ("k", 1_000)):
        if text.endswith(suffix):
            multiplier = scale
            text = text[: -len(suffix)].strip()
            break
    try:
        number = int(Decimal(text) * multiplier)
    except (InvalidOperation, ValueError):
        return None
    return number if number >= 0 else None


def _timestamp(value: Any) -> datetime | None:
    count = _count(value)
    if count is None:
        return None
    if count > 10_000_000_000:
        count //= 1000
    try:
        return datetime.fromtimestamp(count, tz=UTC)
    except (OverflowError, OSError, ValueError):
        return None


def metric_delta(
    current: dict[str, int | None], previous: dict[str, int | None]
) -> dict[str, int]:
    return {
        key: value - previous[key]
        for key, value in current.items()
        if isinstance(value, int)
        and not isinstance(value, bool)
        and isinstance(previous.get(key), int)
        and not isinstance(previous.get(key), bool)
    }


def normalize_account(platform: str, raw: dict[str, Any]) -> NormalizedCompetitor:
    metrics = {
        "followers": _count(raw.get("fans_count")),
        "following": _count(raw.get("following_count")),
        "works": _count(raw.get("works_count")),
        "liked": _count(raw.get("liked_count") or raw.get("interaction_count")),
    }
    return NormalizedCompetitor(
        platform=platform,
        name=str(raw.get("display_name") or raw.get("nickname") or "").strip()[:128],
        profile_url=str(raw.get("profile_url") or "").strip(),
        avatar_url=str(raw.get("avatar") or raw.get("avatar_url") or "").strip(),
        description=str(raw.get("bio") or raw.get("desc") or "").strip(),
        metrics=metrics,
    )


def normalize_video(platform: str, raw: dict[str, Any]) -> NormalizedCompetitor:
    metrics = {
        "likes": _count(raw.get("liked_count")),
        "comments": _count(raw.get("comment_count")),
        "shares": _count(raw.get("share_count")),
        "plays": _count(
            raw.get("viewd_count")
            if raw.get("viewd_count") is not None
            else raw.get("view_count") or raw.get("play_count")
        ),
        "collects": _count(raw.get("collected_count")),
    }
    return NormalizedCompetitor(
        platform=platform,
        platform_content_id=str(
            raw.get("note_id")
            or raw.get("aweme_id")
            or raw.get("video_id")
            or raw.get("content_id")
            or ""
        ).strip(),
        title=str(raw.get("title") or raw.get("desc") or "").strip()[:255],
        description=str(raw.get("desc") or "").strip(),
        content_url=str(
            raw.get("note_url")
            or raw.get("aweme_url")
            or raw.get("video_url")
            or ""
        ).strip(),
        cover_url=str(raw.get("cover_url") or "").strip(),
        author_name=str(
            raw.get("display_name") or raw.get("nickname") or ""
        ).strip()[:128],
        author_profile_url=str(raw.get("profile_url") or "").strip(),
        published_at=_timestamp(raw.get("create_time") or raw.get("time")),
        metrics=metrics,
    )


def normalize_account_videos(
    platform: str, raw_items: list[dict[str, Any]], limit: int = 10
) -> list[NormalizedCompetitorVideo]:
    videos: list[NormalizedCompetitorVideo] = []
    seen: set[str] = set()
    for raw in raw_items:
        normalized = normalize_video(platform, raw)
        identity = normalized.platform_content_id or normalized.content_url
        if not identity or identity in seen:
            continue
        seen.add(identity)
        videos.append(
            NormalizedCompetitorVideo(
                platform_content_id=normalized.platform_content_id,
                title=normalized.title,
                description=normalized.description,
                content_url=normalized.content_url,
                cover_url=normalized.cover_url,
                published_at=normalized.published_at,
                metrics=normalized.metrics,
            )
        )
        if len(videos) >= limit:
            break
    return videos


def serialize_account_video(video: NormalizedCompetitorVideo) -> dict[str, Any]:
    return {
        "platformContentId": video.platform_content_id,
        "title": video.title,
        "description": video.description,
        "contentUrl": video.content_url,
        "coverUrl": video.cover_url,
        "publishedAt": video.published_at.isoformat() if video.published_at else None,
        "metrics": dict(video.metrics),
    }


def recent_account_videos(
    videos: list[NormalizedCompetitorVideo], since: datetime
) -> list[NormalizedCompetitorVideo]:
    cutoff = since.astimezone(UTC) if since.tzinfo else since.replace(tzinfo=UTC)
    return [
        video
        for video in videos
        if video.published_at is not None
        and (
            video.published_at.astimezone(UTC)
            if video.published_at.tzinfo
            else video.published_at.replace(tzinfo=UTC)
        )
        >= cutoff
    ]
