"""将常见的等价 AI 字段变体收敛到严格账号报告契约。"""

from __future__ import annotations

from typing import Any


_RISK_LEVEL_ALIASES = {
    "high": "high",
    "medium": "medium",
    "low": "low",
    "高": "high",
    "高风险": "high",
    "中": "medium",
    "中风险": "medium",
    "低": "low",
    "低风险": "low",
}
_EXPRESSION_ALIASES = (
    "originalExpression",
    "originalText",
    "originalPhrase",
    "original",
    "riskExpression",
    "原表达",
    "风险表达",
)
_SUGGESTION_ALIASES = (
    "suggestedExpression",
    "suggestedText",
    "replacementExpression",
    "replacementText",
    "alternativeExpression",
    "alternative",
    "replacement",
    "rewrite",
    "建议",
    "建议表达",
    "替代表达",
)


def _copy_first_alias(target: dict[str, Any], field: str, aliases: tuple[str, ...]) -> None:
    if field in target:
        return
    for alias in aliases:
        if alias in target:
            target[field] = target[alias]
            return


def normalize_account_report_response(value: dict[str, Any]) -> dict[str, Any]:
    """只修正常见等价表示；缺失内容和未知结构仍交给 Pydantic 拒绝。"""

    normalized = dict(value)
    rules = normalized.get("complianceRules")
    if isinstance(rules, list):
        normalized_rules: list[Any] = []
        for item in rules:
            if not isinstance(item, dict):
                normalized_rules.append(item)
                continue
            rule = dict(item)
            risk_level = rule.get("riskLevel")
            if isinstance(risk_level, str):
                clean_level = risk_level.strip()
                rule["riskLevel"] = _RISK_LEVEL_ALIASES.get(clean_level.lower(), clean_level)
            _copy_first_alias(rule, "expression", _EXPRESSION_ALIASES)
            _copy_first_alias(rule, "suggestion", _SUGGESTION_ALIASES)
            normalized_rules.append(rule)
        normalized["complianceRules"] = normalized_rules

    strategy = normalized.get("contentStrategy")
    if isinstance(strategy, dict) and isinstance(strategy.get("tone"), str):
        normalized_strategy = dict(strategy)
        normalized_strategy["tone"] = [strategy["tone"]]
        normalized["contentStrategy"] = normalized_strategy

    return normalized
