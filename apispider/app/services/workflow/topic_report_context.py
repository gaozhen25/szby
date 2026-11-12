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
)
CREATOR_METRIC_FIELDS = (
    "fansCount",
    "worksCount",
    "interactionCount",
    "hitContentCount",
)


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
            category = _pick_fields(item, ("categoryName", "purchaseMotivation"))
            if not category:
                continue
            category["maleProfile"] = _pick_fields(
                item.get("maleProfile") if isinstance(item, dict) else None,
                ("applicable", "description"),
            )
            category["femaleProfile"] = _pick_fields(
                item.get("femaleProfile") if isinstance(item, dict) else None,
                ("applicable", "description"),
            )
            compact["categories"].append(category)

    priority = value.get("priorityRanking")
    if isinstance(priority, dict):
        compact_priority = _pick_fields(priority, ("priorityCategory", "priorityReason"))
        compact_priority["rankedCategories"] = [
            _pick_fields(
                item,
                (
                    "categoryName",
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


def build_topic_report_context(report: ReportRecord | None) -> dict[str, Any] | None:
    """将已生成报告裁剪成选题生成所需的白名单字段。"""

    if report is None or report.report_version <= 0 or report.generated_at is None:
        return None

    hot_contents = []
    for item in list(report.hot_contents or [])[:10]:
        compact = _pick_fields(
            item,
            ("platform", "contentId", "title", "selectionReason", "publicUrl", "contentType"),
        )
        compact["metrics"] = _compact_metrics(
            item.get("metrics") if isinstance(item, dict) else None,
            CONTENT_METRIC_FIELDS,
        )
        hot_contents.append(compact)

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
        "contentStrategy": _pick_fields(
            report.content_strategy,
            ("contentPillars", "tone", "opportunities", "avoidDirections"),
        ),
        "hotContents": hot_contents,
        "similarAccounts": similar_accounts,
        "complianceRules": compliance_rules,
        "sourceMeta": source_meta,
    }
