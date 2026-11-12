"""选题 workflow 使用的账号报告最小上下文。"""

from __future__ import annotations

from datetime import UTC
from typing import Any

from app.db.models import ReportRecord

CONTENT_METRIC_FIELDS = (
    "likedCount",
    "collectedCount",
    "commentCount",
    "shareCount",
    "viewCount",
    "engagementScore",
    "hotScore",
)
CREATOR_METRIC_FIELDS = (
    "fansCount",
    "worksCount",
    "interactionCount",
    "hitContentCount",
)
TOPIC_REFERENCE_POOL_LIMIT = 20


def _pick_fields(value: Any, fields: tuple[str, ...]) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    return {field: value[field] for field in fields if field in value}


def _compact_metrics(value: Any, allowed_fields: tuple[str, ...]) -> dict[str, int | float]:
    return {
        key: metric
        for key, metric in _pick_fields(value, allowed_fields).items()
        if isinstance(metric, (int, float)) and not isinstance(metric, bool)
    }


def _compact_hot_content(value: Any) -> dict[str, Any]:
    compact = _pick_fields(
        value,
        (
            "platform",
            "contentId",
            "title",
            "summary",
            "selectionReason",
            "publicUrl",
            "coverUrl",
            "contentType",
            "sourceKeyword",
            "sourceSort",
            "publishedAt",
            "hotScore",
        ),
    )
    compact["metrics"] = _compact_metrics(
        value.get("metrics") if isinstance(value, dict) else None,
        CONTENT_METRIC_FIELDS,
    )
    return compact


def _compact_target_user_profile(value: Any) -> dict[str, Any]:
    """兼容旧画像，并对白名单化的新画像嵌套结构做限量裁剪。"""

    if not isinstance(value, dict):
        return {}
    compact = _pick_fields(
        value,
        (
            "assumption",
            "summary",
            "coreNeeds",
            "contentPreferences",
            "purchaseConcerns",
            "conversionTriggers",
        ),
    )
    if "categories" in value:
        compact["categories"] = []
        for item in list(value.get("categories") or [])[:5]:
            category = _pick_fields(item, ("categoryName", "specificProfile", "purchaseMotivation"))
            if not category:
                continue
            male_profile = _pick_fields(
                item.get("maleProfile") if isinstance(item, dict) else None,
                ("applicable", "description"),
            )
            female_profile = _pick_fields(
                item.get("femaleProfile") if isinstance(item, dict) else None,
                ("applicable", "description"),
            )
            if male_profile:
                category["maleProfile"] = male_profile
            if female_profile:
                category["femaleProfile"] = female_profile
            compact["categories"].append(category)

    priority = value.get("priorityRanking")
    if isinstance(priority, dict):
        compact_priority = _pick_fields(priority, ("priorityCategory", "priorityReason"))
        compact_priority["rankedCategories"] = [
            _pick_fields(
                item,
                (
                    "categoryName",
                    "priority",
                    "contentAttraction",
                    "trustDifficulty",
                    "paymentLikelihood",
                    "repurchaseLikelihood",
                    "reason",
                ),
            )
            for item in list(priority.get("rankedCategories") or [])[:5]
            if isinstance(item, dict)
        ]
        compact["priorityRanking"] = compact_priority

    reminder = value.get("positioningReminder")
    if isinstance(reminder, dict):
        compact["positioningReminder"] = _pick_fields(
            reminder,
            ("commonMisjudgment", "hypothesisToValidate"),
        )
    return compact


def _merge_topic_reference_pool(
    hot_contents: list[dict[str, Any]],
    source_pool: list[Any],
) -> list[dict[str, Any]]:
    """确保报告中展示给模型的爆款都能作为合法选题引用。

    展示爆款和原始候选池采用不同的排序策略，展示用的类型平衡结果可能落在
    原始候选池截断线之外。优先保留展示爆款，再用原始候选池补足上限；同一
    contentId 优先使用原始候选中的完整字段。
    """

    compact_source_pool = [
        _compact_hot_content(item)
        for item in source_pool
        if isinstance(item, dict)
    ]
    source_by_id = {
        str(item.get("contentId") or "").strip(): item
        for item in compact_source_pool
        if str(item.get("contentId") or "").strip()
    }
    merged: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    def append_unique(item: dict[str, Any]) -> None:
        content_id = str(item.get("contentId") or "").strip()
        if content_id and content_id in seen_ids:
            return
        if content_id:
            seen_ids.add(content_id)
        merged.append(item)

    for hot_content in hot_contents:
        content_id = str(hot_content.get("contentId") or "").strip()
        append_unique(source_by_id.get(content_id, hot_content))
    for source_content in compact_source_pool:
        append_unique(source_content)

    return merged[:TOPIC_REFERENCE_POOL_LIMIT]


def build_topic_report_context(report: ReportRecord | None) -> dict[str, Any] | None:
    """将已生成报告裁剪成选题生成所需的白名单字段。"""

    if report is None or report.report_version <= 0 or report.generated_at is None:
        return None

    hot_contents = []
    for item in list(report.hot_contents or [])[:10]:
        hot_contents.append(_compact_hot_content(item))

    similar_accounts = []
    for item in list(report.similar_accounts or [])[:10]:
        compact = _pick_fields(
            item,
            ("platform", "name", "similarityReason", "representativeContents"),
        )
        compact["metrics"] = _compact_metrics(
            item.get("metrics") if isinstance(item, dict) else None,
            CREATOR_METRIC_FIELDS,
        )
        similar_accounts.append(compact)

    compliance_rules = [
        _pick_fields(item, ("riskLevel", "expression", "reason", "suggestion", "platforms"))
        for item in list(report.compliance_rules or [])[:20]
    ]
    generated_at = report.generated_at
    if generated_at.tzinfo is None:
        generated_at = generated_at.replace(tzinfo=UTC)
    else:
        generated_at = generated_at.astimezone(UTC)

    source_meta = _pick_fields(
        report.source_meta,
        ("platforms", "keywords", "sampleCount", "unsupportedPlatforms"),
    )
    source_topic_pool = (
        report.source_meta.get("topicReferencePool", [])
        if isinstance(report.source_meta, dict)
        else []
    )
    topic_reference_pool = _merge_topic_reference_pool(
        hot_contents,
        list(source_topic_pool or []),
    )
    failed_platforms = report.source_meta.get("failedPlatforms", []) if isinstance(report.source_meta, dict) else []
    source_meta["failedPlatforms"] = [
        item["platform"]
        for item in failed_platforms
        if isinstance(item, dict) and isinstance(item.get("platform"), str) and item["platform"].strip()
    ]
    source_meta.update(
        {
            "reportVersion": report.report_version,
            "generatedAt": generated_at.isoformat(),
        }
    )
    return {
        "targetUserProfile": _compact_target_user_profile(report.target_user_profile),
        "hotContents": hot_contents,
        "topicReferencePool": topic_reference_pool or hot_contents,
        "similarAccounts": similar_accounts,
        "complianceRules": compliance_rules,
        "sourceMeta": source_meta,
    }
