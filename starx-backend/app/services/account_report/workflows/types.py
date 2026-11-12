"""账号报告 workflow 类型与板块之间的唯一映射。"""

ACCOUNT_REPORT_WORKFLOW_TYPE = "account_report"

ACCOUNT_REPORT_SECTION_WORKFLOW_TYPES = {
    "similarAccounts": "account_report_similar_accounts",
    "complianceRules": "account_report_compliance_rules",
    "targetUserProfile": "account_report_target_user_profile",
    "hotContents": "account_report_hot_contents",
}

ACCOUNT_REPORT_WORKFLOW_TYPES = (
    ACCOUNT_REPORT_WORKFLOW_TYPE,
    *ACCOUNT_REPORT_SECTION_WORKFLOW_TYPES.values(),
)


def section_workflow_type(section_key: str) -> str:
    try:
        return ACCOUNT_REPORT_SECTION_WORKFLOW_TYPES[section_key]
    except KeyError as exc:
        raise ValueError(f"不支持单独生成账号报告板块：{section_key}") from exc
