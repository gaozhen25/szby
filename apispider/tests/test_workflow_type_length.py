from app.db.models import WorkflowRecord
from app.services.account_report.workflow_types import ACCOUNT_REPORT_WORKFLOW_TYPES


def test_workflow_type_column_supports_all_account_report_types():
    column_length = WorkflowRecord.__table__.c.type.type.length

    assert column_length is not None
    assert max(map(len, ACCOUNT_REPORT_WORKFLOW_TYPES)) <= column_length
