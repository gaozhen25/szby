"""将完整账号报告证据投影为 AI 可见的字段白名单。"""

from __future__ import annotations

from typing import Any

from .models import CommentEvidence, ContentEvidence, CreatorEvidence, ReportEvidence


def _content(item: ContentEvidence) -> dict[str, Any]:
    return {
        "platform": item.platform,
        "content_id": item.content_id,
        "title": item.title,
        "summary": item.summary,
        "creator_hash": item.creator_hash,
        "creator_name": item.creator_name,
        "public_url": item.public_url,
        "cover_url": item.cover_url,
        "published_at": item.published_at,
        "liked_count": item.liked_count,
        "collected_count": item.collected_count,
        "comment_count": item.comment_count,
        "share_count": item.share_count,
        "view_count": item.view_count,
        "source_keyword": item.source_keyword,
        "engagement_score": item.engagement_score,
        "hot_score": item.hot_score,
        "source_operation": item.source_operation,
        "source_sort": item.source_sort,
        "evidence_completeness": item.evidence_completeness,
        "content_type": item.content_type,
    }


def _creator(item: CreatorEvidence) -> dict[str, Any]:
    return {
        "platform": item.platform,
        "creator_hash": item.creator_hash,
        "name": item.name,
        "fans_count": item.fans_count,
        "works_count": item.works_count,
        "interaction_count": item.interaction_count,
        "hit_content_count": item.hit_content_count,
        "representative_contents": list(item.representative_contents),
        "matched_queries": list(item.matched_queries),
        "evidence_completeness": item.evidence_completeness,
        "similarity_score": item.similarity_score,
    }


def _comment(item: CommentEvidence) -> dict[str, Any]:
    return {
        "platform": item.platform,
        "content_id": item.content_id,
        "text": item.text,
        "liked_count": item.liked_count,
    }


def build_ai_evidence(evidence: ReportEvidence) -> dict[str, Any]:
    """保留分析字段和公开笔记链接，移除真实昵称与博主主页链接。"""

    return {
        "currentAccountEvidence": {
            "profiles": [_creator(item) for item in evidence.current_account.profiles],
            "contents": [_content(item) for item in evidence.current_account.contents],
            "comments": [_comment(item) for item in evidence.current_account.comments],
        },
        "industryEvidence": {
            "hotContents": [_content(item) for item in evidence.industry.hot_contents],
            "similarAccounts": [
                _creator(item) for item in evidence.industry.similar_accounts
            ],
            "topBloggers": [_creator(item) for item in evidence.industry.top_bloggers],
            "comments": [_comment(item) for item in evidence.industry.comments],
        },
        "ownerHashes": list(evidence.owner_hashes),
    }
