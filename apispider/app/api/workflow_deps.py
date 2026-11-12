"""Shared FastAPI dependencies for background workflow endpoints."""

from fastapi import Depends

from app.api.deps import get_service
from app.core.logging import get_logger
from app.services.db_service import DBService
from app.services.workflow import WorkflowScheduler, WorkflowService

logger = get_logger(__name__)
ACCOUNT_REPORT_DISPATCH_ERROR = "账号报告任务提交失败，请稍后重试"


def get_account_report_workflow_service(db_service: DBService = Depends(get_service)) -> WorkflowService:
    return WorkflowService(db_service.session)


def get_account_report_scheduler() -> WorkflowScheduler:
    return WorkflowScheduler.get_instance()


def log_account_report_dispatch_failure(exc: Exception) -> None:
    """Log dispatch failure metadata without serializing exception secrets."""

    logger.error("account report workflow dispatch failed error_type=%s", exc.__class__.__name__)
