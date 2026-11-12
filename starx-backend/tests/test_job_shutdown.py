from datetime import UTC, datetime

from fastapi.testclient import TestClient

from app.db.models import WorkflowRecord, WorkflowStepRecord
from app import main
from app.services.workflow.shutdown import fail_unfinished_jobs
from tests.db_test_utils import db_session


def test_app_lifespan_marks_unfinished_jobs_failed_on_shutdown(monkeypatch):
    calls = []

    def fake_shutdown() -> None:
        calls.append("shutdown")

    monkeypatch.setattr(main, "mark_unfinished_jobs_failed_on_shutdown", fake_shutdown)

    with TestClient(main.app):
        assert calls == []

    assert calls == ["shutdown"]


def test_fail_unfinished_jobs_marks_only_pending_and_running_records_failed():
    with db_session() as session:
        now = datetime.now(UTC)
        session.add_all(
            [
                WorkflowRecord(
                    id="job_pending",
                    account_id="acc1",
                    user_id="u_001",
                    type="prompt",
                    status="pending",
                    target_platform="小红书",
                    error="",
                    created_at=now,
                    updated_at=now,
                ),
                WorkflowRecord(
                    id="job_running",
                    account_id="acc1",
                    user_id="u_001",
                    type="image",
                    status="running",
                    target_platform="小红书",
                    error="",
                    created_at=now,
                    updated_at=now,
                ),
                WorkflowRecord(
                    id="job_completed",
                    account_id="acc1",
                    user_id="u_001",
                    type="prompt",
                    status="completed",
                    target_platform="小红书",
                    error="",
                    created_at=now,
                    updated_at=now,
                ),
                WorkflowRecord(
                    id="video_running",
                    user_id="u_001",
                    account_id="acc1",
                    type="video_analysis",
                    status="running",
                    video_url="https://oss.example.test/video.mp4",
                    error="",
                    created_at=now,
                    updated_at=now,
                ),
                WorkflowRecord(
                    id="digital_human_running",
                    user_id="u_001",
                    account_id="acc1",
                    type="digital_human_video",
                    status="running",
                    error="",
                    created_at=now,
                    updated_at=now,
                ),
                WorkflowStepRecord(
                    id="sub_pending",
                    workflow_id="job_pending",
                    user_id="u_001",
                    account_id="acc1",
                    type="image_analysis",
                    status="pending",
                    error="",
                    created_at=now,
                    updated_at=now,
                ),
            ]
        )
        session.commit()

        counts = fail_unfinished_jobs(session)

        assert counts == {
            "workflows": 3,
            "workflow_steps": 1,
        }
        assert session.get(WorkflowRecord, "job_pending").status == "failed"
        assert session.get(WorkflowRecord, "job_running").status == "failed"
        assert session.get(WorkflowRecord, "video_running").status == "failed"
        assert session.get(WorkflowStepRecord, "sub_pending").status == "failed"
        assert session.get(WorkflowRecord, "job_completed").status == "completed"
        assert session.get(WorkflowRecord, "digital_human_running").status == "running"
