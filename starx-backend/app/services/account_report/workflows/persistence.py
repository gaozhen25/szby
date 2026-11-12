"""账号报告整体替换与单分块更新载荷。"""

from __future__ import annotations

from typing import Any

from ..domain.models import AccountReportPayload


def build_report_persistence_payload(report: AccountReportPayload) -> dict[str, Any]:
    payload = report.model_dump(mode="json", by_alias=True, exclude_none=True)
    payload.update(report.compatibility_summaries())
    return payload


def report_version(value: Any) -> int:
    if isinstance(value, dict):
        return int(value.get("reportVersion") or value.get("report_version") or 0)
    return int(
        getattr(value, "reportVersion", None)
        or getattr(value, "report_version", 0)
        or 0
    )


def build_section_persistence_payload(
    section_key: str,
    value: Any,
    source_meta: dict[str, Any] | None,
) -> dict[str, Any]:
    """构造单分块原子更新载荷，并同步对应的旧版可读摘要。"""

    payload: dict[str, Any] = {section_key: value}
    if source_meta is not None:
        payload["sourceMeta"] = source_meta
    if section_key == "similarAccounts":
        payload["competitors"] = "；".join(
            f"{item.get('name') or '未命名账号'}（{item.get('platform') or '未知平台'}）："
            f"{item.get('similarityReason') or '暂无相似原因'}"
            for item in value
        ) or "暂无足够的公开相似账号样本。"
    elif section_key == "complianceRules":
        risk_labels = {"high": "高", "medium": "中", "low": "低"}
        payload["prohibitedWords"] = "；".join(
            f"[{risk_labels.get(item.get('riskLevel'), '中')}] "
            f"{item.get('expression') or '风险表达'}：{item.get('reason') or '存在风险'}；"
            f"建议：{item.get('suggestion') or '请使用审慎表达'}"
            for item in value
        )
    elif section_key == "targetUserProfile":
        categories = list(value.get("categories") or [])
        ranking = dict(value.get("priorityRanking") or {})
        summary = "；".join(
            f"{item.get('categoryName') or '用户类别'}："
            f"{item.get('purchaseMotivation') or '暂无购买动机'}"
            for item in categories
        )
        priority_category = str(ranking.get("priorityCategory") or "").strip()
        if priority_category:
            summary += (
                f"。优先服务：{priority_category}，"
                f"{ranking.get('priorityReason') or '建议优先验证该用户类别'}"
            )
        payload["targetUsers"] = summary
    elif section_key == "hotContents":
        payload["hotContent"] = "；".join(
            f"{item.get('title') or '未命名内容'}（{item.get('platform') or '未知平台'}）："
            f"{item.get('selectionReason') or '高互动公开内容'}"
            for item in value
        ) or "暂无足够的公开爆款样本。"
    return payload
