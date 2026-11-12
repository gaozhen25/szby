"""Topic recommendation workflow."""

from __future__ import annotations

import json
import re
from typing import Any

from app.services.ai_service import AI_SERVICE_FORBIDDEN_SENTINEL

from .base import BaseWorkflow, WorkflowRegister

TOPIC_RECOMMENDATION_COUNT = 8
MIN_VALID_TOPIC_COUNT = TOPIC_RECOMMENDATION_COUNT
TOPIC_RECOMMENDATION_MAX_ATTEMPTS = 2
TOPIC_RECOMMENDATION_RETRY_CANDIDATE_COUNT = 10
TOPIC_TITLE_MAX_LENGTH = 255
TOPIC_CATEGORY_MAX_LENGTH = 64
KOUBO_CATEGORY = "口播"
TOPIC_PATTERNS = (
    "痛点避坑",
    "清单干货",
    "测评对比",
    "场景方案",
    "真实体验",
)
TOPIC_PATTERN_ALIASES = {
    "痛点避坑": "痛点避坑",
    "避坑": "痛点避坑",
    "痛点": "痛点避坑",
    "清单干货": "清单干货",
    "清单": "清单干货",
    "干货": "清单干货",
    "测评对比": "测评对比",
    "测评": "测评对比",
    "对比": "测评对比",
    "场景方案": "场景方案",
    "场景": "场景方案",
    "方案": "场景方案",
    "真实体验": "真实体验",
    "体验": "真实体验",
    "实测": "真实体验",
}
_DOUYIN_ALIASES = frozenset({"抖音", "dy", "douyin"})
REFERENCE_METRIC_FIELDS = (
    "likedCount",
    "collectedCount",
    "commentCount",
    "shareCount",
    "viewCount",
    "engagementScore",
    "hotScore",
)


def _is_douyin_platform(value: Any) -> bool:
    return str(value or "").strip().lower() in _DOUYIN_ALIASES


def _account_has_douyin(platforms: list[str]) -> bool:
    return any(_is_douyin_platform(item) for item in platforms)


def _account_is_douyin_only(platforms: list[str]) -> bool:
    normalized = [str(item).strip() for item in platforms if str(item).strip()]
    return bool(normalized) and all(_is_douyin_platform(item) for item in normalized)


def build_topic_recommendation_system_prompt() -> str:
    return (
        "你是社交媒体账号运营选题策划助手。"
        "只输出 JSON，不输出 markdown。"
        "选题必须贴合账号定位、转化目标、账号平台和知识库。"
        "选题标题必须与爆款参考明显不同：禁止复刻、同义改写或轻微改写爆款标题。"
        "选题绑定的原文必须来自选题参考爆款池，禁止使用报告展示爆款内容中的同一条笔记。"
        "换一批时必须与已有选题标题明显不同，禁止同义改写；也禁止复用上一批已绑定的原文。"
        "换一批会按关键词重新搜索原文池，每条选题必须绑定新搜到的、互不相同的 referenceContentId。"
        "每条选题必须有推荐理由、适合平台、选题模板标签 topicPattern，并且在有爆款参考池时绑定一条原文参考（referenceContentId）。"
        "topicPattern 只能是：痛点避坑、清单干货、测评对比、场景方案、真实体验；8 条尽量分散覆盖不同模板。"
        "图文选题只能绑定图文爆款；视频选题绑定视频爆款；标题切口要换新，但必须保留原文链接供前端展示。"
    )


def build_topic_recommendation_user_prompt(context: dict[str, Any], count: int = TOPIC_RECOMMENDATION_COUNT) -> str:
    account = context.get("account") or {}
    account_platforms = [str(item).strip() for item in account.get("platforms") or [] if str(item).strip()]
    if not account_platforms and str(account.get("platform") or "").strip():
        account_platforms = [str(account.get("platform") or "").strip()]
    if not account_platforms:
        account_platforms = ["小红书"]
    prefer_douyin_koubo = _account_has_douyin(account_platforms)
    douyin_only = _account_is_douyin_only(account_platforms)
    account_report = context.get("accountReport")
    if account_report:
        topic_reference_pool = list(
            account_report.get("topicReferencePool")
            or []
        )
        has_image_references = _has_valid_reference(topic_reference_pool, content_types={"image"})
        has_video_references = _has_valid_reference(topic_reference_pool, content_types={"video"})
        has_any_references = has_image_references or has_video_references
        report_lines = [
            "已生成账号报告证据:",
            "目标用户画像:",
            json.dumps(account_report.get("targetUserProfile") or {}, ensure_ascii=False),
            "报告展示爆款内容（仅作方向参考；禁止复刻其标题，也禁止绑定这些 contentId）:",
            json.dumps(account_report.get("hotContents") or [], ensure_ascii=False),
            "选题参考爆款池（每条选题必须绑定其中一条作为原文；与上方展示爆款互斥）:",
            json.dumps(topic_reference_pool, ensure_ascii=False),
            "相似账号:",
            json.dumps(account_report.get("similarAccounts") or [], ensure_ascii=False),
            "合规限制:",
            json.dumps(account_report.get("complianceRules") or [], ensure_ascii=False),
            "报告来源摘要:",
            json.dumps(account_report.get("sourceMeta") or {}, ensure_ascii=False),
        ]
    else:
        has_image_references = False
        has_video_references = False
        has_any_references = False
        report_lines = ["已生成账号报告证据:", "无已生成账号报告。"]
    if prefer_douyin_koubo and has_video_references and (douyin_only or not has_image_references):
        content_type_example = "video"
        category_example = KOUBO_CATEGORY
    else:
        content_type_example = "image 或 video"
        category_example = "内容分类"
    existing_reference_ids = [
        str(item).strip()
        for item in list(context.get("existingReferenceContentIds") or [])
        if str(item or "").strip()
    ]
    lines = [
        "请基于以下账号信息生成新一批推荐选题。",
        "",
        "账号档案:",
        f"- 账号名称: {account.get('name') or ''}",
        f"- 账号类型: {account.get('type') or ''}",
        f"- 账号描述: {account.get('description') or ''}",
        f"- 运营目的: {account.get('purpose') or ''}",
        f"- 行业: {account.get('industry') or ''}",
        f"- 产品/服务: {account.get('productService') or ''}",
        f"- 目标城市: {account.get('targetCity') or ''}",
        f"- 目标人群: {account.get('targetAudience') or ''}",
        f"- 转化目标: {account.get('conversionGoal') or ''}",
        f"- 已选平台: {'、'.join(account.get('platforms') or [])}",
        "",
        "知识库:",
        str(context.get("knowledgeContext") or "无"),
        "",
        "已有选题标题，换一批必须避开（禁止相同或同义改写）:",
        "、".join(context.get("existingTopicTitles") or []) or "无",
        "",
        "上一批已绑定原文 contentId（换一批禁止复用）:",
        "、".join(existing_reference_ids) or "无",
        "",
        *report_lines,
        "",
        "输出要求:",
        "- 如有账号报告，可参考选题参考爆款池提炼方向，但选题标题/切口必须与爆款明显不同。",
        "- 选题原文只能选自选题参考爆款池，禁止使用报告展示爆款内容中的同一条笔记。",
        "- 换一批时原文池已按关键词重新搜索（小红书/抖音内容搜索）；必须绑定新池中互不相同的 contentId。",
        (
            "- 账号含抖音时：尽量全部返回适合口播的视频选题（contentType=video）；"
            "若绑定的原文 tags 含「口播」，category 必须为「口播」。"
            "只有在没有可用视频原文时才允许图文。"
            if prefer_douyin_koubo
            else "- 按账号平台选择图文或视频选题。"
        ),
        "- 禁止沿用参考标题的句式、钩子做轻微改写；禁止与报告展示爆款标题近似。",
        (
            "- 当前有爆款参考池：每条选题都必须填写 referenceContentId，且必须来自选题参考爆款池；"
            "每条选题的 referenceContentId 必须互不相同，禁止多条选题共用同一条原文；"
            "这是前端“原文”展示所必需，不能省略。"
            if has_any_references
            else "- 当前没有爆款参考池，referenceContentId 可为空。"
        ),
        "- 图文选题只能绑定 contentType=image 的 contentId；视频选题只能绑定 contentType=video 的 contentId。",
        "- reason 需说明借鉴了原文的哪类转化结构，以及具体换了什么切口；引用原文时用其 title，禁止写 contentId。",
        "- 必须遵守合规限制，避免报告标记的风险表达和方向。",
        "- 只允许输出一个 JSON 对象，不要输出解释、markdown、代码块或前后缀文本。",
        "- JSON 第一字符必须是 {，最后字符必须是 }。",
        f"- topics 数组必须包含 {count} 条选题。",
        (
            "- 当前账号为纯抖音且存在视频原文：禁止生成 contentType=image，必须全部为口播视频。"
            if prefer_douyin_koubo and douyin_only and has_video_references
            else (
                "- 当前存在有效图文爆款参考，可生成 contentType=image，且必须带准确原文链接。"
                if has_image_references and not (prefer_douyin_koubo and has_video_references)
                else (
                    "- 当前存在有效图文爆款参考，但抖音账号应优先口播视频；图文仅作少量补充。"
                    if has_image_references
                    else "- 当前没有有效图文爆款参考，禁止生成 contentType=image。"
                )
            )
        ),
        (
            "- 当前存在有效视频爆款参考，视频选题必须绑定视频原文；"
            "原文 tags 含「口播」时 category 填「口播」。"
            if has_video_references and prefer_douyin_koubo
            else (
                "- 当前存在有效视频爆款参考，视频选题必须绑定视频原文。"
                if has_video_references
                else "- 当前没有有效视频爆款参考，视频选题 referenceContentId 可为空。"
            )
        ),
        "- platforms 只能从账号已选平台中选择。",
        "- 每条选题必须填写 topicPattern，且只能是："
        + "、".join(TOPIC_PATTERNS)
        + "；标题切口要新，但归入上述模板之一。",
        "- 8 条选题的 topicPattern 尽量分散，不要全部挤在同一类。",
        "JSON 示例:",
        json.dumps(
            {
                "topics": [
                    {
                        "title": "30 字以内中文标题",
                        "reason": "60 字以内推荐理由",
                        "platforms": account_platforms[:1],
                        "category": category_example,
                        "contentType": content_type_example,
                        "topicPattern": "痛点避坑",
                        "referenceContentId": "必填：选题参考爆款池中的 contentId",
                    }
                ]
            },
            ensure_ascii=False,
        ),
    ]
    return "\n".join(lines)


def build_topic_recommendation_retry_prompt(
    context: dict[str, Any],
    *,
    validation_error: str,
    valid_topic_count: int,
    fallbacks: list[str],
) -> str:
    """为校验失败生成一次完整重试提示，不复用可能有缺陷的原始输出。"""

    base_prompt = build_topic_recommendation_user_prompt(
        context,
        count=TOPIC_RECOMMENDATION_RETRY_CANDIDATE_COUNT,
    )
    diagnostics = fallbacks[:12]
    return "\n".join(
        [
            base_prompt,
            "",
            "纠正重试要求:",
            f"- 上一次结果未通过校验：{validation_error}。",
            f"- 上一次规范化后只有 {valid_topic_count} 条有效选题。",
            f"- 本次请完整重写 {TOPIC_RECOMMENDATION_RETRY_CANDIDATE_COUNT} 条候选，不要只补差额。",
            f"- 系统最终会选取前 {TOPIC_RECOMMENDATION_COUNT} 条有效选题，请确保至少有 "
            f"{MIN_VALID_TOPIC_COUNT} 条能独立通过全部约束。",
            "- 图文选题的 referenceContentId 必须逐字复制选题参考爆款池中的有效 contentId；"
            "无法确认引用时请改为 video，不要编造 ID。",
            "- 标题不得为空或重复，topics 中每一项都必须是完整 JSON 对象。",
            "- 上一次规范化诊断（仅用于纠正，不要输出这些文字）: "
            + json.dumps(diagnostics, ensure_ascii=False),
        ]
    )


def _normalize_topic_pattern(raw: Any, *, fallback_index: int = 0) -> str:
    text = str(raw or "").strip()
    if text in TOPIC_PATTERNS:
        return text
    mapped = TOPIC_PATTERN_ALIASES.get(text)
    if mapped:
        return mapped
    for pattern in TOPIC_PATTERNS:
        if pattern in text or text in pattern:
            return pattern
    return TOPIC_PATTERNS[fallback_index % len(TOPIC_PATTERNS)]


def normalize_recommended_topics(
    raw_topics: Any,
    allowed_platforms: list[str],
    canonical_platform: str,
    reference_contents: list[dict[str, Any]] | None = None,
    *,
    convert_invalid_image_reference_to_video: bool = False,
    avoid_titles: list[str] | None = None,
    hot_titles: list[str] | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    allowed = [str(item).strip() for item in allowed_platforms if str(item).strip()]
    canonical = str(canonical_platform or "").strip()
    fallback_platform = canonical if canonical and canonical in allowed else (allowed[0] if allowed else "小红书")
    fallbacks: list[str] = []
    normalized: list[dict[str, Any]] = []
    seen_titles: set[str] = set()
    blocked_titles = [
        str(item).strip()
        for item in list(avoid_titles or []) + list(hot_titles or [])
        if str(item or "").strip()
    ]
    reference_notes = [
        _reference_note(item)
        for item in (reference_contents or [])
        if _is_valid_image_reference(item)
    ]
    reference_by_id = {item["contentId"]: item for item in reference_notes}
    has_image_references = bool(reference_by_id)
    for item in raw_topics or []:
        if not isinstance(item, dict):
            fallbacks.append("skipped non-object topic")
            continue
        raw_title = str(item.get("title") or "").strip()
        title = raw_title[:TOPIC_TITLE_MAX_LENGTH]
        if not title or title in seen_titles:
            fallbacks.append("skipped empty or duplicate title")
            continue
        if any(_titles_too_similar(title, blocked) for blocked in blocked_titles):
            fallbacks.append(f"{title}: skipped similar to existing or hot title")
            continue
        if title != raw_title:
            fallbacks.append(f"{title}: title truncated to {TOPIC_TITLE_MAX_LENGTH} characters")
        seen_titles.add(title)
        raw_platforms = item.get("platforms") if isinstance(item.get("platforms"), list) else []
        platforms = [str(platform).strip() for platform in raw_platforms if str(platform).strip() in allowed]
        if not platforms:
            platforms = [fallback_platform]
            fallbacks.append(f"{title}: platform fallback")
        reason = str(item.get("reason") or "").strip()
        if not reason:
            reason = "贴合账号定位、目标人群和当前内容转化目标。"
            fallbacks.append(f"{title}: reason fallback")
        raw_category = str(item.get("category") or "").strip() or "内容种草"
        category = raw_category[:TOPIC_CATEGORY_MAX_LENGTH]
        if category != raw_category:
            fallbacks.append(f"{title}: category truncated to {TOPIC_CATEGORY_MAX_LENGTH} characters")
        content_type = (
            str(item.get("contentType") or item.get("type") or "").strip()
            or ("image" if has_image_references else "video")
        )
        if content_type not in {"image", "video"}:
            content_type = "image" if has_image_references else "video"
            fallbacks.append(f"{title}: contentType fallback")
        reference_note: dict[str, Any] = {}
        if content_type == "image":
            requested_reference_id = str(item.get("referenceContentId") or "").strip()
            reference_note = reference_by_id.get(requested_reference_id) or {}
            if not reference_note:
                if has_image_references:
                    if convert_invalid_image_reference_to_video:
                        content_type = "video"
                        fallbacks.append(
                            f"{title}: invalid image reference converted to video"
                        )
                    else:
                        fallbacks.append(f"{title}: skipped invalid image reference")
                        continue
                else:
                    content_type = "video"
                    fallbacks.append(
                        f"{title}: image topic converted to video without reference"
                    )
            else:
                reference_title = str(reference_note.get("title") or "").strip()
                if reference_title and _titles_too_similar(title, reference_title):
                    fallbacks.append(f"{title}: skipped too similar to referenced hot note")
                    continue
            reason = _replace_reference_id_with_title(reason, reference_note)
        normalized.append(
            {
                "title": title,
                "source": "AI推荐",
                "category": category,
                "contentType": content_type,
                "reason": reason,
                "platforms": platforms,
                "referenceNote": reference_note,
            }
        )
    return normalized, fallbacks


def _search_fill_title(note: dict[str, Any], *, index: int, variant: int = 0) -> str:
    keyword = str(note.get("sourceKeyword") or note.get("source_keyword") or "").strip()
    if len(keyword) < 2:
        keyword = "账号定位"
    content_id = str(note.get("contentId") or "").strip()
    tail = content_id[-4:] if len(content_id) >= 4 else str(index + 1)
    pattern = TOPIC_PATTERNS[index % len(TOPIC_PATTERNS)]
    if variant == 0:
        title = f"补{index + 1}｜{keyword}{pattern}"
    elif variant == 1:
        title = f"搜到的原文换切口{index + 1}｜{keyword}"
    else:
        title = f"补位选题{index + 1}·{tail}·{pattern}"
    return title[:TOPIC_TITLE_MAX_LENGTH]


def fill_topics_from_reference_pool(
    topics: list[dict[str, Any]],
    reference_contents: list[dict[str, Any]] | None,
    *,
    allowed_platforms: list[str],
    canonical_platform: str,
    avoid_titles: list[str] | None = None,
    hot_titles: list[str] | None = None,
    need: int = MIN_VALID_TOPIC_COUNT,
) -> tuple[list[dict[str, Any]], list[str]]:
    """AI 有效选题不足时，用普通搜索原文池补到 need 条，每条绑唯一原文。"""

    filled = list(topics or [])
    fallbacks: list[str] = []
    if len(filled) >= need:
        return filled, fallbacks

    allowed = [str(item).strip() for item in allowed_platforms if str(item).strip()]
    canonical = str(canonical_platform or "").strip()
    fallback_platform = canonical if canonical and canonical in allowed else (allowed[0] if allowed else "小红书")
    external_titles = [
        str(item).strip()
        for item in (
            list(avoid_titles or [])
            + list(hot_titles or [])
            + [str(topic.get("title") or "").strip() for topic in filled]
        )
        if str(item or "").strip()
    ]
    used_title_keys = {
        _normalize_title_key(str(topic.get("title") or ""))
        for topic in filled
        if str(topic.get("title") or "").strip()
    }
    used_ids = {
        str((topic.get("referenceNote") or {}).get("contentId") or "").strip()
        for topic in filled
        if str((topic.get("referenceNote") or {}).get("contentId") or "").strip()
    }

    for note in reference_contents or []:
        if len(filled) >= need:
            break
        if not is_valid_topic_reference(note):
            continue
        content_id = str(note.get("contentId") or "").strip()
        if not content_id or content_id in used_ids:
            continue
        reference_note = _reference_note(note)
        if not str(reference_note.get("publicUrl") or "").strip():
            continue
        note_title = str(reference_note.get("title") or "").strip()
        title = ""
        for variant in (0, 1, 2):
            candidate = _search_fill_title(note, index=len(filled), variant=variant)
            if not candidate:
                continue
            key = _normalize_title_key(candidate)
            if not key or key in used_title_keys:
                continue
            if any(_titles_too_similar(candidate, blocked) for blocked in external_titles):
                continue
            if note_title and _titles_too_similar(candidate, note_title):
                continue
            title = candidate
            break
        if not title:
            fallbacks.append(f"{content_id}: search fill title collided")
            continue
        content_type = str(note.get("contentType") or "image").strip()
        if content_type not in {"image", "video"}:
            content_type = "image"
        category = KOUBO_CATEGORY if content_type == "video" else "内容种草"
        ref_tags = [
            str(tag).strip()
            for tag in (reference_note.get("tags") or [])
            if str(tag or "").strip()
        ]
        if KOUBO_CATEGORY in ref_tags:
            category = KOUBO_CATEGORY
        filled.append(
            {
                "title": title,
                "source": "AI推荐",
                "category": category,
                "contentType": content_type,
                "topicPattern": TOPIC_PATTERNS[len(filled) % len(TOPIC_PATTERNS)],
                "reason": "参考普通搜索原文换切口，补齐本批选题数量。",
                "platforms": [fallback_platform],
                "referenceNote": reference_note,
            }
        )
        used_ids.add(content_id)
        used_title_keys.add(_normalize_title_key(title))
        fallbacks.append(f"{title}: filled from general search pool")

    return filled, fallbacks


def _normalize_title_key(title: str) -> str:
    text = str(title or "").strip().lower()
    text = re.sub(r"[\s\-_|｜、，。！？!?,.·•:：;；“”\"'（）()【】\[\]]+", "", text)
    return text


def _titles_too_similar(left: str, right: str) -> bool:
    a = _normalize_title_key(left)
    b = _normalize_title_key(right)
    if not a or not b:
        return False
    if a == b or a in b or b in a:
        return True
    if len(a) >= 8 and len(b) >= 8 and (a[:8] == b[:8] or a[-8:] == b[-8:]):
        return True
    if len(a) >= 6 and len(b) >= 6:
        left_grams = {a[i : i + 2] for i in range(len(a) - 1)}
        right_grams = {b[i : i + 2] for i in range(len(b) - 1)}
        if left_grams and right_grams:
            overlap = len(left_grams & right_grams) / max(len(left_grams), len(right_grams))
            if overlap >= 0.72:
                return True
    return False


def _reference_note(item: dict[str, Any]) -> dict[str, Any]:
    value = {
        "contentId": str(item.get("contentId") or "").strip(),
        "platform": str(item.get("platform") or "").strip(),
        "title": str(item.get("title") or "").strip(),
        "summary": str(item.get("summary") or "").strip(),
        "selectionReason": str(item.get("selectionReason") or "").strip(),
        "publicUrl": str(item.get("publicUrl") or "").strip(),
        "coverUrl": str(item.get("coverUrl") or "").strip(),
        "contentType": str(item.get("contentType") or "unknown").strip(),
        "tags": [
            str(tag).strip()
            for tag in (item.get("tags") or [])
            if str(tag or "").strip()
        ],
        "sourceKeyword": str(item.get("sourceKeyword") or "").strip(),
        "sourceSort": str(item.get("sourceSort") or "").strip(),
        "publishedAt": str(item.get("publishedAt") or "").strip(),
        "hotScore": item.get("hotScore") if isinstance(item.get("hotScore"), (int, float)) else 0,
        "metrics": _reference_metrics(item.get("metrics")),
    }
    return {
        key: field_value
        for key, field_value in value.items()
        if field_value not in ("", 0, {}, [])
    }


def _is_valid_image_reference(item: Any) -> bool:
    return (
        isinstance(item, dict)
        and str(item.get("contentId") or "").strip()
        and str(item.get("publicUrl") or "").strip()
        and str(item.get("contentType") or "").strip() == "image"
    )


def _reference_metrics(value: Any) -> dict[str, int | float]:
    if not isinstance(value, dict):
        return {}
    return {
        key: metric
        for key, metric in value.items()
        if key in REFERENCE_METRIC_FIELDS and isinstance(metric, (int, float)) and not isinstance(metric, bool)
    }


def _has_valid_image_reference(items: list[Any]) -> bool:
    return any(_is_valid_image_reference(item) for item in items)


def _replace_reference_id_with_title(reason: str, reference_note: dict[str, Any]) -> str:
    """将模型误写进用户文案的内容 ID 替换为可读的参考标题。"""
    content_id = str(reference_note.get("contentId") or "").strip()
    if not content_id or content_id not in reason:
        return reason

    reference_title = str(reference_note.get("title") or "").strip()
    readable_reference = f"爆款笔记《{reference_title}》" if reference_title else "参考爆款笔记"
    labeled_reference = re.compile(
        rf"(?:爆款|参考)?笔记\s*(?:id|编号)?\s*[:：#]?\s*{re.escape(content_id)}",
        re.IGNORECASE,
    )
    sanitized = labeled_reference.sub(lambda _: readable_reference, reason)
    fallback_replacement = f"《{reference_title}》" if reference_title else "该参考笔记"
    return sanitized.replace(content_id, fallback_replacement)


def parse_topic_recommendation_payload(raw: Any) -> dict[str, Any] | list[Any] | None:
    if isinstance(raw, (dict, list)):
        return raw

    text = str(raw or "").strip()
    if not text:
        return None

    fence = re.match(r"^```(?:json)?\s*\n(.*?)\n```\s*$", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        start_candidates = [idx for idx in (text.find("{"), text.find("[")) if idx >= 0]
        start = min(start_candidates) if start_candidates else -1
        end = max(text.rfind("}"), text.rfind("]"))
        if start < 0 or end <= start:
            return None
        try:
            parsed = json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            return None

    return parsed if isinstance(parsed, (dict, list)) else None


@WorkflowRegister.register
class TopicRecommendationWorkflow(BaseWorkflow):
    type = "topic_recommendation"

    async def _search_context(self, context: dict[str, Any]) -> dict[str, Any]:
        account = dict(context.get("account") or {})
        account_report = dict(context.get("accountReport") or {})
        source_meta = dict(account_report.get("sourceMeta") or {})
        keywords = [
            str(item).strip()
            for item in list(source_meta.get("keywords") or [])
            if str(item or "").strip()
        ]
        platforms = [
            str(item).strip()
            for item in list(account.get("platforms") or [])
            if str(item).strip()
        ]
        if not platforms and str(account.get("platform") or "").strip():
            platforms = [str(account.get("platform") or "").strip()]
        existing_titles = [
            str(item).strip()
            for item in list(context.get("existingTopicTitles") or [])
            if str(item or "").strip()
        ]
        existing_refs = {
            str(item).strip()
            for item in list(context.get("existingReferenceContentIds") or [])
            if str(item or "").strip()
        }
        hot_ids = {
            str(item.get("contentId") or item.get("content_id") or "").strip()
            for item in list(account_report.get("hotContents") or [])
            if isinstance(item, dict)
        }
        exclude_ids = {item for item in existing_refs | hot_ids if item}
        cookie_pool = (
            self.context.get("_cookie_pool_loader")()
            if callable(self.context.get("_cookie_pool_loader"))
            else self.context.get("_cookie_pool")
        )
        return {
            "keywords": keywords,
            "platforms": platforms,
            "exclude_ids": exclude_ids,
            "force_refresh": bool(existing_titles or existing_refs),
            "crawler": self.context.get("_crawler_service"),
            "cookie_pool": cookie_pool,
            "runtime_settings": self.context.get("_settings"),
        }

    async def _ensure_reference_pool(
        self,
        context: dict[str, Any],
    ) -> tuple[list[dict[str, Any]], int]:
        """原文池不足 8 条时用普通搜索补到 8；换一批先重搜再翻页。"""

        search = await self._search_context(context)
        account_report = dict(context.get("accountReport") or {})
        seed_pool = list(account_report.get("topicReferencePool") or [])
        if not search["keywords"] or not search["platforms"]:
            logger.info(
                "topic pool search skipped keywords=%s platforms=%s",
                len(search["keywords"]),
                search["platforms"],
            )
            return seed_pool, 1
        import sys

        # 单测未注入爬虫时不要打真实搜索；生产 crawler=None 会走 MediaCrawlerService
        if search["crawler"] is None and "pytest" in sys.modules:
            return seed_pool, 1

        self.store.update_progress(
            self.workflow_id,
            progress=20,
            current_stage="keyword_research",
        )
        pool, next_page = await ensure_topic_reference_pool(
            seed_pool=[],
            keywords=search["keywords"],
            platforms=search["platforms"],
            exclude_content_ids=search["exclude_ids"],
            crawler=search["crawler"],
            cookie_pool=search["cookie_pool"],
            runtime_settings=search["runtime_settings"],
            force_refresh=True,
            min_count=MIN_VALID_TOPIC_COUNT,
        )
        logger.info(
            "topic pool ready size=%s valid=%s next_page=%s force_refresh=%s excluded=%s",
            len(pool),
            len(valid_topic_reference_ids(pool)),
            next_page,
            search["force_refresh"],
            len(search["exclude_ids"]),
        )
        return pool, next_page

    async def _top_up_reference_pool(
        self,
        context: dict[str, Any],
        pool: list[dict[str, Any]],
        start_page: int,
    ) -> tuple[list[dict[str, Any]], int]:
        search = await self._search_context(context)
        if not search["keywords"] or not search["platforms"] or start_page > 6:
            return pool, start_page
        extra = await refresh_topic_reference_pool_by_keywords(
            keywords=search["keywords"],
            platforms=search["platforms"],
            exclude_content_ids=search["exclude_ids"],
            crawler=search["crawler"],
            cookie_pool=search["cookie_pool"],
            runtime_settings=search["runtime_settings"],
            start_page=start_page,
        )
        merged = merge_topic_reference_pools(
            pool,
            extra,
            exclude_content_ids=search["exclude_ids"],
        )
        return merged, start_page + 1

    async def execute(self) -> dict[str, Any]:
        record: Any = self.store.get_workflow(self.workflow_id)
        if record is None:
            raise ValueError(f"workflow {self.workflow_id} not found")

        self.store.update_progress(self.workflow_id, progress=10, current_stage="context_loading")
        context = self.store.topic_recommendation_context(record.account_id)
        if not context:
            raise ValueError("topic recommendation context is unavailable")

        # 原文池不足 8 条时用普通搜索补齐（换一批会先重搜）
        reference_contents, next_search_page = await self._ensure_reference_pool(context)
        if reference_contents:
            account_report = dict(context.get("accountReport") or {})
            account_report["topicReferencePool"] = reference_contents
            context = {**context, "accountReport": account_report}
            try:
                self.store.update_report_topic_reference_pool(
                    record.account_id,
                    reference_contents,
                )
            except Exception:
                logger.exception(
                    "persist refreshed topicReferencePool failed account_id=%s",
                    record.account_id,
                )

        prompt = build_topic_recommendation_user_prompt(context)
        step_id = self.store.create_step(
            workflow_id=self.workflow_id,
            user_id=record.user_id,
            account_id=record.account_id,
            step_type="topic_recommendation",
            input_payload={"prompt": prompt},
            group_key="topic_recommendation",
        )

        account_report = context.get("accountReport") or {}
        hot_titles = [
            str(item.get("title") or "").strip()
            for item in list(account_report.get("hotContents") or [])
            if isinstance(item, dict) and str(item.get("title") or "").strip()
        ]
        avoid_titles = [
            str(item).strip()
            for item in list(context.get("existingTopicTitles") or [])
            if str(item or "").strip()
        ]
        account_platforms = list((context.get("account") or {}).get("platforms") or [])
        account_platform = str((context.get("account") or {}).get("platform") or "")
        topics: list[dict[str, Any]] = []
        fallbacks: list[str] = []
        parsed_raw_topics: Any = None
        validation_error = "topic recommendation returned invalid JSON"

        self.store.mark_step_running(step_id)
        for attempt in range(TOPIC_RECOMMENDATION_MAX_ATTEMPTS):
            if attempt == 0:
                attempt_prompt = prompt
                self.store.update_progress(
                    self.workflow_id,
                    progress=40,
                    current_stage="ai_recommendation",
                )
            else:
                attempt_prompt = build_topic_recommendation_retry_prompt(
                    context,
                    validation_error=validation_error,
                    valid_topic_count=len(topics),
                    fallbacks=fallbacks,
                )
                self.store.update_progress(
                    self.workflow_id,
                    progress=55,
                    current_stage="ai_correction_retry",
                )
            try:
                raw = await self.ai_service.chat_completion(
                    messages=[{"role": "user", "content": attempt_prompt}],
                    system_prompt=build_topic_recommendation_system_prompt(),
                    temperature=0.9,
                    model=ACCOUNT_REPORT_FAST_LLM_MODEL,
                    extra_body=ACCOUNT_REPORT_LLM_EXTRA_BODY,
                )
            except Exception as exc:
                self.store.mark_step_failed(step_id, str(exc) or exc.__class__.__name__)
                raise

            if raw == AI_SERVICE_FORBIDDEN_SENTINEL:
                self.store.mark_step_failed(step_id, "AI service token is not configured")
                raise ValueError("AI service token is not configured")

            parsed = parse_topic_recommendation_payload(raw)
            topics = []
            fallbacks = []
            if parsed:
                parsed_raw_topics = parsed.get("topics") if isinstance(parsed, dict) else parsed
                topics, fallbacks = normalize_recommended_topics(
                    parsed_raw_topics,
                    account_platforms,
                    account_platform,
                    reference_contents,
                    convert_invalid_image_reference_to_video=attempt > 0,
                    avoid_titles=avoid_titles,
                    hot_titles=hot_titles,
                )

            if parsed and len(topics) < MIN_VALID_TOPIC_COUNT:
                filled, fill_fallbacks = fill_topics_from_reference_pool(
                    topics,
                    reference_contents,
                    allowed_platforms=account_platforms,
                    canonical_platform=account_platform,
                    avoid_titles=avoid_titles,
                    hot_titles=hot_titles,
                    need=MIN_VALID_TOPIC_COUNT,
                )
                topics = filled
                fallbacks.extend(fill_fallbacks)

            while (
                parsed
                and len(topics) < MIN_VALID_TOPIC_COUNT
                and next_search_page <= 6
            ):
                self.store.update_progress(
                    self.workflow_id,
                    progress=50,
                    current_stage="keyword_research",
                )
                reference_contents, next_search_page = await self._top_up_reference_pool(
                    context,
                    reference_contents,
                    next_search_page,
                )
                if parsed_raw_topics:
                    topics, fallbacks = normalize_recommended_topics(
                        parsed_raw_topics,
                        account_platforms,
                        account_platform,
                        reference_contents,
                        convert_invalid_image_reference_to_video=True,
                        avoid_titles=avoid_titles,
                        hot_titles=hot_titles,
                    )
                filled, fill_fallbacks = fill_topics_from_reference_pool(
                    topics,
                    reference_contents,
                    allowed_platforms=account_platforms,
                    canonical_platform=account_platform,
                    avoid_titles=avoid_titles,
                    hot_titles=hot_titles,
                    need=MIN_VALID_TOPIC_COUNT,
                )
                topics = filled
                fallbacks.extend(fill_fallbacks)
                if len(valid_topic_reference_ids(reference_contents)) >= MIN_VALID_TOPIC_COUNT:
                    break

            self.store.update_progress(
                self.workflow_id,
                progress=75,
                current_stage="normalization",
            )
            if not parsed and not topics:
                validation_error = "topic recommendation returned invalid JSON"
            elif len(topics) < MIN_VALID_TOPIC_COUNT:
                validation_error = (
                    f"at least {MIN_VALID_TOPIC_COUNT} valid topics are required"
                )
                logger.warning(
                    "topic recommendation short batch workflow_id=%s valid=%s pool=%s fallbacks=%s",
                    self.workflow_id,
                    len(topics),
                    len(valid_topic_reference_ids(reference_contents)),
                    fallbacks[:20],
                )
            else:
                topics = topics[:TOPIC_RECOMMENDATION_COUNT]
                has_refs = _has_valid_reference(reference_contents)
                if has_refs and not any(
                    str((topic.get("referenceNote") or {}).get("publicUrl") or "").strip()
                    for topic in topics
                ):
                    validation_error = "topics must keep original reference notes"
                else:
                    validation_error = ""
                    break

        if validation_error:
            self.store.mark_step_failed(step_id, validation_error)
            raise ValueError(validation_error)

        result = {
            "knowledgeBaseUsed": bool(context.get("knowledgeBaseUsed")),
            "accountContext": context.get("account") or {},
            "knowledgeContext": context.get("knowledgeContext") or "",
            "accountReport": context.get("accountReport"),
            "topics": topics,
            "fallbacks": fallbacks,
        }
        self.store.update_progress(self.workflow_id, progress=90, current_stage="topic_replacement")
        try:
            self.store.replace_account_topics(
                workflow_id=self.workflow_id,
                user_id=record.user_id,
                account_id=record.account_id,
                topics=topics,
            )
        except Exception as exc:
            self.store.mark_step_failed(step_id, str(exc) or exc.__class__.__name__)
            raise
        self.store.mark_step_completed(step_id, {"raw": raw, "topics": topics, "fallbacks": fallbacks})
        self.store.update_progress(self.workflow_id, progress=100, current_stage="completed", result_payload=result)
        return result
