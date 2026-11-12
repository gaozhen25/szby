import logging

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.models import AccountRecord, UserRecord, WorkflowRecord, WorkflowStepRecord
from app.services.workflow import WorkflowService
from tests.test_generation_jobs import FailingImageViewAIService, FakeAIService, FakeStorage, FakeUpload


def _engine():
    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection, connection_record):  # noqa: ARG001
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(bind=engine)
    return engine


def _seed_demo_account(session: Session) -> None:
    session.add(
        UserRecord(
            id="demo-user",
            email="demo-user@example.test",
            password_hash="not-used",
            nickname="Demo User",
            status="active",
        )
    )
    session.add(
        AccountRecord(
            id="acc1",
            user_id="demo-user",
            name="Beauty",
            avatar="美",
            account_type="专业号",
            platform="小红书",
            platforms=["小红书"],
            description="美妆测评",
            purpose="品牌合作",
            status="active",
        )
    )
    session.commit()


def test_prompt_workflow_uses_unified_workflow_records():
    engine = _engine()
    with Session(engine) as session:
        _seed_demo_account(session)
        service = WorkflowService(session, storage=FakeStorage())

        created = service.create_prompt_job(
            user_id="demo-user",
            account_id="acc1",
            images=[FakeUpload("ref.png", "image/png", b"png-bytes")],
            copy_text="copy",
            target_platform="小红书",
            topic_title="topic",
        )

        record = session.get(WorkflowRecord, created.id)
        assert record is not None
        assert record.type == "prompt"
        assert record.progress == 0
        assert record.current_stage == ""


def test_failed_workflow_step_logs_failure_reason(caplog):
    engine = _engine()
    with Session(engine) as session:
        _seed_demo_account(session)
        service = WorkflowService(session, ai_service=FailingImageViewAIService(), storage=FakeStorage())
        created = service.create_prompt_job(
            user_id="demo-user",
            account_id="acc1",
            images=[FakeUpload("ref.png", "image/png", b"png-bytes")],
            copy_text="copy",
            target_platform="小红书",
            topic_title="topic",
        )

        with caplog.at_level(logging.ERROR, logger="app.services.workflow.scheduler"):
            completed = service.run_job("prompt", created.id)

        step = session.query(WorkflowStepRecord).filter(WorkflowStepRecord.workflow_id == created.id).one()
        assert completed.status == "failed"
        assert step.status == "failed"
        assert step.error == "vision service unavailable"
        assert any(
            "workflow step failed" in item.message and "vision service unavailable" in item.message
            for item in caplog.records
        )


def test_script_rewrite_workflow_persists_single_ai_step():
    class ScriptRewriteAIService(FakeAIService):
        async def chat_completion(self, messages, system_prompt=None, temperature=0.7):  # noqa: ANN001, ARG002
            return '{"script":["改写第一句","改写第二句"],"hookSuggestion":"开场钩子","rhythmNote":"节奏说明"}'

    engine = _engine()
    with Session(engine) as session:
        _seed_demo_account(session)
        service = WorkflowService(session, ai_service=ScriptRewriteAIService(), storage=FakeStorage())
        created = service.create_script_rewrite_job(
            user_id="demo-user",
            account_id="acc1",
            original_script=["第一句", "第二句"],
            copy_text="卖点",
            target_platform="小红书",
            topic_title="topic",
        )

        completed = service.run_job("script_rewrite", created.id)

        step = session.query(WorkflowStepRecord).filter(WorkflowStepRecord.workflow_id == created.id).one()
        assert completed.status == "completed"
        assert step.type == "script_rewrite"
        assert step.status == "completed"
        assert step.progress == 100


def test_list_jobs_paginates_generation_history():
    engine = _engine()
    with Session(engine) as session:
        _seed_demo_account(session)
        service = WorkflowService(session, ai_service=FakeAIService(), storage=FakeStorage())
        first = service.create_script_rewrite_job(
            user_id="demo-user",
            account_id="acc1",
            original_script=["第一句"],
            copy_text="卖点一",
            target_platform="小红书",
            topic_title="topic 1",
        )
        second = service.create_script_rewrite_job(
            user_id="demo-user",
            account_id="acc1",
            original_script=["第二句"],
            copy_text="卖点二",
            target_platform="小红书",
            topic_title="topic 2",
        )
        third = service.create_script_rewrite_job(
            user_id="demo-user",
            account_id="acc1",
            original_script=["第三句"],
            copy_text="卖点三",
            target_platform="小红书",
            topic_title="topic 3",
        )

        first_page = service.list_jobs("demo-user", "acc1", page=1, limit=2)
        second_page = service.list_jobs("demo-user", "acc1", page=2, limit=2)

        assert [job.id for job in first_page] == [third.id, second.id]
        assert [job.id for job in second_page] == [first.id]
        assert first_page[0].inputPayload == {}
        assert first_page[0].resultPayload == {}
        assert first_page[0].steps == []


def test_scheduler_uses_configured_default_concurrency(monkeypatch):
    from app.core.config import settings
    from app.services.workflow.scheduler import WorkflowScheduler

    WorkflowScheduler._instance = None
    monkeypatch.setattr(settings, "workflow_max_concurrent", 2)

    scheduler = WorkflowScheduler.get_instance()

    assert scheduler.max_concurrent == 2
    assert scheduler._semaphore is not None
    WorkflowScheduler._instance = None


def test_scheduler_allows_explicit_unbounded_concurrency_for_tests():
    from app.services.workflow.scheduler import WorkflowScheduler

    scheduler = WorkflowScheduler(max_concurrent=None, use_default_concurrency=False)

    assert scheduler.max_concurrent is None
    assert scheduler._semaphore is None
