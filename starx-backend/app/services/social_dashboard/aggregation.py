"""社媒账号与作品快照到数据看板视图的纯计算。"""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Iterable

from app.schemas.dashboards import (
    DashboardContentStructureSchema,
    DashboardInsightSchema,
    DashboardMetricSchema,
    DashboardTopContentSchema,
    SocialDashboardSchema,
)
from app.services.tikhub_service import TikHubAccount, TikHubContent


def _published_at(value: str) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        numeric = int(float(text))
        if numeric > 10_000_000_000:
            numeric //= 1000
        return datetime.fromtimestamp(numeric, tz=UTC)
    except (TypeError, ValueError, OverflowError):
        pass
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    except ValueError:
        return None


def _content_type(content: TikHubContent) -> str:
    value = str(content.contentType or "").lower()
    if value in {"video", "视频"}:
        return "视频"
    if value in {"image", "images", "normal", "图文"}:
        return "图文"
    return "其他"


def _interactions(content: TikHubContent) -> int:
    return max(
        content.likeCount
        + content.commentCount
        + content.shareCount
        + content.collectCount,
        0,
    )


def build_social_dashboard(
    *,
    platform_name: str,
    platform_account: str,
    account: TikHubAccount,
    contents: Iterable[TikHubContent],
    days: int,
    previous_followers: int | None,
    now: datetime | None = None,
    notices: list[str] | None = None,
) -> SocialDashboardSchema:
    current_time = now or datetime.now(UTC)
    cutoff = current_time - timedelta(days=days)
    recent = [
        content
        for content in contents
        if (published := _published_at(content.publishedAt)) is None or published >= cutoff
    ]
    total_likes = sum(item.likeCount for item in recent)
    total_comments = sum(item.commentCount for item in recent)
    total_favorites = sum(item.collectCount for item in recent)
    total_shares = sum(item.shareCount for item in recent)
    follower_growth = (
        account.followers - previous_followers
        if previous_followers is not None
        else None
    )
    follower_note = (
        f"近 {days} 天净增 {follower_growth:+d}"
        if follower_growth is not None
        else "已记录当前粉丝数，完成周期快照后展示真实涨粉"
    )
    type_counts: dict[str, int] = defaultdict(int)
    for item in recent:
        type_counts[_content_type(item)] += 1
    denominator = max(len(recent), 1)
    structure = [
        DashboardContentStructureSchema(
            label=label,
            count=count,
            percentage=round(count / denominator * 100, 1),
        )
        for label, count in sorted(
            type_counts.items(), key=lambda pair: pair[1], reverse=True
        )
    ]

    ranked = sorted(
        recent,
        key=lambda item: (_interactions(item), item.likeCount, item.collectCount),
        reverse=True,
    )[:10]
    top_contents = [
        DashboardTopContentSchema(
            rank=index,
            contentId=item.contentId,
            title=item.title or item.description or "未命名内容",
            contentType=_content_type(item),
            contentUrl=item.contentUrl,
            coverUrl=item.coverUrl,
            likes=item.likeCount,
            comments=item.commentCount,
            favorites=item.collectCount,
            shares=item.shareCount,
        )
        for index, item in enumerate(ranked, start=1)
    ]

    insights: list[DashboardInsightSchema] = []
    if ranked:
        best = ranked[0]
        insights.append(
            DashboardInsightSchema(
                title=f"当前表现最佳：{best.title or best.description or '未命名内容'}",
                description=f"近 {days} 天公开作品中，按点赞、评论、收藏和分享合计排序最高。",
            )
        )
    if structure:
        insights.append(
            DashboardInsightSchema(
                title=f"{structure[0].label}是主要内容形式",
                description=f"近 {days} 天发布内容占比 {structure[0].percentage:g}%。",
            )
        )
    if follower_growth is None:
        insights.append(
            DashboardInsightSchema(
                title="粉丝趋势正在积累",
                description="完成首日快照后，后续可计算所选周期的真实粉丝净增。",
            )
        )

    return SocialDashboardSchema(
        status="ready",
        platform=platform_name,
        platformAccount=platform_account,
        displayName=account.name,
        days=days,
        updatedAt=current_time.isoformat(),
        metrics=[
            DashboardMetricSchema(
                key="likes",
                label="点赞数",
                value=total_likes,
                note=f"近 {days} 天公开作品当前累计值",
            ),
            DashboardMetricSchema(
                key="comments",
                label="评论数",
                value=total_comments,
            ),
            DashboardMetricSchema(
                key="favorites",
                label="收藏数",
                value=total_favorites,
            ),
            DashboardMetricSchema(
                key="shares",
                label="分享数",
                value=total_shares,
            ),
            DashboardMetricSchema(
                key="followers",
                label="粉丝数",
                value=account.followers if account.followers > 0 else None,
                change=follower_growth,
                available=account.followers > 0,
                note=follower_note,
            ),
        ],
        trend=[],
        contentStructure=structure,
        topContents=top_contents,
        insights=insights,
        notices=list(notices or []),
    )
