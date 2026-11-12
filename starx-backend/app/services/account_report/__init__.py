"""账号报告领域服务。"""

from .domain import AccountReportEvidence, AccountReportPayload, KeywordPlan, ReportEvidence
from .evidence import build_report_evidence, normalize_metric
from .generation.prompts import (
    build_account_report_prompt,
    build_keyword_planning_prompt,
    parse_account_report,
)

__all__ = [
    "AccountReportPayload",
    "AccountReportEvidence",
    "KeywordPlan",
    "ReportEvidence",
    "build_account_report_prompt",
    "build_keyword_planning_prompt",
    "build_report_evidence",
    "normalize_metric",
    "parse_account_report",
]
