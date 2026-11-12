from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app.api.deps import get_autophone_service, get_service
from app.db.init_db import init_database
from app.db.models import ContentCreationRecord, CreationPublishAttemptRecord
from app.main import app
from app.services.autophone_service import (
    AutophoneNotFoundError,
    AutophonePublishRequest,
)
from app.services.db_service import DBService
from tests.db_test_utils import db_session


def _auth_headers(client: TestClient) -> dict[str, str]:
    login = client.post(
        "/api/v1/auth/login",
        json={"email": "demo@starx.ai", "password": "demo123"},
    )
    return {"Authorization": f"Bearer {login.json()['accessToken']}"}


def _create_publish_creation(
    client: TestClient,
    headers: dict[str, str],
) -> tuple[str, str]:
    account = client.post(
        "/api/v1/accounts",
        json={
            "name": "发布可靠性测试号",
            "description": "发布状态机与并发测试",
            "purpose": "自动发布",
            "type": "专业号",
            "platforms": ["抖音"],
            "accountLinks": {"抖音": "https://example.test/douyin"},
            "publishSettings": {"抖音": {"androidId": "android-douyin"}},
        },
        headers=headers,
    )
    assert account.status_code == 200
    account_id = account.json()["id"]
    topic_id = client.get(
        f"/api/v1/accounts/{account_id}/topics",
        headers=headers,
    ).json()[0]["id"]
    creation = client.post(
        f"/api/v1/accounts/{account_id}/creations/generate",
        json={"topicId": topic_id, "targetPlatform": "抖音"},
        headers=headers,
    ).json()
    submitted = client.post(
        f"/api/v1/accounts/{account_id}/creations/{creation['creationId']}/submit-task",
        json={
            "topicId": topic_id,
            "targetPlatform": "抖音",
            "type": creation["type"],
            "content": creation["content"],
            "status": "pending_review",
        },
        headers=headers,
    )
    assert submitted.status_code == 200
    return account_id, creation["creationId"]


def _publish_payload(*, retry: bool = False) -> dict[str, object]:
    return {
        "assetList": ["https://cdn.example.test/video.mp4"],
        "description": "发布文案",
        "retry": retry,
    }


class QueuedAutophoneService:
    def __init__(self) -> None:
        self.requests: list[AutophonePublishRequest] = []

    def publish(self, request: AutophonePublishRequest) -> dict[str, object]:
        self.requests.append(request)
        return {
            "external_id": request.external_id,
            "platform": request.platform,
            "status": "queued",
            "android_id": request.android_id,
            "material_id": "mat_test",
            "publish_job_id": "pub_test",
            "task_id": "publish-pub_test",
            "error_message": None,
            "created_at": "2026-07-16 10:20:00",
            "triggered_at": "2026-07-16 10:20:00",
            "started_at": None,
            "finished_at": None,
        }


class MissingThenQueuedAutophoneService(QueuedAutophoneService):
    def __init__(self) -> None:
        super().__init__()
        self.external_job_missing = True

    def get_publish_status(self, external_id: str) -> dict[str, object]:
        if self.external_job_missing:
            raise AutophoneNotFoundError(f"publish job {external_id} was not found")
        return {
            "external_id": external_id,
            "platform": "douyin",
            "status": "queued",
            "android_id": "android-douyin",
        }


def test_terminal_publish_status_cannot_be_downgraded_by_late_response():
    with db_session() as session:
        autophone = QueuedAutophoneService()
        service = DBService(session)
        app.dependency_overrides[get_service] = lambda: service
        app.dependency_overrides[get_autophone_service] = lambda: autophone
        try:
            client = TestClient(app)
            headers = _auth_headers(client)
            account_id, creation_id = _create_publish_creation(client, headers)
            publish_url = f"/api/v1/accounts/{account_id}/creations/{creation_id}/publish"
            first = client.post(publish_url, json=_publish_payload(), headers=headers)
            assert first.status_code == 200
            external_id = first.json()["externalId"]

            queued = service.get_current_creation_publish_state("u_001", account_id, creation_id)
            assert queued is not None
            service.update_creation_publish_state(
                "u_001",
                account_id,
                creation_id,
                {**queued, "status": "succeeded"},
                expected_external_id=external_id,
                expected_attempt=1,
            )
            late = service.update_creation_publish_state(
                "u_001",
                account_id,
                creation_id,
                {**queued, "status": "failed", "errorMessage": "late device error"},
                expected_external_id=external_id,
                expected_attempt=1,
            )

            assert late.creationState["publish"]["status"] == "succeeded"
            retry = client.post(
                publish_url,
                json=_publish_payload(retry=True),
                headers=headers,
            )
            assert retry.status_code == 409
            assert len(autophone.requests) == 1
        finally:
            app.dependency_overrides.clear()


def test_concurrent_legacy_backfill_is_idempotent_on_sqlite(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'legacy-backfill.db'}",
        connect_args={"check_same_thread": False},
    )
    init_database(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)

    def override_service():
        with session_factory() as session:
            yield DBService(session)

    app.dependency_overrides[get_service] = override_service
    try:
        client = TestClient(app)
        headers = _auth_headers(client)
        account_id, creation_id = _create_publish_creation(client, headers)
        external_id = f"starx_{creation_id}_douyin"
        with session_factory() as session:
            creation = session.get(ContentCreationRecord, creation_id)
            assert creation is not None
            failed = {
                "externalId": external_id,
                "platform": "douyin",
                "status": "failed",
                "attempt": 1,
                "errorMessage": "legacy failure",
                "recordedAt": "2026-07-16T10:20:00+00:00",
            }
            creation.creation_state = {
                "publish": dict(failed),
                "publishHistory": [dict(failed)],
            }
            session.commit()

        barrier = Barrier(2)

        class RacingLegacyDBService(DBService):
            def __init__(self, session):  # noqa: ANN001
                super().__init__(session)
                self.waited_for_peer = False

            def _publish_attempts_for_record(self, record, *, for_update=False):  # noqa: ANN001
                attempts = super()._publish_attempts_for_record(record, for_update=for_update)
                if for_update and not attempts and not self.waited_for_peer:
                    self.waited_for_peer = True
                    barrier.wait(timeout=5)
                return attempts

        def backfill() -> str:
            with session_factory() as session:
                state = RacingLegacyDBService(session).get_current_creation_publish_state(
                    "u_001",
                    account_id,
                    creation_id,
                )
                assert state is not None
                return str(state["status"])

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda _: backfill(), range(2)))

        assert results == ["failed", "failed"]
        with session_factory() as session:
            count = session.scalar(
                select(func.count())
                .select_from(CreationPublishAttemptRecord)
                .where(CreationPublishAttemptRecord.creation_id == creation_id)
            )
        assert count == 1
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_expired_unconfirmed_reservation_recovers_after_external_not_found():
    with db_session() as session:
        autophone = MissingThenQueuedAutophoneService()
        service = DBService(session)
        app.dependency_overrides[get_service] = lambda: service
        app.dependency_overrides[get_autophone_service] = lambda: autophone
        try:
            client = TestClient(app)
            headers = _auth_headers(client)
            account_id, creation_id = _create_publish_creation(client, headers)
            reservation = service.reserve_creation_publish_attempt(
                "u_001",
                account_id,
                creation_id,
                expected_target_platform="抖音",
                external_platform="douyin",
                android_id="android-douyin",
                retry=False,
            )
            attempt = session.scalar(
                select(CreationPublishAttemptRecord).where(
                    CreationPublishAttemptRecord.external_id == reservation.external_id
                )
            )
            assert attempt is not None
            attempt.updated_at = datetime.now(UTC) - timedelta(minutes=6)
            session.commit()
            publish_url = f"/api/v1/accounts/{account_id}/creations/{creation_id}/publish"

            recovered = client.get(f"{publish_url}/status", headers=headers)

            assert recovered.status_code == 200
            assert recovered.json()["status"] == "failed"
            assert "not found" in recovered.json()["errorMessage"]

            autophone.external_job_missing = False
            retried = client.post(
                publish_url,
                json=_publish_payload(retry=True),
                headers=headers,
            )
            assert retried.status_code == 200
            assert retried.json()["attempt"] == 2
        finally:
            app.dependency_overrides.clear()
