"""相似账号与爆款参考的确定性选择和 AI 失败降级。"""

from __future__ import annotations

import re
from typing import Any

from ..domain.models import HotContent, ReportEvidence, SimilarAccount
from .hot_contents import select_balanced_hot_contents

_PLATFORM_HANDLE_LABEL_RE = re.compile(
    r"^(?:小红书号|红书号|抖音号|快手号|ID|id|账号)\s*[:：]\s*\S+$",
    re.IGNORECASE,
)
_KEYWORD_MENTION_RE = re.compile(
    r"(检索|搜索)?关键词|检索词|搜索词|搜词|source_keyword|matched_queries?",
    re.IGNORECASE,
)
_HASHTAG_RE = re.compile(r"[#＃]\s*")


def scrub_reason_text(text: str, *, fallback: str) -> str:
    """去掉「关键词」一类字眼，避免理由读起来像爬虫日志。"""

    cleaned = " ".join(str(text or "").split()).strip()
    cleaned = _KEYWORD_MENTION_RE.sub("", cleaned)
    cleaned = re.sub(r"[，,、\s]{2,}", "，", cleaned).strip("，,、;； ")
    if len(cleaned) < 8:
        cleaned = " ".join(str(fallback or "").split()).strip()
    return cleaned[:500]


def _pick_template(seed: str, templates: list[str]) -> str:
    if not templates:
        return ""
    digest = sum(ord(char) for char in str(seed or "")) or 0
    return templates[digest % len(templates)]


def _clip_title(value: Any, *, limit: int = 36) -> str:
    text = re.sub(r"\s+", " ", str(value or "").strip())
    if len(text) <= limit:
        return text
    return f"{text[: limit - 1]}…"


def _account_positioning(account_context: dict[str, Any] | None) -> str:
    account = dict((account_context or {}).get("account") or {})
    parts = [
        str(account.get("productService") or "").strip(),
        str(account.get("industry") or "").strip(),
        str(account.get("description") or "").strip(),
        str(account.get("purpose") or "").strip(),
    ]
    parts = [part for part in parts if part]
    if not parts:
        return "当前账号定位"
    # 取前两段拼成「健身/减脂」风格定位短语
    merged = "/".join(_clip_title(part, limit=12) for part in parts[:2])
    return merged or "当前账号定位"


def _theme_from_titles(titles: list[str], *, limit: int = 14) -> str:
    """从代表作品标题里抽短主题：优先话题标签，否则截取标题主干。"""

    tags: list[str] = []
    chunks: list[str] = []
    for title in titles:
        raw = str(title or "").strip()
        if not raw:
            continue
        found = [
            re.sub(r"\s+", "", tag)
            for tag in re.findall(r"[#＃]\s*([^\s#＃|｜]+)", raw)
            if str(tag).strip()
        ]
        for tag in found:
            if tag and tag not in tags:
                tags.append(tag)
        text = _HASHTAG_RE.sub("", raw)
        text = re.sub(r"\s+", " ", text).strip(" -|｜")
        # 去掉「作者名 - 」前缀噪音
        text = re.sub(r"^[\w\u4e00-\u9fff]{1,12}\s*[-—–|｜]\s*", "", text)
        if text:
            chunks.append(_clip_title(text, limit=limit))
        if len(tags) >= 2 or len(chunks) >= 2:
            break
    if tags:
        return "、".join(tags[:3])
    return "、".join(chunks[:2])


def similar_selection_reason(
    *,
    name: str,
    themes: list[str],
    creator_hash: str,
    account_context: dict[str, Any] | None = None,
) -> str:
    """对齐截图风格：赛道 + 内容核心 + 与账号定位一致性。"""

    positioning = _account_positioning(account_context)
    theme = _theme_from_titles(themes) or "同赛道内容"
    display = name or "该账号"
    templates = [
        f"同属相关赛道，内容核心是{theme}，与「{positioning}」定位高度一致。",
        f"{display}内容核心是{theme}，与「{positioning}」定位高度一致，可作对标样本。",
        f"内容聚焦{theme}，人设与转化方式贴近「{positioning}」，适合借鉴其代表作品。",
        f"与「{positioning}」同细分：代表内容围绕{theme}，选题切口和更新节奏可直接参考。",
        f"垂直重合点在{theme}，和「{positioning}」目标用户接近，适合观察其内容结构。",
    ]
    return scrub_reason_text(
        _pick_template(creator_hash or name or theme, templates),
        fallback=f"与「{positioning}」同属细分赛道，可作对标参考。",
    )


def hot_selection_reason(
    source: Any,
    *,
    account_context: dict[str, Any] | None = None,
) -> str:
    """对齐截图风格：标题/摘要主题 + 与账号定位一致性（可附带热度）。"""

    title = str(getattr(source, "title", "") or "").strip()
    summary = str(getattr(source, "summary", "") or "").strip()
    title_clip = _clip_title(title or summary, limit=24)
    type_label = "视频" if getattr(source, "content_type", "") == "video" else "图文"
    liked = max(int(getattr(source, "liked_count", 0) or 0), 0)
    content_id = str(getattr(source, "content_id", "") or "")
    positioning = _account_positioning(account_context)
    theme = _clip_title(title or summary or type_label, limit=28) or type_label

    if title_clip:
        templates = [
            f"标题与摘要明确围绕「{theme}」，与「{positioning}」高度一致。",
            f"标题指向「{theme}」，内容主题贴近「{positioning}」，适合作为爆款结构参考。",
            f"「{theme}」直接对应账号「{positioning}」方向，{type_label}完整且可拆解。",
            f"该{type_label}围绕「{theme}」展开，与「{positioning}」定位强相关。",
        ]
        if liked >= 5000:
            templates.append(
                f"标题指向「{theme}」，与「{positioning}」强相关且热度积累高。"
            )
        if summary and summary != title:
            summary_clip = _clip_title(summary, limit=20)
            templates.append(
                f"标题与摘要覆盖「{theme} / {summary_clip}」，与「{positioning}」定位一致。"
            )
    else:
        templates = [
            f"用于补充{type_label}形态参考，互动表现支撑其作为公开样本。",
            f"同赛道高互动{type_label}，可对照「{positioning}」观察表达方式。",
        ]
    return scrub_reason_text(
        _pick_template(content_id or title_clip, templates),
        fallback=f"与「{positioning}」相关的高互动{type_label}样本。",
    )


def deterministic_similar_accounts(
    evidence: ReportEvidence,
    *,
    limit: int = 8,
    account_context: dict[str, Any] | None = None,
) -> list[SimilarAccount]:
    items: list[SimilarAccount] = []
    for source in evidence.industry.similar_accounts[:limit]:
        themes = [
            str(item)[:120]
            for item in source.representative_contents[:3]
            if str(item).strip() and not _PLATFORM_HANDLE_LABEL_RE.match(str(item).strip())
        ]
        name = str(source.display_name or source.name or "公开行业账号").strip() or "公开行业账号"
        if len(name) > 100:
            name = name[:100]
        reason = similar_selection_reason(
            name=name,
            themes=themes,
            creator_hash=source.creator_hash,
            account_context=account_context,
        )
        items.append(
            SimilarAccount(
                platform=source.platform,
                creatorHash=source.creator_hash,
                name=name,
                profileUrl=source.profile_url,
                avatarUrl=source.avatar_url,
                similarityReason=reason,
                metrics={
                    "fansCount": source.fans_count,
                    "worksCount": source.works_count,
                    "likedCount": source.liked_count,
                    "interactionCount": source.interaction_count,
                    "similarityScore": source.similarity_score,
                    "evidenceCompleteness": source.evidence_completeness,
                },
                representativeContents=themes,
            )
        )
    return items


def deterministic_hot_contents(
    evidence: ReportEvidence,
    *,
    limit: int = 8,
    platforms: list[str] | None = None,
    exclude_keys: set[tuple[str, str]] | frozenset[tuple[str, str]] | None = None,
    account_context: dict[str, Any] | None = None,
) -> list[HotContent]:
    items: list[HotContent] = []
    for source in select_balanced_hot_contents(
        evidence.industry.hot_contents,
        limit=limit,
        platforms=platforms,
        exclude_keys=exclude_keys,
        account_context=account_context,
    ):
        items.append(
            HotContent(
                platform=source.platform,
                contentId=source.content_id,
                title=source.title or "未命名公开内容",
                selectionReason=hot_selection_reason(
                    source, account_context=account_context
                ),
                publicUrl=source.public_url,
                coverUrl=source.cover_url,
                contentType=source.content_type,
                tags=[],
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
