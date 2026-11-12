from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.deps import get_service, get_similar_account_resolver
from app.api.routes.competitors import (
    get_competitor_monitoring_service,
    get_competitor_scheduler,
)
from app.db.init_db import init_database
from app.main import app
from app.services.competitor_monitoring.service import CompetitorMonitoringService
from app.services.competitor_monitoring.models import (
    NormalizedCompetitor,
    NormalizedCompetitorVideo,
)
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


class StubAccountResolver:
    def __init__(self):
        self.requests = []

    async def resolve(
        self,
        profile_url="",
        *,
        platform="",
        account_id="",
    ):
        self.requests.append(
            {
                "profileUrl": profile_url,
                "platform": platform,
                "accountId": account_id,
            }
        )
        return {
            "name": "已解析账号",
            "platform": platform,
            "profileUrl": (
                "https://www.douyin.com/user/MS4wLjAB-resolved"
                if platform == "抖音"
                else "https://www.xiaohongshu.com/user/profile/resolved-user-id"
            ),
        }


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
    service = CompetitorMonitoringService(session_factory=factory)
    scheduler = RecordingScheduler()
    resolver = StubAccountResolver()
    app.dependency_overrides[get_service] = lambda: DBService(auth_session)
    app.dependency_overrides[get_competitor_monitoring_service] = lambda: service
    app.dependency_overrides[get_competitor_scheduler] = lambda: scheduler
    app.dependency_overrides[get_similar_account_resolver] = lambda: resolver
    return TestClient(app), service, scheduler, resolver, auth_session


def _cleanup(auth_session):
    app.dependency_overrides.clear()
    auth_session.close()


def test_user_can_add_list_and_delete_competitor_account():
    client, _service, scheduler, _resolver, session = _harness()
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
        assert created.json()["target"]["secUserId"] == "a"
        assert listed.json()[0]["id"] == target_id
        assert listed.json()[0]["secUserId"] == "a"
        assert deleted.status_code == 204
        assert scheduler.submissions == [
            ("competitor_refresh", created.json()["workflow"]["id"])
        ]
    finally:
        _cleanup(session)


def test_user_can_add_competitor_account_from_platform_account_id():
    client, _service, scheduler, resolver, session = _harness()
    try:
        headers = _headers(client)
        created = client.post(
            "/api/v1/accounts/acc1/competitors/accounts",
            headers=headers,
            json={"platform": "抖音", "accountId": "2012721597"},
        )

        assert created.status_code == 201
        assert created.json()["target"]["platform"] == "dy"
        assert created.json()["target"]["profileUrl"] == (
            "https://www.douyin.com/user/MS4wLjAB-resolved"
        )
        assert created.json()["target"]["secUserId"] == "MS4wLjAB-resolved"
        assert resolver.requests == [
            {
                "profileUrl": "",
                "platform": "抖音",
                "accountId": "2012721597",
            }
        ]
        assert scheduler.submissions == [
            ("competitor_refresh", created.json()["workflow"]["id"])
        ]
    finally:
        _cleanup(session)


def test_user_can_add_xiaohongshu_competitor_from_platform_account_id():
    client, _service, scheduler, resolver, session = _harness()
    try:
        headers = _headers(client)
        created = client.post(
            "/api/v1/accounts/acc1/competitors/accounts",
            headers=headers,
            json={"platform": "小红书", "accountId": "11672196288"},
        )

        assert created.status_code == 201
        assert created.json()["target"]["platform"] == "xhs"
        assert created.json()["target"]["profileUrl"] == (
            "https://www.xiaohongshu.com/user/profile/resolved-user-id"
        )
        assert resolver.requests == [
            {
                "profileUrl": "",
                "platform": "小红书",
                "accountId": "11672196288",
            }
        ]
        assert scheduler.submissions == [
            ("competitor_refresh", created.json()["workflow"]["id"])
        ]
    finally:
        _cleanup(session)


def test_backend_auto_detects_unified_competitor_reference_type():
    client, _service, scheduler, resolver, session = _harness()
    try:
        headers = _headers(client)
        from_id = client.post(
            "/api/v1/accounts/acc1/competitors/accounts",
            headers=headers,
            json={"platform": "抖音", "reference": "2012721597"},
        )
        from_url = client.post(
            "/api/v1/accounts/acc1/competitors/accounts",
            headers=headers,
            json={
                "platform": "小红书",
                "reference": "https://www.xiaohongshu.com/user/profile/url-user",
            },
        )

        assert from_id.status_code == 201
        assert from_url.status_code == 201
        assert resolver.requests == [
            {
                "profileUrl": "",
                "platform": "抖音",
                "accountId": "2012721597",
            }
        ]
        assert from_url.json()["target"]["profileUrl"] == (
            "https://www.xiaohongshu.com/user/profile/url-user"
        )
        assert len(scheduler.submissions) == 2
    finally:
        _cleanup(session)


def test_competitor_account_reference_requires_exactly_one_input():
    client, _service, _scheduler, _resolver, session = _harness()
    try:
        headers = _headers(client)
        missing = client.post(
            "/api/v1/accounts/acc1/competitors/accounts",
            headers=headers,
            json={"platform": "小红书"},
        )
        ambiguous = client.post(
            "/api/v1/accounts/acc1/competitors/accounts",
            headers=headers,
            json={
                "platform": "小红书",
                "accountId": "red-id",
                "profileUrl": "https://www.xiaohongshu.com/user/profile/user-id",
            },
        )

        assert missing.status_code == 422
        assert ambiguous.status_code == 422
    finally:
        _cleanup(session)


def test_account_content_trends_expose_persisted_detail_snapshots():
    client, service, _scheduler, _resolver, session = _harness()
    try:
        headers = _headers(client)
        created = client.post(
            "/api/v1/accounts/acc1/competitors/accounts",
            headers=headers,
            json={"profileUrl": "https://www.douyin.com/user/trend-author"},
        ).json()
        service.complete_refresh(
            created["workflow"]["id"],
            NormalizedCompetitor(
                platform="dy",
                metrics={"followers": 100, "following": 5, "works": 8, "liked": 900},
                videos=[
                    NormalizedCompetitorVideo(
                        platform_content_id="work-1",
                        title="趋势作品",
                        content_url="https://www.douyin.com/video/work-1",
                        metrics={"likes": 10, "collects": 2},
                    )
                ],
            ),
        )
        second_workflow, _ = service.create_refresh(
            "u_001", "acc1", "account", created["target"]["id"], "manual"
        )
        service.complete_refresh(
            second_workflow.id,
            NormalizedCompetitor(
                platform="dy",
                metrics={"followers": 120, "following": 6, "works": 9, "liked": 980},
            ),
        )

        response = client.get(
            f"/api/v1/accounts/acc1/competitors/accounts/{created['target']['id']}/content-trends?days=7",
            headers=headers,
        )

        assert response.status_code == 200
        assert response.json()[0]["platformContentId"] == "work-1"
        assert response.json()[0]["points"][0]["metrics"] == {
            "likes": 10,
            "collects": 2,
        }
        metric_response = client.get(
            f"/api/v1/accounts/acc1/competitors/accounts/{created['target']['id']}/metric-trends?days=30",
            headers=headers,
        )
        assert metric_response.status_code == 200
        assert [point["metrics"]["followers"] for point in metric_response.json()] == [
            100,
            120,
        ]
    finally:
        _cleanup(session)


def test_user_can_add_list_and_delete_competitor_video():
    client, _service, scheduler, _resolver, session = _harness()
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
    client, _service, _scheduler, _resolver, session = _harness()
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
    client, _service, scheduler, _resolver, session = _harness()
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
    client, _service, scheduler, _resolver, session = _harness()
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
    client, service, scheduler, _resolver, session = _harness()
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
    client, service, scheduler, _resolver, session = _harness()
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
