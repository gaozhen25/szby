"""账号报告 AI 输入的最小业务上下文。"""

from __future__ import annotations

from typing import Any


_ACCOUNT_FIELDS = (
    "name",
    "description",
    "purpose",
    "type",
    "industry",
    "productService",
    "targetCity",
    "targetAudience",
    "conversionGoal",
    "platforms",
)
_KNOWLEDGE_PREFIXES = ("产品: ", "产品介绍: ", "品牌故事: ", "价格: ")


def build_account_report_ai_context(
    account: dict[str, Any],
    *,
    knowledge_enabled: bool,
    knowledge_context: str,
) -> dict[str, Any]:
    """仅保留生成账号策略所需的账号档案和知识库字段。"""

    safe_account = {
        key: account[key]
        for key in _ACCOUNT_FIELDS
        if account.get(key) not in (None, "")
    }
    safe_knowledge = "\n".join(
        line
        for line in str(knowledge_context or "").splitlines()
        if line.startswith(_KNOWLEDGE_PREFIXES)
    )
    return {
        "account": safe_account,
        "knowledgeEnabled": bool(knowledge_enabled and safe_knowledge),
        "knowledgeContext": safe_knowledge,
    }
