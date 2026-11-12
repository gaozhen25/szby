"""账号报告四个可见板块各自独立的 workflow。"""

from app.services.workflow.workflows.base import WorkflowRegister

from .workflow import AccountReportWorkflow
from .workflow_types import ACCOUNT_REPORT_SECTION_WORKFLOW_TYPES


class AccountReportSectionWorkflow(AccountReportWorkflow):
    """复用报告采集管线，但只生成由子类声明的唯一板块。"""

    section_key: str


@WorkflowRegister.register
class SimilarAccountsReportWorkflow(AccountReportSectionWorkflow):
    type = ACCOUNT_REPORT_SECTION_WORKFLOW_TYPES["similarAccounts"]
    section_key = "similarAccounts"


@WorkflowRegister.register
class ComplianceRulesReportWorkflow(AccountReportSectionWorkflow):
    type = ACCOUNT_REPORT_SECTION_WORKFLOW_TYPES["complianceRules"]
    section_key = "complianceRules"


@WorkflowRegister.register
class TargetUserProfileReportWorkflow(AccountReportSectionWorkflow):
    type = ACCOUNT_REPORT_SECTION_WORKFLOW_TYPES["targetUserProfile"]
    section_key = "targetUserProfile"


@WorkflowRegister.register
class HotContentsReportWorkflow(AccountReportSectionWorkflow):
    type = ACCOUNT_REPORT_SECTION_WORKFLOW_TYPES["hotContents"]
    section_key = "hotContents"
