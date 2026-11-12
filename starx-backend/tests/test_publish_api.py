from concurrent.futures import ThreadPoolExecutor
import json
from threading import Event, Lock

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import UniqueConstraint, create_engine, delete
from sqlalchemy.orm import sessionmaker

from app.api.deps import get_autophone_service, get_service
from app.db.base import Base
from app.db.init_db import init_database
from app.db.models import ContentCreationRecord, TaskRecord
from app.main import app
from app.services.autophone_service import (
    AutophoneConflictError,
    AutophonePublishRequest,
    AutophoneRequestError,
    AutophoneService,
)
from app.services.db_service import DBService
from tests.db_test_utils import db_session


def _auth_headers(client: TestClient) -> dict[str, str]:
    login = client.post("/api/v1/auth/login", json={"email": "demo@starx.ai", "password": "demo123"})
    return {"Authorization": f"Bearer {login.json()['accessToken']}"}


def _persist_creation(
    client: TestClient,
    headers: dict[str, str],
    account_id: str,
    target_platform: str = "小红书",
    task_status: str = "pending_review",
) -> str:
    topic_id = client.get(f"/api/v1/accounts/{account_id}/topics", headers=headers).json()[0]["id"]
    creation = client.post(
        f"/api/v1/accounts/{account_id}/creations/generate",
        json={"topicId": topic_id, "targetPlatform": target_platform},
        headers=headers,
    ).json()
    submitted = client.post(
        f"/api/v1/accounts/{account_id}/creations/{creation['creationId']}/submit-task",
        json={
            "topicId": topic_id,
            "targetPlatform": target_platform,
            "type": creation["type"],
            "content": creation["content"],
            "status": task_status,
        },
        headers=headers,
    )
    assert submitted.status_code == 200
    return creation["creationId"]


def _task_id_for_creation(client: TestClient, headers: dict[str, str], account_id: str, creation_id: str) -> str:
    tasks = client.get(f"/api/v1/accounts/{account_id}/tasks", headers=headers).json()
    return next(task["id"] for task in tasks if task.get("creationId") == creation_id)


class FakeAutophoneService:
    def __init__(self, *, publish_status: str = "queued", queried_status: str = "succeeded") -> None:
        self.requests: list[AutophonePublishRequest] = []
        self.status_requests: list[str] = []
        self.publish_status = publish_status
        self.queried_status = queried_status

    def publish(self, request: AutophonePublishRequest) -> dict[str, object]:
        self.requests.append(request)
        return {
            "external_id": request.external_id,
            "platform": request.platform,
            "status": self.publish_status,
            "android_id": request.android_id,
            "material_id": "mat_test",
            "publish_job_id": "pub_test",
            "task_id": "publish-pub_test",
            "error_message": None,
            "created_at": "2026-07-06 10:20:00",
            "triggered_at": "2026-07-06 10:20:00",
            "started_at": None,
            "finished_at": None,
        }

    def get_publish_status(self, external_id: str) -> dict[str, object]:
        self.status_requests.append(external_id)
        return {
            "external_id": external_id,
            "platform": "douyin",
            "status": self.queried_status,
            "android_id": "android-douyin",
            "material_id": "mat_test",
            "publish_job_id": "pub_test",
            "task_id": "publish-pub_test",
            "error_message": None,
            "created_at": "2026-07-06 10:20:00",
            "triggered_at": "2026-07-06 10:20:00",
            "started_at": "2026-07-06 10:20:05",
            "finished_at": "2026-07-06 10:21:00",
        }


class RacingAutophoneService(FakeAutophoneService):
    def __init__(self) -> None:
        super().__init__()
        self.stale_status_started = Event()
        self.release_stale_status = Event()
        self._status_lock = Lock()
        self._status_call_count = 0

    def get_publish_status(self, external_id: str) -> dict[str, object]:
        with self._status_lock:
            self._status_call_count += 1
            call_number = self._status_call_count
        self.status_requests.append(external_id)
        if call_number == 2:
            self.stale_status_started.set()
            assert self.release_stale_status.wait(timeout=5)
        return {
            "external_id": external_id,
            "platform": "douyin",
            "status": "failed",
            "android_id": "android-douyin",
            "material_id": "mat_test",
            "publish_job_id": "pub_test",
            "task_id": "publish-pub_test",
            "error_message": "device failed",
            "created_at": "2026-07-06 10:20:00",
            "triggered_at": "2026-07-06 10:20:00",
            "started_at": "2026-07-06 10:20:05",
            "finished_at": "2026-07-06 10:20:10",
        }


class ConflictThenRecoverAutophoneService(FakeAutophoneService):
    def __init__(self) -> None:
        super().__init__(queried_status="queued")

    def publish(self, request: AutophonePublishRequest) -> dict[str, object]:
        self.requests.append(request)
        raise AutophoneConflictError("external publish already exists")


class FailOnceAutophoneService(FakeAutophoneService):
    def __init__(self) -> None:
        super().__init__()
        self.should_fail = True

    def publish(self, request: AutophonePublishRequest) -> dict[str, object]:
        if self.should_fail:
            self.requests.append(request)
            raise AutophoneRequestError("autophone is temporarily unavailable")
        return super().publish(request)


class UnrecoverableConflictAutophoneService(FakeAutophoneService):
    def __init__(self) -> None:
        super().__init__()
        self.should_conflict = True
        self.status_unavailable = True

    def publish(self, request: AutophonePublishRequest) -> dict[str, object]:
        if self.should_conflict:
            self.requests.append(request)
            raise AutophoneConflictError("external publish already exists")
        return super().publish(request)

    def get_publish_status(self, external_id: str) -> dict[str, object]:
        if self.status_unavailable:
            self.status_requests.append(external_id)
            raise AutophoneRequestError("external publish status is unavailable")
        return super().get_publish_status(external_id)


class BlockingAutophoneService(FakeAutophoneService):
    def __init__(self) -> None:
        super().__init__()
        self.publish_started = Event()
        self.release_publish = Event()

    def publish(self, request: AutophonePublishRequest) -> dict[str, object]:
        self.requests.append(request)
        self.publish_started.set()
        assert self.release_publish.wait(timeout=5)
        return {
            "external_id": request.external_id,
            "platform": request.platform,
            "status": self.publish_status,
            "android_id": request.android_id,
            "material_id": "mat_test",
            "publish_job_id": "pub_test",
            "task_id": "publish-pub_test",
            "error_message": None,
            "created_at": "2026-07-06 10:20:00",
            "triggered_at": "2026-07-06 10:20:00",
            "started_at": None,
            "finished_at": None,
        }

def _create_publish_account(client: TestClient, headers: dict[str, str], *, platform: str = "抖音") -> str:
    platform_code = {"小红书": "xhs", "抖音": "douyin", "快手": "kuaishou"}[platform]
    created = client.post(
        "/api/v1/accounts",
        json={
            "name": f"{platform}发布契约测试号",
            "description": "发布重试契约测试",
            "purpose": "自动发布",
            "type": "专业号",
            "platforms": [platform],
            "accountLinks": {platform: f"https://example.test/{platform_code}"},
            "publishSettings": {platform: {"androidId": f"android-{platform_code}"}},
        },
        headers=headers,
    )
    assert created.status_code == 200
    return created.json()["id"]


def _publish_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "assetList": ["https://cdn.example.test/video.mp4"],
        "description": "发布文案",
    }
    payload.update(overrides)
    return payload


def test_publish_attempt_schema_enforces_atomic_identifiers():
    table = Base.metadata.tables.get("creation_publish_attempts")
    assert table is not None
    unique_columns = {
        tuple(sorted(column.name for column in constraint.columns))
        for constraint in table.constraints
        if isinstance(constraint, UniqueConstraint)
    }
    assert ("attempt", "creation_id") in unique_columns
    assert ("external_id",) in unique_columns


def test_legacy_publish_state_does_not_duplicate_current_history_entry():
    with db_session() as session:
        app.dependency_overrides[get_service] = lambda: DBService(session)
        try:
            client = TestClient(app)
            headers = _auth_headers(client)
            account_id = _create_publish_account(client, headers)
            creation_id = _persist_creation(client, headers, account_id, "抖音")
            external_id = f"starx_{creation_id}_douyin"
            queued = {
                "externalId": external_id,
                "platform": "douyin",
                "status": "queued",
                "attempt": 1,
                "recordedAt": "2026-07-06T10:20:00+00:00",
            }
            failed = {
                **queued,
                "status": "failed",
                "errorMessage": "device failed",
                "recordedAt": "2026-07-06T10:21:00+00:00",
            }
            creation = session.get(ContentCreationRecord, creation_id)
            assert creation is not None
            creation.creation_state = {
                "publish": dict(failed),
                "publishHistory": [dict(queued), dict(failed)],
            }
            session.commit()

            service = DBService(session)
            service.get_current_creation_publish_state("u_001", account_id, creation_id)
            projected = service.get_creation("u_001", account_id, creation_id)

            assert [event["status"] for event in projected.creationState["publishHistory"]] == [
                "queued",
                "failed",
            ]
        finally:
            app.dependency_overrides.clear()


def test_account_publish_settings_are_optional_and_can_be_configured():
    with db_session() as session:
        app.dependency_overrides[get_service] = lambda: DBService(session)
        try:
            client = TestClient(app)
            headers = _auth_headers(client)

            existing = client.get("/api/v1/accounts", headers=headers)
            assert existing.status_code == 200
            assert existing.json()[0]["publishSettings"] == {}

            created = client.post(
                "/api/v1/accounts",
                json={
                    "name": "发布配置号",
                    "description": "短视频发布测试",
                    "purpose": "自动发布",
                    "type": "专业号",
                    "platforms": ["小红书", "抖音"],
                    "accountLinks": {
                        "小红书": "https://www.xiaohongshu.com/user/profile/publisher",
                        "抖音": "https://www.douyin.com/user/publisher",
                    },
                    "publishSettings": {
                        "抖音": {"androidId": "android-douyin"},
                    },
                },
                headers=headers,
            )

            assert created.status_code == 200
            assert created.json()["publishSettings"] == {
                "抖音": {"androidId": "android-douyin", "platform": "douyin"}
            }
        finally:
            app.dependency_overrides.clear()


def test_publish_creation_requires_account_publish_setting_for_target_platform():
    with db_session() as session:
        app.dependency_overrides[get_service] = lambda: DBService(session)
        app.dependency_overrides[get_autophone_service] = lambda: FakeAutophoneService()
        try:
            client = TestClient(app)
            headers = _auth_headers(client)
            account_id = client.get("/api/v1/accounts", headers=headers).json()[0]["id"]
            creation_id = _persist_creation(client, headers, account_id, "小红书")

            published = client.post(
                f"/api/v1/accounts/{account_id}/creations/{creation_id}/publish",
                json=_publish_payload(),
                headers=headers,
            )

            assert published.status_code == 400
            assert published.json()["detail"] == "publishSettings is required for 小红书"
        finally:
            app.dependency_overrides.clear()


def test_publish_creation_calls_autophone_and_persists_publish_state():
    with db_session() as session:
        fake_autophone = FakeAutophoneService()
        app.dependency_overrides[get_service] = lambda: DBService(session)
        app.dependency_overrides[get_autophone_service] = lambda: fake_autophone
        try:
            client = TestClient(app)
            headers = _auth_headers(client)
            created_account = client.post(
                "/api/v1/accounts",
                json={
                    "name": "抖音发布号",
                    "description": "短视频发布测试",
                    "purpose": "自动发布",
                    "type": "专业号",
                    "platforms": ["抖音"],
                    "accountLinks": {"抖音": "https://www.douyin.com/user/autophone"},
                    "publishSettings": {"抖音": {"androidId": "android-douyin"}},
                },
                headers=headers,
            )
            assert created_account.status_code == 200
            account_id = created_account.json()["id"]
            creation_id = _persist_creation(client, headers, account_id, "抖音")

            published = client.post(
                f"/api/v1/accounts/{account_id}/creations/{creation_id}/publish",
                json={
                    "assetList": ["https://cdn.example.test/video.mp4"],
                    "filename": "video.mp4",
                    "title": "  夏日护肤实测  ",
                    "description": "  发布文案  ",
                    "visibility": "0",
                    "copyToAlbum": False,
                    "sha256": "abc123",
                    "sizeBytes": 123456,
                },
                headers=headers,
            )

            assert published.status_code == 200
            payload = published.json()
            assert payload["status"] == "queued"
            assert payload["attempt"] == 1
            assert payload["publishJobId"] == "pub_test"
            request = fake_autophone.requests[0]
            assert request.external_id == f"starx_{creation_id}_douyin"
            assert request.platform == "douyin"
            assert request.android_id == "android-douyin"
            assert request.asset_list == ["https://cdn.example.test/video.mp4"]
            assert request.filename == "video.mp4"
            assert request.title == "夏日护肤实测"
            assert request.description == "发布文案"
            assert request.visibility == "0"
            assert request.copy_to_album is False
            assert request.sha256 == "abc123"
            assert request.size_bytes == 123456

            persisted = client.get(f"/api/v1/accounts/{account_id}/creations/{creation_id}", headers=headers)
            assert persisted.status_code == 200
            publish_state = persisted.json()["creationState"]["publish"]
            assert publish_state["externalId"] == f"starx_{creation_id}_douyin"
            assert publish_state["status"] == "queued"
            assert publish_state["attempt"] == 1
            assert publish_state["taskId"] == "publish-pub_test"
            publish_history = persisted.json()["creationState"]["publishHistory"]
            assert publish_history[-1]["status"] == "queued"
            assert publish_history[-1]["attempt"] == 1
        finally:
            app.dependency_overrides.clear()


def test_publish_creation_can_override_the_creation_platform():
    with db_session() as session:
        fake_autophone = FakeAutophoneService()
        app.dependency_overrides[get_service] = lambda: DBService(session)
        app.dependency_overrides[get_autophone_service] = lambda: fake_autophone
        try:
            client = TestClient(app)
            headers = _auth_headers(client)
            created_account = client.post(
                "/api/v1/accounts",
                json={
                    "name": "多平台发布号",
                    "description": "发布时切换平台测试",
                    "purpose": "自动发布",
                    "type": "专业号",
                    "platforms": ["小红书", "抖音"],
                    "accountLinks": {
                        "小红书": "https://www.xiaohongshu.com/user/profile/test",
                        "抖音": "https://www.douyin.com/user/test",
                    },
                    "publishSettings": {
                        "小红书": {"androidId": "android-xhs"},
                        "抖音": {"androidId": "android-douyin"},
                    },
                },
                headers=headers,
            )
            assert created_account.status_code == 200
            account_id = created_account.json()["id"]
            creation_id = _persist_creation(client, headers, account_id, "小红书")

            published = client.post(
                f"/api/v1/accounts/{account_id}/creations/{creation_id}/publish",
                json=_publish_payload(targetPlatform="抖音"),
                headers=headers,
            )

            assert published.status_code == 200
            request = fake_autophone.requests[0]
            assert request.platform == "douyin"
            assert request.android_id == "android-douyin"
            assert request.external_id == f"starx_{creation_id}_douyin"
        finally:
            app.dependency_overrides.clear()


def test_publish_conflict_with_recoverable_external_job_returns_recovered_state():
    with db_session() as session:
        fake_autophone = ConflictThenRecoverAutophoneService()
        app.dependency_overrides[get_service] = lambda: DBService(session)
        app.dependency_overrides[get_autophone_service] = lambda: fake_autophone
        try:
            client = TestClient(app)
            headers = _auth_headers(client)
            account_id = _create_publish_account(client, headers)
            creation_id = _persist_creation(client, headers, account_id, "抖音")

            published = client.post(
                f"/api/v1/accounts/{account_id}/creations/{creation_id}/publish",
                json=_publish_payload(),
                headers=headers,
            )

            assert published.status_code == 200
            assert published.json()["status"] == "queued"
            assert published.json()["attempt"] == 1
            external_id = f"starx_{creation_id}_douyin"
            assert fake_autophone.status_requests == [external_id]

            persisted = client.get(
                f"/api/v1/accounts/{account_id}/creations/{creation_id}",
                headers=headers,
            ).json()["creationState"]["publish"]
            assert persisted["externalId"] == external_id
            assert persisted["status"] == "queued"
            assert persisted["attempt"] == 1
        finally:
            app.dependency_overrides.clear()


def test_uncertain_publish_failure_keeps_attempt_pending_until_status_recovery():
    with db_session() as session:
        fake_autophone = FailOnceAutophoneService()
        app.dependency_overrides[get_service] = lambda: DBService(session)
        app.dependency_overrides[get_autophone_service] = lambda: fake_autophone
        try:
            client = TestClient(app)
            headers = _auth_headers(client)
            account_id = _create_publish_account(client, headers)
            creation_id = _persist_creation(client, headers, account_id, "抖音")
            publish_url = f"/api/v1/accounts/{account_id}/creations/{creation_id}/publish"

            failed = client.post(publish_url, json=_publish_payload(), headers=headers)

            assert failed.status_code == 502
            persisted = client.get(
                f"/api/v1/accounts/{account_id}/creations/{creation_id}",
                headers=headers,
            ).json()["creationState"]["publish"]
            assert persisted["status"] == "pending"
            assert persisted["attempt"] == 1
            assert persisted["errorMessage"] is None

            retried = client.post(
                publish_url,
                json=_publish_payload(retry=True),
                headers=headers,
            )

            assert retried.status_code == 409
            recovered = client.get(f"{publish_url}/status", headers=headers)
            assert recovered.status_code == 200
            assert recovered.json()["status"] == "succeeded"
            assert recovered.json()["attempt"] == 1
            external_id = f"starx_{creation_id}_douyin"
            assert [request.external_id for request in fake_autophone.requests] == [external_id]
            assert fake_autophone.status_requests == [external_id]
        finally:
            app.dependency_overrides.clear()


def test_publish_http_transport_error_does_not_leave_reserved_attempt(monkeypatch):
    def failing_post(url, **kwargs):  # noqa: ANN001, ARG001
        raise httpx.ConnectError("connection refused", request=httpx.Request("POST", url))

    monkeypatch.setattr("app.services.autophone_service.httpx.post", failing_post)
    with db_session() as session:
        autophone = AutophoneService(
            base_url="https://auto.example.test",
            client_id="client",
            client_secret="secret",
        )
        app.dependency_overrides[get_service] = lambda: DBService(session)
        app.dependency_overrides[get_autophone_service] = lambda: autophone
        try:
            client = TestClient(app)
            headers = _auth_headers(client)
            account_id = _create_publish_account(client, headers)
            creation_id = _persist_creation(client, headers, account_id, "抖音")

            published = client.post(
                f"/api/v1/accounts/{account_id}/creations/{creation_id}/publish",
                json=_publish_payload(),
                headers=headers,
            )

            assert published.status_code == 502
            persisted = client.get(
                f"/api/v1/accounts/{account_id}/creations/{creation_id}",
                headers=headers,
            ).json()["creationState"]["publish"]
            assert persisted["status"] == "failed"
            assert persisted["attempt"] == 1
            assert "connection refused" in persisted["errorMessage"]
        finally:
            app.dependency_overrides.clear()


def test_publish_http_5xx_keeps_attempt_pending_and_non_retryable(monkeypatch):
    publish_requests: list[str] = []

    class UnavailableResponse:
        status_code = 503

        def json(self):
            return {"detail": "autophone is temporarily unavailable"}

    def unavailable_post(url, **kwargs):  # noqa: ANN001, ARG001
        publish_requests.append(url)
        return UnavailableResponse()

    monkeypatch.setattr("app.services.autophone_service.httpx.post", unavailable_post)
    with db_session() as session:
        autophone = AutophoneService(
            base_url="https://auto.example.test",
            client_id="client",
            client_secret="secret",
        )
        app.dependency_overrides[get_service] = lambda: DBService(session)
        app.dependency_overrides[get_autophone_service] = lambda: autophone
        try:
            client = TestClient(app)
            headers = _auth_headers(client)
            account_id = _create_publish_account(client, headers)
            creation_id = _persist_creation(client, headers, account_id, "抖音")
            publish_url = f"/api/v1/accounts/{account_id}/creations/{creation_id}/publish"

            published = client.post(publish_url, json=_publish_payload(), headers=headers)

            assert published.status_code == 502
            persisted = client.get(
                f"/api/v1/accounts/{account_id}/creations/{creation_id}",
                headers=headers,
            ).json()["creationState"]["publish"]
            assert persisted["status"] == "pending"
            assert persisted["attempt"] == 1
            assert persisted["errorMessage"] is None

            retried = client.post(
                publish_url,
                json=_publish_payload(retry=True),
                headers=headers,
            )

            assert retried.status_code == 409
            assert len(publish_requests) == 1
        finally:
            app.dependency_overrides.clear()


def test_publish_mismatched_2xx_stays_pending_until_same_id_status_recovers(
    monkeypatch,
):
    expected_external_ids: list[str] = []

    class SuccessfulResponse:
        status_code = 200

        def __init__(self, data: dict[str, object]) -> None:
            self.data = data

        def json(self):
            return {"success": True, "data": self.data}

    def mismatched_post(url, *, content, **kwargs):  # noqa: ANN001, ARG001
        external_id = str(json.loads(content)["external_id"])
        expected_external_ids.append(external_id)
        return SuccessfulResponse(
            {
                "external_id": "another-publish",
                "platform": "douyin",
                "status": "queued",
                "android_id": "android-douyin",
            }
        )

    def recovered_get(url, **kwargs):  # noqa: ANN001, ARG001
        return SuccessfulResponse(
            {
                "external_id": expected_external_ids[-1],
                "platform": "douyin",
                "status": "succeeded",
                "android_id": "android-douyin",
            }
        )

    monkeypatch.setattr("app.services.autophone_service.httpx.post", mismatched_post)
    monkeypatch.setattr("app.services.autophone_service.httpx.get", recovered_get)
    with db_session() as session:
        autophone = AutophoneService(
            base_url="https://auto.example.test",
            client_id="client",
            client_secret="secret",
        )
        app.dependency_overrides[get_service] = lambda: DBService(session)
        app.dependency_overrides[get_autophone_service] = lambda: autophone
        try:
            client = TestClient(app)
            headers = _auth_headers(client)
            account_id = _create_publish_account(client, headers)
            creation_id = _persist_creation(client, headers, account_id, "抖音")
            publish_url = f"/api/v1/accounts/{account_id}/creations/{creation_id}/publish"

            published = client.post(publish_url, json=_publish_payload(), headers=headers)

            assert published.status_code == 502
            persisted = client.get(
                f"/api/v1/accounts/{account_id}/creations/{creation_id}",
                headers=headers,
            ).json()["creationState"]["publish"]
            assert persisted["externalId"] == f"starx_{creation_id}_douyin"
            assert persisted["status"] == "pending"
            assert persisted["attempt"] == 1
            assert persisted["errorMessage"] is None

            retry = client.post(
                publish_url,
                json=_publish_payload(retry=True),
                headers=headers,
            )
            assert retry.status_code == 409

            recovered = client.get(f"{publish_url}/status", headers=headers)
            assert recovered.status_code == 200
            assert recovered.json()["externalId"] == f"starx_{creation_id}_douyin"
            assert recovered.json()["status"] == "succeeded"
            assert recovered.json()["attempt"] == 1
            assert len(expected_external_ids) == 1
        finally:
            app.dependency_overrides.clear()


def test_get_status_mismatched_2xx_does_not_overwrite_current_attempt(monkeypatch):
    expected_external_ids: list[str] = []
    status_call_count = 0

    class SuccessfulResponse:
        status_code = 200

        def __init__(self, data: dict[str, object]) -> None:
            self.data = data

        def json(self):
            return {"success": True, "data": self.data}

    def accepted_post(url, *, content, **kwargs):  # noqa: ANN001, ARG001
        external_id = str(json.loads(content)["external_id"])
        expected_external_ids.append(external_id)
        return SuccessfulResponse(
            {
                "external_id": external_id,
                "platform": "douyin",
                "status": "queued",
                "android_id": "android-douyin",
            }
        )

    def queried_get(url, **kwargs):  # noqa: ANN001, ARG001
        nonlocal status_call_count
        status_call_count += 1
        external_id = (
            "another-publish" if status_call_count == 1 else expected_external_ids[-1]
        )
        return SuccessfulResponse(
            {
                "external_id": external_id,
                "platform": "douyin",
                "status": "succeeded",
                "android_id": "android-douyin",
            }
        )

    monkeypatch.setattr("app.services.autophone_service.httpx.post", accepted_post)
    monkeypatch.setattr("app.services.autophone_service.httpx.get", queried_get)
    with db_session() as session:
        autophone = AutophoneService(
            base_url="https://auto.example.test",
            client_id="client",
            client_secret="secret",
        )
        app.dependency_overrides[get_service] = lambda: DBService(session)
        app.dependency_overrides[get_autophone_service] = lambda: autophone
        try:
            client = TestClient(app)
            headers = _auth_headers(client)
            account_id = _create_publish_account(client, headers)
            creation_id = _persist_creation(client, headers, account_id, "抖音")
            publish_url = f"/api/v1/accounts/{account_id}/creations/{creation_id}/publish"
            assert client.post(
                publish_url,
                json=_publish_payload(),
                headers=headers,
            ).status_code == 200

            mismatched = client.get(f"{publish_url}/status", headers=headers)

            assert mismatched.status_code == 502
            persisted = client.get(
                f"/api/v1/accounts/{account_id}/creations/{creation_id}",
                headers=headers,
            ).json()["creationState"]["publish"]
            assert persisted["externalId"] == f"starx_{creation_id}_douyin"
            assert persisted["status"] == "queued"
            assert persisted["attempt"] == 1
            retry = client.post(
                publish_url,
                json=_publish_payload(retry=True),
                headers=headers,
            )
            assert retry.status_code == 409

            recovered = client.get(f"{publish_url}/status", headers=headers)
            assert recovered.status_code == 200
            assert recovered.json()["status"] == "succeeded"
            assert recovered.json()["attempt"] == 1
            assert status_call_count == 2
        finally:
            app.dependency_overrides.clear()


def test_publish_conflict_with_unavailable_status_stays_pending_until_get_recovers():
    with db_session() as session:
        fake_autophone = UnrecoverableConflictAutophoneService()
        app.dependency_overrides[get_service] = lambda: DBService(session)
        app.dependency_overrides[get_autophone_service] = lambda: fake_autophone
        try:
            client = TestClient(app)
            headers = _auth_headers(client)
            account_id = _create_publish_account(client, headers)
            creation_id = _persist_creation(client, headers, account_id, "抖音")
            publish_url = f"/api/v1/accounts/{account_id}/creations/{creation_id}/publish"

            conflicted = client.post(publish_url, json=_publish_payload(), headers=headers)

            assert conflicted.status_code == 409
            persisted = client.get(
                f"/api/v1/accounts/{account_id}/creations/{creation_id}",
                headers=headers,
            ).json()["creationState"]["publish"]
            assert persisted["status"] == "pending"
            assert persisted["attempt"] == 1
            assert persisted["errorMessage"] is None

            retried = client.post(
                publish_url,
                json=_publish_payload(retry=True),
                headers=headers,
            )

            assert retried.status_code == 409
            fake_autophone.status_unavailable = False
            recovered = client.get(f"{publish_url}/status", headers=headers)
            assert recovered.status_code == 200
            assert recovered.json()["status"] == "succeeded"
            assert recovered.json()["attempt"] == 1
            assert len(fake_autophone.requests) == 1
        finally:
            app.dependency_overrides.clear()


def test_publish_creation_only_requires_selected_target_platform_publish_setting():
    with db_session() as session:
        fake_autophone = FakeAutophoneService()
        app.dependency_overrides[get_service] = lambda: DBService(session)
        app.dependency_overrides[get_autophone_service] = lambda: fake_autophone
        try:
            client = TestClient(app)
            headers = _auth_headers(client)
            created_account = client.post(
                "/api/v1/accounts",
                json={
                    "name": "多平台发布号",
                    "description": "只配置当前发布平台",
                    "purpose": "自动发布",
                    "type": "专业号",
                    "platforms": ["小红书", "抖音"],
                    "accountLinks": {
                        "小红书": "https://www.xiaohongshu.com/user/profile/autophone",
                        "抖音": "https://www.douyin.com/user/autophone",
                    },
                    "publishSettings": {"抖音": {"androidId": "android-douyin"}},
                },
                headers=headers,
            )
            assert created_account.status_code == 200
            account_id = created_account.json()["id"]
            creation_id = _persist_creation(client, headers, account_id, "抖音")

            published = client.post(
                f"/api/v1/accounts/{account_id}/creations/{creation_id}/publish",
                json=_publish_payload(),
                headers=headers,
            )

            assert published.status_code == 200
            assert fake_autophone.requests[0].platform == "douyin"
            assert fake_autophone.requests[0].android_id == "android-douyin"
        finally:
            app.dependency_overrides.clear()


def test_get_publish_status_calls_autophone_and_persists_latest_status_history():
    with db_session() as session:
        fake_autophone = FakeAutophoneService()
        app.dependency_overrides[get_service] = lambda: DBService(session)
        app.dependency_overrides[get_autophone_service] = lambda: fake_autophone
        try:
            client = TestClient(app)
            headers = _auth_headers(client)
            created_account = client.post(
                "/api/v1/accounts",
                json={
                    "name": "抖音状态号",
                    "description": "查询发布状态",
                    "purpose": "自动发布",
                    "type": "专业号",
                    "platforms": ["抖音"],
                    "accountLinks": {"抖音": "https://www.douyin.com/user/status"},
                    "publishSettings": {"抖音": {"androidId": "android-douyin"}},
                },
                headers=headers,
            )
            assert created_account.status_code == 200
            account_id = created_account.json()["id"]
            creation_id = _persist_creation(client, headers, account_id, "抖音")
            published = client.post(
                f"/api/v1/accounts/{account_id}/creations/{creation_id}/publish",
                json=_publish_payload(),
                headers=headers,
            )
            assert published.status_code == 200

            status_response = client.get(
                f"/api/v1/accounts/{account_id}/creations/{creation_id}/publish/status",
                headers=headers,
            )

            assert status_response.status_code == 200
            assert status_response.json()["status"] == "succeeded"
            assert status_response.json()["attempt"] == 1
            assert fake_autophone.status_requests == [f"starx_{creation_id}_douyin"]

            persisted = client.get(f"/api/v1/accounts/{account_id}/creations/{creation_id}", headers=headers)
            publish_state = persisted.json()["creationState"]["publish"]
            publish_history = persisted.json()["creationState"]["publishHistory"]
            assert publish_state["status"] == "succeeded"
            assert [item["status"] for item in publish_history[-2:]] == ["queued", "succeeded"]
            assert [item["attempt"] for item in publish_history[-2:]] == [1, 1]
        finally:
            app.dependency_overrides.clear()


def test_publish_creation_accepts_pending_review():
    with db_session() as session:
        fake_autophone = FakeAutophoneService()
        app.dependency_overrides[get_service] = lambda: DBService(session)
        app.dependency_overrides[get_autophone_service] = lambda: fake_autophone
        try:
            client = TestClient(app)
            headers = _auth_headers(client)
            account_id = _create_publish_account(client, headers)
            creation_id = _persist_creation(client, headers, account_id, "抖音", "pending_review")

            published = client.post(
                f"/api/v1/accounts/{account_id}/creations/{creation_id}/publish",
                json=_publish_payload(),
                headers=headers,
            )

            assert published.status_code == 200
            assert len(fake_autophone.requests) == 1
        finally:
            app.dependency_overrides.clear()


@pytest.mark.parametrize("task_status", ["pending", "pending_publish"])
def test_publish_creation_rejects_legacy_pending_aliases(task_status: str):
    with db_session() as session:
        fake_autophone = FakeAutophoneService()
        app.dependency_overrides[get_service] = lambda: DBService(session)
        app.dependency_overrides[get_autophone_service] = lambda: fake_autophone
        try:
            client = TestClient(app)
            headers = _auth_headers(client)
            account_id = _create_publish_account(client, headers)
            creation_id = _persist_creation(client, headers, account_id, "抖音", task_status)

            published = client.post(
                f"/api/v1/accounts/{account_id}/creations/{creation_id}/publish",
                json=_publish_payload(),
                headers=headers,
            )

            assert published.status_code == 409
            assert published.json()["detail"] == (
                "workflow task must be pending_review before publishing"
            )
            assert fake_autophone.requests == []
        finally:
            app.dependency_overrides.clear()


def test_publish_creation_rejects_draft_workflow_task():
    with db_session() as session:
        fake_autophone = FakeAutophoneService()
        app.dependency_overrides[get_service] = lambda: DBService(session)
        app.dependency_overrides[get_autophone_service] = lambda: fake_autophone
        try:
            client = TestClient(app)
            headers = _auth_headers(client)
            account_id = _create_publish_account(client, headers)
            creation_id = _persist_creation(client, headers, account_id, "抖音", "draft")

            published = client.post(
                f"/api/v1/accounts/{account_id}/creations/{creation_id}/publish",
                json=_publish_payload(),
                headers=headers,
            )

            assert published.status_code == 409
            assert published.json()["detail"] == "workflow task must be pending_review before publishing"
            assert fake_autophone.requests == []
        finally:
            app.dependency_overrides.clear()


def test_publish_creation_rejects_creation_without_associated_workflow_task():
    with db_session() as session:
        fake_autophone = FakeAutophoneService()
        app.dependency_overrides[get_service] = lambda: DBService(session)
        app.dependency_overrides[get_autophone_service] = lambda: fake_autophone
        try:
            client = TestClient(app)
            headers = _auth_headers(client)
            account_id = _create_publish_account(client, headers)
            creation_id = _persist_creation(client, headers, account_id, "抖音")
            session.execute(delete(TaskRecord).where(TaskRecord.account_id == account_id, TaskRecord.creation_id == creation_id))
            session.commit()

            published = client.post(
                f"/api/v1/accounts/{account_id}/creations/{creation_id}/publish",
                json=_publish_payload(),
                headers=headers,
            )

            assert published.status_code == 409
            assert published.json()["detail"] == "workflow task not found for creation"
            assert fake_autophone.requests == []
        finally:
            app.dependency_overrides.clear()


def test_create_task_rejects_duplicate_creation_binding():
    with db_session() as session:
        app.dependency_overrides[get_service] = lambda: DBService(session)
        try:
            client = TestClient(app)
            headers = _auth_headers(client)
            account_id = _create_publish_account(client, headers)
            creation_id = _persist_creation(client, headers, account_id, "抖音")

            duplicate = client.post(
                f"/api/v1/accounts/{account_id}/tasks",
                json={
                    "title": "重复流程任务",
                    "type": "video",
                    "targetPlatform": "抖音",
                    "creationId": creation_id,
                },
                headers=headers,
            )

            assert duplicate.status_code == 409
        finally:
            app.dependency_overrides.clear()


def test_duplicate_task_creates_an_independent_creation_copy():
    with db_session() as session:
        app.dependency_overrides[get_service] = lambda: DBService(session)
        try:
            client = TestClient(app)
            headers = _auth_headers(client)
            account_id = _create_publish_account(client, headers)
            creation_id = _persist_creation(client, headers, account_id, "抖音")
            source = client.get(
                f"/api/v1/accounts/{account_id}/tasks",
                headers=headers,
            ).json()[0]

            response = client.post(
                f"/api/v1/accounts/{account_id}/tasks/{source['id']}/duplicate",
                headers=headers,
            )

            assert response.status_code == 200
            duplicate = response.json()
            assert duplicate["id"] != source["id"]
            assert duplicate["creationId"] != creation_id
            assert duplicate["title"] == source["title"]
            assert duplicate["status"] == source["status"]
            copied_creation = client.get(
                f"/api/v1/accounts/{account_id}/creations/{duplicate['creationId']}",
                headers=headers,
            )
            assert copied_creation.status_code == 200
        finally:
            app.dependency_overrides.clear()


def test_create_task_rejects_creation_from_another_account():
    with db_session() as session:
        app.dependency_overrides[get_service] = lambda: DBService(session)
        try:
            client = TestClient(app)
            headers = _auth_headers(client)
            source_account_id = _create_publish_account(client, headers)
            target_account_id = _create_publish_account(client, headers, platform="快手")
            creation_id = _persist_creation(client, headers, source_account_id, "抖音")

            cross_account = client.post(
                f"/api/v1/accounts/{target_account_id}/tasks",
                json={
                    "title": "跨账号流程任务",
                    "type": "video",
                    "targetPlatform": "快手",
                    "creationId": creation_id,
                },
                headers=headers,
            )

            assert cross_account.status_code == 404
        finally:
            app.dependency_overrides.clear()


def test_publish_creation_rejects_invalid_visibility_before_dispatch():
    with db_session() as session:
        fake_autophone = FakeAutophoneService()
        app.dependency_overrides[get_service] = lambda: DBService(session)
        app.dependency_overrides[get_autophone_service] = lambda: fake_autophone
        try:
            client = TestClient(app)
            headers = _auth_headers(client)
            account_id = _create_publish_account(client, headers)
            creation_id = _persist_creation(client, headers, account_id, "抖音")

            published = client.post(
                f"/api/v1/accounts/{account_id}/creations/{creation_id}/publish",
                json=_publish_payload(visibility="3"),
                headers=headers,
            )

            assert published.status_code == 422
            assert fake_autophone.requests == []
        finally:
            app.dependency_overrides.clear()


def test_publish_creation_rejects_blank_description_before_dispatch():
    with db_session() as session:
        fake_autophone = FakeAutophoneService()
        app.dependency_overrides[get_service] = lambda: DBService(session)
        app.dependency_overrides[get_autophone_service] = lambda: fake_autophone
        try:
            client = TestClient(app)
            headers = _auth_headers(client)
            account_id = _create_publish_account(client, headers)
            creation_id = _persist_creation(client, headers, account_id, "抖音")

            published = client.post(
                f"/api/v1/accounts/{account_id}/creations/{creation_id}/publish",
                json=_publish_payload(description="  \n  "),
                headers=headers,
            )

            assert published.status_code == 422
            assert fake_autophone.requests == []
        finally:
            app.dependency_overrides.clear()


def test_publish_creation_rejects_missing_description_before_dispatch():
    with db_session() as session:
        fake_autophone = FakeAutophoneService()
        app.dependency_overrides[get_service] = lambda: DBService(session)
        app.dependency_overrides[get_autophone_service] = lambda: fake_autophone
        try:
            client = TestClient(app)
            headers = _auth_headers(client)
            account_id = _create_publish_account(client, headers)
            creation_id = _persist_creation(client, headers, account_id, "抖音")

            published = client.post(
                f"/api/v1/accounts/{account_id}/creations/{creation_id}/publish",
                json={"assetList": ["https://cdn.example.test/video.mp4"]},
                headers=headers,
            )

            assert published.status_code == 422
            assert fake_autophone.requests == []
        finally:
            app.dependency_overrides.clear()


def test_publish_creation_rejects_ordinary_duplicate_post():
    with db_session() as session:
        fake_autophone = FakeAutophoneService()
        app.dependency_overrides[get_service] = lambda: DBService(session)
        app.dependency_overrides[get_autophone_service] = lambda: fake_autophone
        try:
            client = TestClient(app)
            headers = _auth_headers(client)
            account_id = _create_publish_account(client, headers)
            creation_id = _persist_creation(client, headers, account_id, "抖音")
            url = f"/api/v1/accounts/{account_id}/creations/{creation_id}/publish"
            payload = _publish_payload()

            first = client.post(url, json=payload, headers=headers)
            duplicate = client.post(url, json=payload, headers=headers)

            assert first.status_code == 200
            assert duplicate.status_code == 409
            assert duplicate.json()["detail"] == "creation already has a publish attempt"
            assert len(fake_autophone.requests) == 1
        finally:
            app.dependency_overrides.clear()


@pytest.mark.parametrize(
    "replacement_state",
    [
        {},
        {
            "publish": {
                "externalId": "forged",
                "platform": "douyin",
                "status": "failed",
                "attempt": 99,
            },
            "publishHistory": [],
        },
    ],
    ids=["empty", "forged"],
)
def test_submit_task_cannot_replace_server_owned_publish_state(replacement_state: dict[str, object]):
    with db_session() as session:
        fake_autophone = FakeAutophoneService()
        app.dependency_overrides[get_service] = lambda: DBService(session)
        app.dependency_overrides[get_autophone_service] = lambda: fake_autophone
        try:
            client = TestClient(app)
            headers = _auth_headers(client)
            account_id = _create_publish_account(client, headers)
            creation_id = _persist_creation(client, headers, account_id, "抖音")
            publish_url = f"/api/v1/accounts/{account_id}/creations/{creation_id}/publish"
            assert client.post(publish_url, json=_publish_payload(), headers=headers).status_code == 200

            creation = client.get(
                f"/api/v1/accounts/{account_id}/creations/{creation_id}",
                headers=headers,
            ).json()
            saved = client.post(
                f"/api/v1/accounts/{account_id}/creations/{creation_id}/submit-task",
                json={
                    "topicId": creation["topicId"],
                    "targetPlatform": creation["targetPlatform"],
                    "type": creation["type"],
                    "content": creation["content"],
                    "creationState": replacement_state,
                    "status": "pending_review",
                },
                headers=headers,
            )
            assert saved.status_code == 200

            persisted = client.get(
                f"/api/v1/accounts/{account_id}/creations/{creation_id}",
                headers=headers,
            ).json()["creationState"]
            assert persisted["publish"]["externalId"] == f"starx_{creation_id}_douyin"
            assert persisted["publish"]["status"] == "queued"
            assert persisted["publish"]["attempt"] == 1
            assert persisted["publishHistory"][-1]["attempt"] == 1

            retry = client.post(
                publish_url,
                json=_publish_payload(retry=True),
                headers=headers,
            )
            assert retry.status_code == 409
            assert len(fake_autophone.requests) == 1
        finally:
            app.dependency_overrides.clear()


def test_publish_creation_retries_failed_attempt_with_incremented_external_id():
    with db_session() as session:
        fake_autophone = FakeAutophoneService(queried_status="failed")
        app.dependency_overrides[get_service] = lambda: DBService(session)
        app.dependency_overrides[get_autophone_service] = lambda: fake_autophone
        try:
            client = TestClient(app)
            headers = _auth_headers(client)
            account_id = _create_publish_account(client, headers)
            creation_id = _persist_creation(client, headers, account_id, "抖音")
            url = f"/api/v1/accounts/{account_id}/creations/{creation_id}/publish"
            payload = _publish_payload()

            first = client.post(url, json=payload, headers=headers)
            failed = client.get(f"{url}/status", headers=headers)
            retried = client.post(url, json={**payload, "retry": True}, headers=headers)

            assert first.status_code == 200
            assert first.json()["attempt"] == 1
            assert failed.status_code == 200
            assert failed.json()["status"] == "failed"
            assert failed.json()["attempt"] == 1
            assert retried.status_code == 200
            assert retried.json()["attempt"] == 2
            assert retried.json()["externalId"] == f"starx_{creation_id}_douyin_attempt_2"
            assert [request.external_id for request in fake_autophone.requests] == [
                f"starx_{creation_id}_douyin",
                f"starx_{creation_id}_douyin_attempt_2",
            ]

            persisted = client.get(f"/api/v1/accounts/{account_id}/creations/{creation_id}", headers=headers).json()
            publish_state = persisted["creationState"]["publish"]
            publish_history = persisted["creationState"]["publishHistory"]
            assert publish_state["attempt"] == 2
            assert publish_state["externalId"] == f"starx_{creation_id}_douyin_attempt_2"
            assert [(item["status"], item["attempt"]) for item in publish_history[-3:]] == [
                ("queued", 1),
                ("failed", 1),
                ("queued", 2),
            ]
        finally:
            app.dependency_overrides.clear()


def test_publish_creation_rejects_retry_while_current_attempt_is_active():
    with db_session() as session:
        fake_autophone = FakeAutophoneService()
        app.dependency_overrides[get_service] = lambda: DBService(session)
        app.dependency_overrides[get_autophone_service] = lambda: fake_autophone
        try:
            client = TestClient(app)
            headers = _auth_headers(client)
            account_id = _create_publish_account(client, headers)
            creation_id = _persist_creation(client, headers, account_id, "抖音")
            url = f"/api/v1/accounts/{account_id}/creations/{creation_id}/publish"
            payload = _publish_payload()
            assert client.post(url, json=payload, headers=headers).status_code == 200

            retried = client.post(url, json={**payload, "retry": True}, headers=headers)

            assert retried.status_code == 409
            assert retried.json()["detail"] == "publish retry requires a failed or cancelled current attempt"
            assert len(fake_autophone.requests) == 1
        finally:
            app.dependency_overrides.clear()


def test_publish_creation_rejects_retry_after_success():
    with db_session() as session:
        fake_autophone = FakeAutophoneService(queried_status="succeeded")
        app.dependency_overrides[get_service] = lambda: DBService(session)
        app.dependency_overrides[get_autophone_service] = lambda: fake_autophone
        try:
            client = TestClient(app)
            headers = _auth_headers(client)
            account_id = _create_publish_account(client, headers)
            creation_id = _persist_creation(client, headers, account_id, "抖音")
            url = f"/api/v1/accounts/{account_id}/creations/{creation_id}/publish"
            payload = _publish_payload()
            assert client.post(url, json=payload, headers=headers).status_code == 200
            assert client.get(f"{url}/status", headers=headers).json()["status"] == "succeeded"

            retried = client.post(url, json={**payload, "retry": True}, headers=headers)

            assert retried.status_code == 409
            assert retried.json()["detail"] == "publish retry requires a failed or cancelled current attempt"
            assert len(fake_autophone.requests) == 1
        finally:
            app.dependency_overrides.clear()


def test_late_status_response_cannot_replace_a_newer_publish_attempt(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'publish-race.db'}",
        connect_args={"check_same_thread": False},
    )
    init_database(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    fake_autophone = RacingAutophoneService()

    def override_service():
        with session_factory() as session:
            yield DBService(session)

    app.dependency_overrides[get_service] = override_service
    app.dependency_overrides[get_autophone_service] = lambda: fake_autophone
    try:
        client = TestClient(app)
        headers = _auth_headers(client)
        account_id = _create_publish_account(client, headers)
        creation_id = _persist_creation(client, headers, account_id, "抖音")
        publish_url = f"/api/v1/accounts/{account_id}/creations/{creation_id}/publish"
        status_url = f"{publish_url}/status"

        first = client.post(publish_url, json=_publish_payload(), headers=headers)
        assert first.status_code == 200
        failed = client.get(status_url, headers=headers)
        assert failed.status_code == 200
        assert failed.json()["status"] == "failed"

        with ThreadPoolExecutor(max_workers=1) as executor:
            stale_future = executor.submit(client.get, status_url, headers=headers)
            assert fake_autophone.stale_status_started.wait(timeout=5)
            try:
                retry = client.post(
                    publish_url,
                    json=_publish_payload(retry=True),
                    headers=headers,
                )
                assert retry.status_code == 200
                assert retry.json()["attempt"] == 2
            finally:
                fake_autophone.release_stale_status.set()
            stale_response = stale_future.result(timeout=5)

        assert stale_response.status_code == 200
        assert stale_response.json()["attempt"] == 2
        assert stale_response.json()["status"] == "queued"
        persisted = client.get(
            f"/api/v1/accounts/{account_id}/creations/{creation_id}",
            headers=headers,
        ).json()["creationState"]["publish"]
        assert persisted["attempt"] == 2
        assert persisted["status"] == "queued"
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_concurrent_publish_requests_reserve_once_before_external_dispatch(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'publish-reservation.db'}",
        connect_args={"check_same_thread": False},
    )
    init_database(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    fake_autophone = BlockingAutophoneService()

    def override_service():
        with session_factory() as session:
            yield DBService(session)

    app.dependency_overrides[get_service] = override_service
    app.dependency_overrides[get_autophone_service] = lambda: fake_autophone
    try:
        client = TestClient(app)
        headers = _auth_headers(client)
        account_id = _create_publish_account(client, headers)
        creation_id = _persist_creation(client, headers, account_id, "抖音")
        publish_url = f"/api/v1/accounts/{account_id}/creations/{creation_id}/publish"

        with ThreadPoolExecutor(max_workers=1) as executor:
            first_future = executor.submit(
                client.post,
                publish_url,
                json=_publish_payload(),
                headers=headers,
            )
            assert fake_autophone.publish_started.wait(timeout=5)
            try:
                duplicate = client.post(
                    publish_url,
                    json=_publish_payload(),
                    headers=headers,
                )
                assert duplicate.status_code == 409
                assert duplicate.json()["detail"] == "creation already has a publish attempt"
                assert len(fake_autophone.requests) == 1
            finally:
                fake_autophone.release_publish.set()
            first = first_future.result(timeout=5)

        assert first.status_code == 200
        assert first.json()["attempt"] == 1
        assert len(fake_autophone.requests) == 1
    finally:
        app.dependency_overrides.clear()
        engine.dispose()
