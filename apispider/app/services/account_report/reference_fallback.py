"""相似账号与爆款参考的确定性选择和 AI 失败降级。"""

from __future__ import annotations

from .hot_content_selection import select_balanced_hot_contents
from .models import HotContent, ReportEvidence, SimilarAccount


def deterministic_similar_accounts(
    evidence: ReportEvidence, *, limit: int = 8
) -> list[SimilarAccount]:
    items: list[SimilarAccount] = []
    for source in evidence.industry.similar_accounts[:limit]:
        themes = list(source.representative_contents[:2])
        matched = "、".join(source.matched_queries[:2])
        basis = matched or ("、".join(themes) if themes else "行业内容方向")
        items.append(
            SimilarAccount(
                platform=source.platform,
                creatorHash=source.creator_hash,
                name=source.display_name or source.name or "公开行业账号",
                profileUrl=source.profile_url,
                avatarUrl=source.avatar_url,
                similarityReason=(
                    f"该账号在“{basis}”方向与目标定位接近，"
                    "可参考其近期内容结构与账号运营节奏。"
                ),
                metrics={
                    "fansCount": source.fans_count,
                    "worksCount": source.works_count,
                    "interactionCount": source.interaction_count,
                    "similarityScore": source.similarity_score,
                    "evidenceCompleteness": source.evidence_completeness,
                },
                representativeContents=themes,
            )
        )
    return items


def deterministic_hot_contents(
    evidence: ReportEvidence, *, limit: int = 8
) -> list[HotContent]:
    items: list[HotContent] = []
    for source in select_balanced_hot_contents(
        evidence.industry.hot_contents, limit=limit
    ):
        type_label = "视频" if source.content_type == "video" else "图文"
        items.append(
            HotContent(
                platform=source.platform,
                contentId=source.content_id,
                title=source.title or "未命名公开内容",
                selectionReason=(
                    f"该内容在同平台{type_label}候选中热度和相关性较高，"
                    "适合参考其选题切口、内容结构与互动设计。"
                ),
                publicUrl=source.public_url,
                contentType=source.content_type,
                metrics={
                    "likedCount": source.liked_count,
                    "collectedCount": source.collected_count,
                    "commentCount": source.comment_count,
                    "shareCount": source.share_count,
                    "viewCount": source.view_count,
                    "engagementScore": source.engagement_score,
                    "hotScore": source.hot_score,
                },
            )
        )
    return items
