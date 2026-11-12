"""账号报告 workflow 注册与编排。"""

from .report import AccountReportWorkflow
from .sections import (
    ComplianceRulesReportWorkflow,
    HotContentsReportWorkflow,
    SimilarAccountsReportWorkflow,
    TargetUserProfileReportWorkflow,
)

__all__ = [
    "AccountReportWorkflow",
    "ComplianceRulesReportWorkflow",
    "HotContentsReportWorkflow",
    "SimilarAccountsReportWorkflow",
    "TargetUserProfileReportWorkflow",
]
