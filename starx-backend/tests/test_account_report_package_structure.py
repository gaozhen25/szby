"""账号报告领域包的分层边界回归测试。"""

from pathlib import Path

from app.services.account_report.workflows.base import BaseAccountReportWorkflow
from app.services.account_report.workflows.report import AccountReportWorkflow


ACCOUNT_REPORT_PACKAGE = (
    Path(__file__).resolve().parents[1] / "app" / "services" / "account_report"
)


def test_account_report_root_only_contains_public_package_entrypoint():
    root_modules = sorted(path.name for path in ACCOUNT_REPORT_PACKAGE.glob("*.py"))
    assert root_modules == ["__init__.py"]


def test_account_report_capabilities_are_grouped_by_responsibility():
    expected_packages = {
        "collection",
        "domain",
        "evidence",
        "generation",
        "similar_accounts",
        "workflows",
    }
    actual_packages = {
        path.name
        for path in ACCOUNT_REPORT_PACKAGE.iterdir()
        if path.is_dir() and not path.name.startswith("__")
    }
    assert expected_packages <= actual_packages


def test_report_workflow_reuses_account_report_base_class():
    assert issubclass(AccountReportWorkflow, BaseAccountReportWorkflow)
