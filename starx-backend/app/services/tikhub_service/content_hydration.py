"""账号作品详情补全与发布时间筛选。"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from app.core.logging import get_logger
from app.services.tikhub_service.models import (
    TikHubContent,
    TikHubContentDetailRequest,
    TikHubPlatform,
)

logger = get_logger(__name__)


def parse_published_at(value: str) -> datetime | None:
    """兼容 TikHub 返回的秒、毫秒时间戳和 ISO 时间。"""

    text = str(value or "").strip()
    if not text:
        return None
    try:
        timestamp = float(text)
        if timestamp > 10_000_000_000:
            timestamp /= 1000
        return datetime.fromtimestamp(timestamp, tz=UTC)
    except (OverflowError, OSError, ValueError):
        pass
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def is_published_since(content: TikHubContent, since: datetime) -> bool:
    published_at = parse_published_at(content.publishedAt)
    return published_at is not None and published_at >= since


def page_reaches_cutoff(contents: list[TikHubContent], since: datetime) -> bool:
    """主页作品按发布时间倒序返回；遇到窗口外作品后即可停止翻页。"""

    published = [parse_published_at(item.publishedAt) for item in contents]
    return any(value is not None and value < since for value in published)


def _merge_detail(discovered: TikHubContent, detail: TikHubContent) -> TikHubContent:
    """详情值优先，同时保留列表接口独有的身份及发布时间字段。"""

    updates = {}
    for field_name in (
        "contentId",
        "title",
        "description",
        "contentUrl",
        "coverUrl",
        "authorId",
        "authorName",
        "authorUrl",
        "publishedAt",
        "contentType",
    ):
        if not str(getattr(detail, field_name) or "").strip():
            updates[field_name] = getattr(discovered, field_name)
    for field_name in (
        "likeCount",
        "commentCount",
        "shareCount",
        "collectCount",
        "readCount",
    ):
        updates[field_name] = max(
            int(getattr(discovered, field_name) or 0),
            int(getattr(detail, field_name) or 0),
        )
    if not detail.raw:
        updates["raw"] = discovered.raw
    return detail.model_copy(update=updates)


async def hydrate_recent_content_details(
    provider,
    platform: TikHubPlatform,
    contents: list[TikHubContent],
    since: datetime,
    *,
    concurrency: int = 5,
) -> list[TikHubContent]:
    """只请求时间窗口内的作品详情；单条失败时保留主页列表结果。"""

    semaphore = asyncio.Semaphore(max(concurrency, 1))

    async def hydrate(content: TikHubContent) -> TikHubContent:
        if not is_published_since(content, since) or not content.contentId:
            return content
        try:
            async with semaphore:
                detail = await provider.get_content(
                    TikHubContentDetailRequest(
                        platform=platform,
                        workId=content.contentId,
                        contentType=content.contentType,
                    )
                )
            return _merge_detail(content, detail)
        except Exception as exc:  # 单条作品不可用不应导致整个账号刷新失败。
            logger.warning(
                "tikhub content detail hydration failed platform=%s content_id=%s cause_type=%s",
                platform.value,
                content.contentId,
                type(exc).__name__,
            )
            return content

    return list(await asyncio.gather(*(hydrate(content) for content in contents)))
