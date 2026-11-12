"""Shared FastAPI dependencies for background workflow endpoints."""

from fastapi import Depends

from app.api.deps import get_service
from app.core.logging import get_logger
from app.services.account_report.ai_service import account_report_ai_service
from app.services.account_report.scheduler import AccountReportWorkflowScheduler
from app.services.db_service import DBService
from app.services.workflow import WorkflowService

# 账号报告 workflow 在 API 组装边界注册，避免基类包反向导入业务 workflow。
from app.services.account_report.workflows import report as _account_report  # noqa: F401,E402
from app.services.account_report.workflows import sections as _account_report_sections  # noqa: F401,E402

logger = get_logger(__name__)
ACCOUNT_REPORT_DISPATCH_ERROR = "账号报告任务提交失败，请稍后重试"
account_report_scheduler = AccountReportWorkflowScheduler(ai_service=account_report_ai_service)


def get_account_report_workflow_service(db_service: DBService = Depends(get_service)) -> WorkflowService:
    return WorkflowService(db_service.session, ai_service=account_report_ai_service)


def get_account_report_scheduler() -> AccountReportWorkflowScheduler:
    return account_report_scheduler


def log_account_report_dispatch_failure(exc: Exception) -> None:
    """Log dispatch failure metadata without serializing exception secrets."""

    logger.error("account report workflow dispatch failed error_type=%s", exc.__class__.__name__)
