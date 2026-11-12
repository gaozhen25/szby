"""为账号报告任务注入专用依赖的调度适配器。"""

from collections.abc import Callable
from typing import Any

from app.services.ai_service import AIService
from app.services.workflow import WorkflowScheduler

from .collection.dashboard_source import AccountDashboardSource


class AccountReportWorkflowScheduler:
    """复用全局调度器，并注入账号报告专用 AI 与看板数据源。"""

    def __init__(
        self,
        *,
        ai_service: AIService,
        dashboard_source: AccountDashboardSource | None = None,
        scheduler_factory: Callable[[], WorkflowScheduler] = WorkflowScheduler.get_instance,
    ) -> None:
        self._ai_service = ai_service
        self._dashboard_source = dashboard_source or AccountDashboardSource()
        self._scheduler_factory = scheduler_factory

    def submit(
        self,
        workflow_type: str,
        workflow_id: str,
        context: dict[str, Any] | None = None,
    ) -> None:
        workflow_context = dict(context or {})
        workflow_context["_ai_service"] = self._ai_service
        workflow_context["_dashboard_source"] = self._dashboard_source
        self._scheduler_factory().submit(workflow_type, workflow_id, context=workflow_context)
