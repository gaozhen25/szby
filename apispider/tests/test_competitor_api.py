from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.deps import get_service
from app.api.routes.competitors import (
    get_competitor_monitoring_service,
    get_competitor_scheduler,
)
from app.db.init_db import init_database
from app.main import app
from app.services.competitor_monitoring.service import CompetitorMonitoringService
from app.services.competitor_monitoring.models import NormalizedCompetitor
from app.services.db_service import DBService


class RecordingScheduler:
    def __init__(self, error=None):
        self.submissions = []
        self.error = error
        self.fail_on_calls = set()

    def submit(self, workflow_type, workflow_id, context=None):
        self.submissions.append((workflow_type, workflow_id))
        if self.error or len(self.submissions) in self.fail_on_calls:
            raise self.error or RuntimeError("submit failed")


def _headers(client):
    login = client.post(
        "/api/v1/auth/login",
        json={"email": "demo@starx.ai", "password": "demo123"},
    )
    return {"Authorization": f"Bearer {login.json()['accessToken']}"}


def _harness():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    init_database(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    auth_session = factory()
    service = CompetitorMonitoringService(
        session_factory=factory,
        refresh_interval_seconds=21600,
    )
    scheduler = RecordingScheduler()
    app.dependency_overrides[get_service] = lambda: DBService(auth_session)
    app.dependency_overrides[get_competitor_monitoring_service] = lambda: service
    app.dependency_overrides[get_competitor_scheduler] = lambda: scheduler
    return TestClient(app), service, scheduler, auth_session


def _cleanup(auth_session):
    app.dependency_overrides.clear()
    auth_session.close()


def test_user_can_add_list_and_delete_competitor_account():
    client, _service, scheduler, session = _harness()
    try:
        headers = _headers(client)
        created = client.post(
            "/api/v1/accounts/acc1/competitors/accounts",
            headers=headers,
            json={"profileUrl": "https://www.douyin.com/user/a"},
        )
        target_id = created.json()["target"]["id"]
        listed = client.get(
            "/api/v1/accounts/acc1/competitors/accounts", headers=headers
        )
        deleted = client.delete(
            f"/api/v1/accounts/acc1/competitors/accounts/{target_id}",
            headers=headers,
        )

        assert created.status_code == 201
        assert listed.json()[0]["id"] == target_id
        assert deleted.status_code == 204
        assert scheduler.submissions == [
            ("competitor_refresh", created.json()["workflow"]["id"])
        ]
    finally:
        _cleanup(session)


def test_user_can_add_list_and_delete_competitor_video():
    client, _service, scheduler, session = _harness()
    try:
        headers = _headers(client)
        created = client.post(
            "/api/v1/accounts/acc1/competitors/videos",
            headers=headers,
            json={"contentUrl": "https://www.douyin.com/video/1"},
        )
        target_id = created.json()["target"]["id"]
        listed = client.get(
            "/api/v1/accounts/acc1/competitors/videos", headers=headers
        )
        deleted = client.delete(
            f"/api/v1/accounts/acc1/competitors/videos/{target_id}",
            headers=headers,
        )

        assert created.status_code == 201
        assert listed.json()[0]["id"] == target_id
        assert deleted.status_code == 204
        assert scheduler.submissions == [
            ("competitor_refresh", created.json()["workflow"]["id"])
        ]
    finally:
        _cleanup(session)


def test_duplicate_and_cross_account_operations_are_safe():
    client, _service, _scheduler, session = _harness()
    try:
        headers = _headers(client)
        payload = {"contentUrl": "https://www.douyin.com/video/1"}
        first = client.post(
            "/api/v1/accounts/acc1/competitors/videos",
            headers=headers,
            json=payload,
        )
        duplicate = client.post(
            "/api/v1/accounts/acc1/competitors/videos",
            headers=headers,
            json=payload,
        )
        wrong_account = client.delete(
            f"/api/v1/accounts/acc2/competitors/videos/{first.json()['target']['id']}",
            headers=headers,
        )

        assert duplicate.status_code == 409
        assert wrong_account.status_code == 404
    finally:
        _cleanup(session)


def test_repeated_refresh_reuses_active_workflow_without_resubmitting():
    client, _service, scheduler, session = _harness()
    try:
        headers = _headers(client)
        created = client.post(
            "/api/v1/accounts/acc1/competitors/videos",
            headers=headers,
            json={"contentUrl": "https://www.douyin.com/video/1"},
        ).json()
        target_id = created["target"]["id"]
        first = client.post(
            f"/api/v1/accounts/acc1/competitors/videos/{target_id}/refresh",
            headers=headers,
        )
        second = client.post(
            f"/api/v1/accounts/acc1/competitors/videos/{target_id}/refresh",
            headers=headers,
        )
        own = client.get(
            f"/api/v1/accounts/acc1/competitors/refresh-workflows/{first.json()['id']}",
            headers=headers,
        )
        wrong = client.get(
            f"/api/v1/accounts/acc2/competitors/refresh-workflows/{first.json()['id']}",
            headers=headers,
        )

        assert first.json()["id"] == second.json()["id"] == created["workflow"]["id"]
        assert own.status_code == 200
        assert wrong.status_code == 404
        assert scheduler.submissions == [
            ("competitor_refresh", created["workflow"]["id"])
        ]
    finally:
        _cleanup(session)


def test_batch_refresh_returns_all_workflows_without_resubmitting_active_ones():
    client, _service, scheduler, session = _harness()
    try:
        headers = _headers(client)
        for suffix in ("1", "2"):
            client.post(
                "/api/v1/accounts/acc1/competitors/videos",
                headers=headers,
                json={"contentUrl": f"https://www.douyin.com/video/{suffix}"},
            )
        batch = client.post(
            "/api/v1/accounts/acc1/competitors/videos/refresh-batch",
            headers=headers,
        )

        assert batch.status_code == 200
        assert len(batch.json()["workflows"]) == 2
        assert len(scheduler.submissions) == 2
    finally:
        _cleanup(session)


def test_submission_failure_marks_target_and_workflow_failed_without_leaking_error():
    client, service, scheduler, session = _harness()
    scheduler.error = RuntimeError("Cookie=session-secret token=query-secret")
    try:
        headers = _headers(client)
        response = client.post(
            "/api/v1/accounts/acc1/competitors/videos",
            headers=headers,
            json={"contentUrl": "https://www.douyin.com/video/1"},
        )
        targets = service.list_videos("u_001", "acc1")
        workflow = service.get_workflow(
            "u_001", "acc1", scheduler.submissions[0][1]
        )

        assert response.status_code == 500
        assert response.json()["detail"] == "竞品刷新任务提交失败，请稍后重试"
        assert targets == []
        assert workflow.status == "failed"
        assert "secret" not in f"{response.text} {workflow.error}".lower()
    finally:
        _cleanup(session)


def test_batch_submission_failure_finalizes_failed_item_and_submits_remaining_items():
    client, service, scheduler, session = _harness()
    try:
        headers = _headers(client)
        created = []
        for suffix in ("1", "2"):
            created.append(client.post(
                "/api/v1/accounts/acc1/competitors/videos",
                headers=headers,
                json={"contentUrl": f"https://www.douyin.com/video/{suffix}"},
            ).json())
        for item in created:
            service.complete_refresh(
                item["workflow"]["id"],
                NormalizedCompetitor(platform="dy", metrics={"likes": 1}),
            )
        scheduler.fail_on_calls = {3}

        batch = client.post(
            "/api/v1/accounts/acc1/competitors/videos/refresh-batch",
            headers=headers,
        )

        assert batch.status_code == 200
        assert len(scheduler.submissions) == 4
        assert {item["status"] for item in batch.json()["workflows"]} == {"failed", "pending"}
        assert {item.refresh_status for item in service.list_videos("u_001", "acc1")} == {"failed", "pending"}
    finally:
        _cleanup(session)
