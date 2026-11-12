from fastapi.testclient import TestClient
import pytest

from app.api.deps import get_service, get_similar_account_resolver
from app.api.workflow_deps import get_account_report_scheduler, get_account_report_workflow_service
from app.db.models import WorkflowRecord
from app.main import app
from app.services.db_service import DBService
from app.services.workflow import WorkflowService
from tests.db_test_utils import db_session


class RecordingScheduler:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.submissions: list[tuple[str, str]] = []

    def submit(self, workflow_type: str, workflow_id: str, context=None) -> None:  # noqa: ANN001, ARG002
        self.submissions.append((workflow_type, workflow_id))
        if self.error is not None:
            raise self.error


class StubSimilarAccountResolver:
    def __init__(self) -> None:
        self.requests: list[dict[str, str]] = []

    async def resolve(
        self,
        profile_url: str = "",
        *,
        platform: str = "",
        account_id: str = "",
    ) -> dict[str, object]:
        self.requests.append(
            {
                "profileUrl": profile_url,
                "platform": platform,
                "accountId": account_id,
            }
        )
        return {
            "name": "解析到的博主",
            "platform": "小红书",
            "profileUrl": "https://www.xiaohongshu.com/user/profile/resolved-peer",
            "avatarUrl": "https://example.test/avatar.png",
            "description": "公开简介",
            "followers": 12345,
            "follows": 88,
            "contentCount": 66,
            "totalLikes": 98765,
            "ipLocation": "上海",
        }


def _headers(client: TestClient) -> dict[str, str]:
    login = client.post("/api/v1/auth/login", json={"email": "demo@starx.ai", "password": "demo123"})
    return {"Authorization": f"Bearer {login.json()['accessToken']}"}


def _account_payload() -> dict[str, object]:
    return {
        "name": "报告测试号",
        "description": "面向职场人的效率内容",
        "purpose": "获客",
        "type": "普通号",
        "platforms": ["小红书", "抖音"],
        "accountLinks": {
            "小红书": "https://www.xiaohongshu.com/user/profile/sensitive-query?xsec_token=secret",
            "抖音": "https://www.douyin.com/user/safe-public-id",
        },
    }


def _configure(session, scheduler: RecordingScheduler) -> WorkflowService:  # noqa: ANN001
    service = WorkflowService(session)
    app.dependency_overrides[get_service] = lambda: DBService(session)
    app.dependency_overrides[get_account_report_workflow_service] = lambda: service
    app.dependency_overrides[get_account_report_scheduler] = lambda: scheduler
    return service


def test_create_account_submits_one_account_report_workflow_and_keeps_payload_safe():
    with db_session() as session:
        scheduler = RecordingScheduler()
        _configure(session, scheduler)
        try:
            client = TestClient(app)
            headers = _headers(client)

            created = client.post("/api/v1/accounts", headers=headers, json=_account_payload())
            account_id = created.json()["id"]
            latest = client.get(f"/api/v1/accounts/{account_id}/report/workflows/latest", headers=headers)

            assert created.status_code == 200
            assert latest.status_code == 200
            assert latest.json()["type"] == "account_report"
            assert latest.json()["status"] == "pending"
            assert latest.json()["progress"] == 0
            assert latest.json()["currentStage"] == "pending"
            assert latest.json()["inputPayload"] == {
                "accountId": account_id,
                "platforms": ["小红书", "抖音"],
                "referenceComments": False,
            }
            assert "cookie" not in str(latest.json()).lower()
            assert "xsec_token" not in str(latest.json()).lower()
            assert scheduler.submissions == [("account_report", latest.json()["id"])]
        finally:
            app.dependency_overrides.clear()


def test_repeated_report_refresh_reuses_active_workflow_without_resubmitting():
    with db_session() as session:
        scheduler = RecordingScheduler()
        _configure(session, scheduler)
        try:
            client = TestClient(app)
            headers = _headers(client)

            first = client.post(
                "/api/v1/accounts/acc1/report/workflows",
                headers=headers,
                json={"referenceComments": False},
            )
            second = client.post(
                "/api/v1/accounts/acc1/report/workflows",
                headers=headers,
                json={"referenceComments": True},
            )

            assert first.status_code == second.status_code == 200
            assert second.json()["id"] == first.json()["id"]
            assert second.json()["inputPayload"]["referenceComments"] is False
            assert scheduler.submissions == [("account_report", first.json()["id"])]
        finally:
            app.dependency_overrides.clear()


def test_report_refresh_can_explicitly_enable_comment_reference():
    with db_session() as session:
        scheduler = RecordingScheduler()
        _configure(session, scheduler)
        try:
            client = TestClient(app)
            headers = _headers(client)

            response = client.post(
                "/api/v1/accounts/acc1/report/workflows",
                headers=headers,
                json={"referenceComments": True},
            )

            assert response.status_code == 200
            assert response.json()["inputPayload"]["referenceComments"] is True
        finally:
            app.dependency_overrides.clear()


def test_user_can_add_and_delete_a_manual_similar_account():
    with db_session() as session:
        scheduler = RecordingScheduler()
        _configure(session, scheduler)
        try:
            client = TestClient(app)
            headers = _headers(client)

            added = client.post(
                "/api/v1/accounts/acc1/report/similar-accounts",
                headers=headers,
                json={
                    "name": "手动对标账号",
                    "platform": "小红书",
                    "profileUrl": "https://www.xiaohongshu.com/user/profile/manual-peer",
                    "similarityReason": "内容定位接近",
                },
            )

            assert added.status_code == 200
            account = added.json()["similarAccounts"][0]
            assert account["name"] == "手动对标账号"
            assert account["configurationSource"] == "manual"
            assert account["configurationKey"].startswith("manual_")

            deleted = client.delete(
                f"/api/v1/accounts/acc1/report/similar-accounts/{account['configurationKey']}",
                headers=headers,
            )
            assert deleted.status_code == 200
            assert deleted.json()["similarAccounts"] == []
        finally:
            app.dependency_overrides.clear()


def test_user_resolves_similar_account_link_before_confirming_addition():
    with db_session() as session:
        scheduler = RecordingScheduler()
        resolver = StubSimilarAccountResolver()
        _configure(session, scheduler)
        app.dependency_overrides[get_similar_account_resolver] = lambda: resolver
        try:
            client = TestClient(app)
            headers = _headers(client)
            response = client.post(
                "/api/v1/accounts/acc1/report/similar-accounts/resolve",
                headers=headers,
                json={"profileUrl": "https://www.xiaohongshu.com/user/profile/shared-link"},
            )

            assert response.status_code == 200
            assert resolver.requests == [
                {
                    "profileUrl": "https://www.xiaohongshu.com/user/profile/shared-link",
                    "platform": "",
                    "accountId": "",
                }
            ]
            assert response.json() == {
                "name": "解析到的博主",
                "platform": "小红书",
                "profileUrl": "https://www.xiaohongshu.com/user/profile/resolved-peer",
                "avatarUrl": "https://example.test/avatar.png",
                "description": "公开简介",
                "followers": 12345,
                "follows": 88,
                "contentCount": 66,
                "totalLikes": 98765,
                "ipLocation": "上海",
            }
        finally:
            app.dependency_overrides.clear()


def test_user_resolves_similar_account_from_platform_account_id():
    with db_session() as session:
        scheduler = RecordingScheduler()
        resolver = StubSimilarAccountResolver()
        _configure(session, scheduler)
        app.dependency_overrides[get_similar_account_resolver] = lambda: resolver
        try:
            client = TestClient(app)
            headers = _headers(client)
            response = client.post(
                "/api/v1/accounts/acc1/report/similar-accounts/resolve",
                headers=headers,
                json={"platform": "小红书", "accountId": "red-id-001"},
            )

            assert response.status_code == 200
            assert resolver.requests == [
                {
                    "profileUrl": "",
                    "platform": "小红书",
                    "accountId": "red-id-001",
                }
            ]
        finally:
            app.dependency_overrides.clear()


@pytest.mark.parametrize(
    ("path", "section_key", "workflow_type"),
    [
        ("similar-accounts", "similarAccounts", "account_report_similar_accounts"),
        ("compliance-rules", "complianceRules", "account_report_compliance_rules"),
        ("target-user-profile", "targetUserProfile", "account_report_target_user_profile"),
        ("hot-contents", "hotContents", "account_report_hot_contents"),
    ],
)
def test_report_sections_create_independent_workflow_types(path, section_key, workflow_type):
    with db_session() as session:
        scheduler = RecordingScheduler()
        _configure(session, scheduler)
        try:
            client = TestClient(app)
            headers = _headers(client)

            response = client.post(
                f"/api/v1/accounts/acc1/report/{path}/workflows",
                headers=headers,
                json={"referenceComments": True},
            )

            assert response.status_code == 200
            assert response.json()["type"] == workflow_type
            assert response.json()["inputPayload"]["sectionKey"] == section_key
            assert response.json()["inputPayload"]["referenceComments"] is True
            assert scheduler.submissions == [(workflow_type, response.json()["id"])]
        finally:
            app.dependency_overrides.clear()


def test_different_report_sections_run_concurrently_while_full_report_stays_exclusive():
    with db_session() as session:
        scheduler = RecordingScheduler()
        _configure(session, scheduler)
        try:
            client = TestClient(app)
            headers = _headers(client)

            hot_contents = client.post(
                "/api/v1/accounts/acc1/report/hot-contents/workflows",
                headers=headers,
            ).json()
            similar_accounts = client.post(
                "/api/v1/accounts/acc1/report/similar-accounts/workflows",
                headers=headers,
            ).json()
            duplicate_similar_accounts = client.post(
                "/api/v1/accounts/acc1/report/similar-accounts/workflows",
                headers=headers,
            ).json()
            full = client.post(
                "/api/v1/accounts/acc1/report/workflows",
                headers=headers,
            ).json()

            assert similar_accounts["id"] != hot_contents["id"]
            assert duplicate_similar_accounts["id"] == similar_accounts["id"]
            assert full["id"] in {hot_contents["id"], similar_accounts["id"]}
            assert scheduler.submissions == [
                ("account_report_hot_contents", hot_contents["id"]),
                ("account_report_similar_accounts", similar_accounts["id"]),
            ]

            active = client.get(
                "/api/v1/accounts/acc1/report/workflows/active",
                headers=headers,
            )
            assert active.status_code == 200
            assert {item["id"] for item in active.json()} == {
                hot_contents["id"],
                similar_accounts["id"],
            }
        finally:
            app.dependency_overrides.clear()


def test_completed_report_workflow_allows_a_new_refresh_and_scoped_lookup():
    with db_session() as session:
        scheduler = RecordingScheduler()
        _configure(session, scheduler)
        try:
            client = TestClient(app)
            headers = _headers(client)
            first = client.post("/api/v1/accounts/acc1/report/workflows", headers=headers).json()
            record = session.get(WorkflowRecord, first["id"])
            record.status = "completed"
            record.progress = 100
            record.current_stage = "completed"
            session.commit()

            second = client.post("/api/v1/accounts/acc1/report/workflows", headers=headers)
            own = client.get(f"/api/v1/accounts/acc1/report/workflows/{second.json()['id']}", headers=headers)
            wrong_account = client.get(f"/api/v1/accounts/acc2/report/workflows/{second.json()['id']}", headers=headers)

            assert second.status_code == 200
            assert second.json()["id"] != first["id"]
            assert own.status_code == 200
            assert wrong_account.status_code == 404
            assert scheduler.submissions == [
                ("account_report", first["id"]),
                ("account_report", second.json()["id"]),
            ]
        finally:
            app.dependency_overrides.clear()


def test_latest_missing_and_account_authorization_return_404():
    with db_session() as session:
        scheduler = RecordingScheduler()
        _configure(session, scheduler)
        try:
            client = TestClient(app)
            headers = _headers(client)

            missing = client.get("/api/v1/accounts/acc1/report/workflows/latest", headers=headers)
            unknown_account = client.post("/api/v1/accounts/not-owned/report/workflows", headers=headers)

            assert missing.status_code == 404
            assert unknown_account.status_code == 404

            created = client.post("/api/v1/accounts/acc1/report/workflows", headers=headers).json()
            service = WorkflowService(session)
            with pytest.raises(StopIteration):
                service.get_account_report_job("another-user", "acc1", created["id"])

            unauthorized = client.get(f"/api/v1/accounts/acc1/report/workflows/{created['id']}")
            assert unauthorized.status_code == 401
        finally:
            app.dependency_overrides.clear()


def test_manual_submit_failure_marks_workflow_failed_and_returns_500(caplog: pytest.LogCaptureFixture):
    with db_session() as session:
        scheduler = RecordingScheduler(
            RuntimeError(
                "scheduler submit failed Cookie=session-secret xsec_token=secret "
                "https://example.test/profile?token=query-secret"
            )
        )
        _configure(session, scheduler)
        try:
            client = TestClient(app, raise_server_exceptions=False)
            headers = _headers(client)

            response = client.post("/api/v1/accounts/acc1/report/workflows", headers=headers)
            record = session.query(WorkflowRecord).filter(WorkflowRecord.type == "account_report").one()

            assert response.status_code == 500
            assert record.status == "failed"
            assert record.current_stage == "failed"
            assert record.error == "账号报告任务提交失败，请稍后重试"
            assert response.json()["detail"] == "账号报告任务提交失败，请稍后重试"
            failure_text = f"{record.error} {response.text}".lower()
            assert "cookie" not in failure_text
            assert "token" not in failure_text
            assert "secret" not in failure_text
            assert "?" not in failure_text
            log_text = caplog.text.lower()
            assert "cookie" not in log_text
            assert "xsec_token" not in log_text
            assert "query-secret" not in log_text
        finally:
            app.dependency_overrides.clear()


def test_automatic_submit_failure_keeps_created_account_and_marks_workflow_failed():
    with db_session() as session:
        scheduler = RecordingScheduler(
            RuntimeError(
                "scheduler unavailable Cookie=session-secret xsec_token=secret "
                "https://example.test/profile?token=query-secret"
            )
        )
        _configure(session, scheduler)
        try:
            client = TestClient(app)
            headers = _headers(client)

            created = client.post("/api/v1/accounts", headers=headers, json=_account_payload())
            account_id = created.json()["id"]
            latest = client.get(f"/api/v1/accounts/{account_id}/report/workflows/latest", headers=headers)

            assert created.status_code == 200
            assert latest.status_code == 200
            assert latest.json()["status"] == "failed"
            assert latest.json()["currentStage"] == "failed"
            assert latest.json()["error"] == "账号报告任务提交失败，请稍后重试"
            failure_text = latest.text.lower()
            assert "cookie" not in failure_text
            assert "token" not in failure_text
            assert "secret" not in failure_text
            assert "?" not in failure_text
        finally:
            app.dependency_overrides.clear()


def test_create_account_report_job_rolls_back_when_commit_fails(monkeypatch: pytest.MonkeyPatch):
    with db_session() as session:
        service = WorkflowService(session)
        original_rollback = session.rollback
        rollback_calls: list[bool] = []

        def fail_commit() -> None:
            raise RuntimeError("commit failed")

        def track_rollback() -> None:
            rollback_calls.append(True)
            original_rollback()

        monkeypatch.setattr(session, "commit", fail_commit)
        monkeypatch.setattr(session, "rollback", track_rollback)

        with pytest.raises(RuntimeError, match="commit failed"):
            service.create_account_report_job("u_001", "acc1")

        assert rollback_calls == [True]


def test_mark_account_report_job_failed_rolls_back_when_commit_fails(monkeypatch: pytest.MonkeyPatch):
    with db_session() as session:
        service = WorkflowService(session)
        workflow, _ = service.create_account_report_job("u_001", "acc1")
        original_rollback = session.rollback
        rollback_calls: list[bool] = []

        def fail_commit() -> None:
            raise RuntimeError("commit failed")

        def track_rollback() -> None:
            rollback_calls.append(True)
            original_rollback()

        monkeypatch.setattr(session, "commit", fail_commit)
        monkeypatch.setattr(session, "rollback", track_rollback)

        with pytest.raises(RuntimeError, match="commit failed"):
            service.mark_account_report_job_failed("u_001", "acc1", workflow.id, "safe error")

        assert rollback_calls == [True]
        assert session.get(WorkflowRecord, workflow.id).status == "pending"
