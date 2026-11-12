import asyncio
import importlib
from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

from app.db.init_db import init_database
from app.db.models import (
    CompetitorAccountRecord,
    CompetitorVideoRecord,
    WorkflowRecord,
)
from app.services.competitor_monitoring.periodic_scheduler import (
    CompetitorPeriodicScheduler,
)
from app.services.competitor_monitoring.service import CompetitorMonitoringService


class RecordingWorkflowScheduler:
    def __init__(self):
        self.submissions = []
        self.fail_first = False

    def submit(self, workflow_type, workflow_id, context=None):
        self.submissions.append((workflow_type, workflow_id))
        if self.fail_first and len(self.submissions) == 1:
            raise RuntimeError("Cookie=must-not-leak")


def _harness():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def _enable_sqlite_foreign_keys(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    init_database(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    service = CompetitorMonitoringService(
        session_factory=factory,
        refresh_interval_seconds=21600,
    )
    workflow_scheduler = RecordingWorkflowScheduler()
    periodic = CompetitorPeriodicScheduler(
        competitor_service=service,
        workflow_scheduler=workflow_scheduler,
        scan_seconds=60,
        batch_size=20,
        stale_workflow_seconds=7200,
    )
    return factory, service, workflow_scheduler, periodic


def _save_due_targets(factory):
    due = datetime.now(UTC) - timedelta(minutes=1)
    with factory() as session:
        session.add_all(
            [
                CompetitorAccountRecord(
                    id="ca_due",
                    account_id="acc1",
                    user_id="u_001",
                    platform="dy",
                    profile_url="https://www.douyin.com/user/due",
                    refresh_status="succeeded",
                    next_refresh_at=due,
                ),
                CompetitorVideoRecord(
                    id="cv_due",
                    account_id="acc1",
                    user_id="u_001",
                    platform="dy",
                    content_url="https://www.douyin.com/video/due",
                    refresh_status="succeeded",
                    next_refresh_at=due,
                ),
            ]
        )
        session.commit()


def test_scan_submits_due_account_and_video_once():
    factory, _service, workflow_scheduler, periodic = _harness()
    _save_due_targets(factory)

    assert asyncio.run(periodic.scan_once()) == 2
    assert asyncio.run(periodic.scan_once()) == 0
    assert [item[0] for item in workflow_scheduler.submissions] == [
        "competitor_refresh",
        "competitor_refresh",
    ]
    with factory() as session:
        targets = [
            session.get(CompetitorAccountRecord, "ca_due"),
            session.get(CompetitorVideoRecord, "cv_due"),
        ]
        assert all(target.active_workflow_id for target in targets)
        assert all(
            session.get(WorkflowRecord, target.active_workflow_id) is not None
            for target in targets
        )


def test_one_submission_failure_does_not_stop_other_due_targets():
    factory, service, workflow_scheduler, periodic = _harness()
    _save_due_targets(factory)
    workflow_scheduler.fail_first = True

    assert asyncio.run(periodic.scan_once()) == 2
    assert len(workflow_scheduler.submissions) == 2
    accounts = service.list_accounts("u_001", "acc1")
    videos = service.list_videos("u_001", "acc1")
    statuses = {accounts[0].refresh_status, videos[0].refresh_status}
    assert statuses == {"failed", "pending"}


def test_scan_recovers_terminal_workflow_claim_after_restart():
    factory, service, workflow_scheduler, periodic = _harness()
    video, old_workflow = service.add_video(
        "u_001", "acc1", "https://www.douyin.com/video/restart"
    )
    with factory() as session:
        session.get(WorkflowRecord, old_workflow.id).status = "failed"
        saved = session.get(CompetitorVideoRecord, video.id)
        next_refresh_at = saved.next_refresh_at
        if next_refresh_at.tzinfo is None:
            next_refresh_at = next_refresh_at.replace(tzinfo=UTC)
        assert next_refresh_at > datetime.now(UTC)
        session.commit()

    assert asyncio.run(periodic.scan_once()) == 1
    assert workflow_scheduler.submissions[0][1] != old_workflow.id


def test_scan_recovers_previously_released_stale_target_without_waiting_interval():
    factory, service, workflow_scheduler, periodic = _harness()
    video, old_workflow = service.add_video(
        "u_001", "acc1", "https://www.douyin.com/video/old-restart"
    )
    with factory() as session:
        workflow = session.get(WorkflowRecord, old_workflow.id)
        workflow.status = "failed"
        saved = session.get(CompetitorVideoRecord, video.id)
        saved.active_workflow_id = None
        saved.refresh_status = "failed"
        saved.refresh_error_code = "workflow_stale"
        next_refresh_at = saved.next_refresh_at
        if next_refresh_at.tzinfo is None:
            next_refresh_at = next_refresh_at.replace(tzinfo=UTC)
        assert next_refresh_at > datetime.now(UTC)
        session.commit()

    assert asyncio.run(periodic.scan_once()) == 1
    assert workflow_scheduler.submissions[0][1] != old_workflow.id


def test_scan_recovers_stale_running_workflow_after_abrupt_restart():
    factory, service, workflow_scheduler, periodic = _harness()
    video, old_workflow = service.add_video(
        "u_001", "acc1", "https://www.douyin.com/video/stale"
    )
    with factory() as session:
        workflow = session.get(WorkflowRecord, old_workflow.id)
        workflow.status = "running"
        workflow.updated_at = datetime.now(UTC) - timedelta(hours=3)
        saved = session.get(CompetitorVideoRecord, video.id)
        saved.next_refresh_at = datetime.now(UTC) - timedelta(minutes=1)
        session.commit()

    assert asyncio.run(periodic.scan_once()) == 1
    assert workflow_scheduler.submissions[0][1] != old_workflow.id
    with factory() as session:
        assert session.get(WorkflowRecord, old_workflow.id).status == "failed"


def test_periodic_loop_starts_and_stops_without_waiting_for_timeout():
    _factory, _service, _workflow_scheduler, periodic = _harness()

    async def run():
        periodic.start()
        assert periodic.is_running is True
        await periodic.stop()
        assert periodic.is_running is False

    asyncio.run(run())


def test_periodic_loop_scans_immediately_on_start():
    factory, _service, workflow_scheduler, periodic = _harness()
    _save_due_targets(factory)

    async def run():
        periodic.start()
        for _ in range(50):
            if len(workflow_scheduler.submissions) == 2:
                break
            await asyncio.sleep(0.01)
        await periodic.stop()

    asyncio.run(run())

    assert len(workflow_scheduler.submissions) == 2


def test_app_lifespan_starts_and_stops_competitor_scheduler(monkeypatch):
    main_module = importlib.import_module("app.main")
    calls = []

    class FakePeriodicScheduler:
        def start(self):
            calls.append("start")

        async def stop(self):
            calls.append("stop")

    class FakeWorkflowScheduler:
        def start(self):
            calls.append("workflow_start")

        async def shutdown(self):
            calls.append("workflow_stop")

    monkeypatch.setattr(
        main_module, "competitor_periodic_scheduler", FakePeriodicScheduler()
    )
    monkeypatch.setattr(main_module, "workflow_scheduler", FakeWorkflowScheduler())
    monkeypatch.setattr(
        main_module,
        "mark_unfinished_jobs_failed_on_shutdown",
        lambda: calls.append("shutdown"),
    )

    with TestClient(main_module.app):
        assert calls == ["workflow_start", "start"]

    assert calls == ["workflow_start", "start", "stop", "workflow_stop", "shutdown"]
