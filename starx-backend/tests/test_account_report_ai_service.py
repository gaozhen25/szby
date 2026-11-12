from types import SimpleNamespace

from app.api.workflow_deps import get_account_report_workflow_service
from app.services.account_report.ai_service import (
    ACCOUNT_REPORT_LLM_MODEL,
    account_report_ai_service,
)
from app.services.account_report.scheduler import AccountReportWorkflowScheduler


class RecordingScheduler:
    def __init__(self) -> None:
        self.submissions: list[tuple[str, str, dict[str, object]]] = []

    def submit(self, workflow_type: str, workflow_id: str, context=None) -> None:  # noqa: ANN001
        self.submissions.append((workflow_type, workflow_id, context))


def test_account_report_uses_dedicated_qwen_service():
    assert ACCOUNT_REPORT_LLM_MODEL == "qwen3.6-plus"
    assert account_report_ai_service.llm_model == "qwen3.6-plus"

    service = get_account_report_workflow_service(SimpleNamespace(session=object()))

    assert service.ai_service is account_report_ai_service


def test_account_report_scheduler_injects_dedicated_ai_service():
    scheduler = RecordingScheduler()
    dashboard_source = object()
    adapter = AccountReportWorkflowScheduler(
        ai_service=account_report_ai_service,
        dashboard_source=dashboard_source,  # type: ignore[arg-type]
        scheduler_factory=lambda: scheduler,
    )

    adapter.submit("account_report", "workflow-1", context={"source": "api"})

    assert scheduler.submissions == [
        (
            "account_report",
            "workflow-1",
            {
                "source": "api",
                "_ai_service": account_report_ai_service,
                "_dashboard_source": dashboard_source,
            },
        )
    ]
