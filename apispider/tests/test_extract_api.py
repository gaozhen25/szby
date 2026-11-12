from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from app.api.deps import get_service
from app.api.routes.creations import get_creation_scheduler
from app.api.routes.extract import get_extract_reference_service, get_profile_extract_service
from app.core.security import create_access_token, get_password_hash
from app.db.models import ContentCreationRecord, MaterialRecord, UserRecord, WorkflowRecord
from app.main import app
from app.services.db_service import DBService
from tests.db_test_utils import db_session
from tests.test_api_flows import auth_headers


class FakeExtractReferenceService:
    def extract_from_text(self, share_text: str) -> dict:
        assert share_text.startswith("8.25 复制打开抖音")
        return {
            "url": "https://v.douyin.com/xdSvtgg4xpo/",
            "resolvedUrl": "https://www.douyin.com/video/123",
            "platform": "抖音",
            "type": "image",
            "title": "失败者联盟",
            "description": "正文内容 #热梗 #失败者联盟",
            "images": [
                {
                    "sourceUrl": "https://source.example.test/cover.webp",
                    "url": "https://source.example.test/cover.webp",
                    "contentType": "",
                    "kind": "image",
                    "storageStatus": "external",
                }
            ],
            "videos": [
                {
                    "sourceUrl": "https://source.example.test/video.mp4",
                    "url": "https://source.example.test/video.mp4",
                    "contentType": "",
                    "kind": "video",
                    "storageStatus": "external",
                }
            ],
            "cover": "https://source.example.test/cover.webp",
        }


class FakeProfileExtractService:
    def extract(self, url: str, limit: int = 10) -> dict:
        assert url == "https://www.douyin.com/user/sample"
        assert limit == 2
        return {
            "platform": "douyin",
            "url": url,
            "resolvedUrl": url,
            "name": "示例博主",
            "accountId": "sample-id",
            "description": "示例简介",
            "following": 139,
            "followers": 974_000,
            "liked": 55_583_000,
            "worksCount": 88,
            "metricLabels": {"followers": "97.4万", "liked": "5558.3万"},
            "works": [
                {
                    "id": "1",
                    "url": "https://www.douyin.com/video/1",
                    "title": "第一条作品",
                }
            ],
        }


class RollbackAwareExtractReferenceService(FakeExtractReferenceService):
    def __init__(self, session) -> None:
        self.session = session

    def extract_from_text(self, share_text: str) -> dict:
        assert self.session.rollback_count >= 1
        return super().extract_from_text(share_text)


class RollbackTrackingSession:
    def __init__(self, session):
        self._session = session
        self.rollback_count = 0

    def __getattr__(self, name):
        return getattr(self._session, name)

    def rollback(self):
        self.rollback_count += 1
        self._session.rollback()


class HistoryCommitTimeoutSession:
    def __init__(self, session):
        self._session = session
        self.rollback_called = False

    def __getattr__(self, name):
        return getattr(self._session, name)

    def commit(self):
        raise OperationalError("INSERT INTO extract_histories ...", {}, Exception("query timeout"))

    def rollback(self):
        self.rollback_called = True
        self._session.rollback()


class RecordingCreationScheduler:
    def __init__(self):
        self.calls = []

    def submit(self, workflow_type, workflow_id, context=None):
        self.calls.append((workflow_type, workflow_id, context or {}))


def _creation_content():
    return {
        "scriptOriginal": ["原始脚本"],
        "scriptRewritten": ["改写脚本"],
        "title": "解析视频创作",
        "body": "视频正文",
        "hashtags": ["#测试"],
        "cover": {"fileId": "", "url": "https://source.example.test/cover.webp"},
        "bgmSuggestion": "",
        "sensitiveCheck": {"status": "passed", "issues": []},
        "imagePrompt": "",
        "assets": [],
    }


def test_extract_link_reference_api_returns_history_id_and_external_media_urls():
    with db_session() as session:
        app.dependency_overrides[get_service] = lambda: DBService(session)
        app.dependency_overrides[get_extract_reference_service] = lambda: FakeExtractReferenceService()

        try:
            client = TestClient(app)
            headers = auth_headers(client)
            response = client.post(
                "/api/v1/extract/link-reference",
                json={
                    "text": "8.25 复制打开抖音，看看【GBD的图文作品】失败者联盟。https://v.douyin.com/xdSvtgg4xpo/ ATl:/"
                },
                headers=headers,
            )

            assert response.status_code == 200
            payload = response.json()
            assert payload["title"] == "失败者联盟"
            assert payload["historyId"].startswith("eh_")
            assert payload["images"][0]["url"] == "https://source.example.test/cover.webp"
            assert payload["images"][0]["storageStatus"] == "external"
            assert payload["cover"] == payload["images"][0]["url"]
        finally:
            app.dependency_overrides.clear()


def test_extract_creator_profile_api_returns_public_metrics_and_work_links():
    with db_session() as session:
        app.dependency_overrides[get_service] = lambda: DBService(session)
        app.dependency_overrides[get_profile_extract_service] = lambda: FakeProfileExtractService()
        try:
            client = TestClient(app)
            headers = auth_headers(client)
            response = client.post(
                "/api/v1/extract/creator-profile",
                json={"url": "https://www.douyin.com/user/sample", "limit": 2},
                headers=headers,
            )

            assert response.status_code == 200
            payload = response.json()
            assert payload["followers"] == 974_000
            assert payload["metricLabels"]["followers"] == "97.4万"
            assert payload["works"][0]["url"] == "https://www.douyin.com/video/1"
        finally:
            app.dependency_overrides.clear()


def test_extract_link_reference_api_returns_result_when_history_save_times_out():
    with db_session() as session:
        timeout_session = HistoryCommitTimeoutSession(session)
        app.dependency_overrides[get_service] = lambda: DBService(timeout_session)
        app.dependency_overrides[get_extract_reference_service] = lambda: FakeExtractReferenceService()

        try:
            client = TestClient(app)
            headers = auth_headers(client)
            response = client.post(
                "/api/v1/extract/link-reference",
                json={
                    "text": "8.25 复制打开抖音，看看【GBD的图文作品】失败者联盟。https://v.douyin.com/xdSvtgg4xpo/ ATl:/"
                },
                headers=headers,
            )

            assert response.status_code == 200
            assert response.json()["title"] == "失败者联盟"
            assert timeout_session.rollback_called is True
        finally:
            app.dependency_overrides.clear()


def test_extract_link_reference_api_releases_auth_transaction_before_extracting():
    with db_session() as session:
        tracking_session = RollbackTrackingSession(session)
        app.dependency_overrides[get_service] = lambda: DBService(tracking_session)
        app.dependency_overrides[get_extract_reference_service] = lambda: RollbackAwareExtractReferenceService(
            tracking_session
        )

        try:
            client = TestClient(app)
            headers = auth_headers(client)
            response = client.post(
                "/api/v1/extract/link-reference",
                json={
                    "text": "8.25 复制打开抖音，看看【GBD的图文作品】失败者联盟。https://v.douyin.com/xdSvtgg4xpo/ ATl:/"
                },
                headers=headers,
            )

            assert response.status_code == 200
            assert response.json()["title"] == "失败者联盟"
        finally:
            app.dependency_overrides.clear()


def test_extract_link_reference_api_saves_user_history_and_filters_by_owner():
    with db_session() as session:
        session.add(
            UserRecord(
                id="u_other",
                email="other@starx.ai",
                password_hash=get_password_hash("secret123"),
                nickname="Other User",
                status="active",
            )
        )
        session.commit()
        app.dependency_overrides[get_service] = lambda: DBService(session)
        app.dependency_overrides[get_extract_reference_service] = lambda: FakeExtractReferenceService()

        try:
            client = TestClient(app)
            headers = auth_headers(client)
            created = client.post(
                "/api/v1/extract/link-reference",
                json={
                    "text": "8.25 复制打开抖音，看看【GBD的图文作品】失败者联盟。https://v.douyin.com/xdSvtgg4xpo/ ATl:/"
                },
                headers=headers,
            )
            assert created.status_code == 200

            history = client.get("/api/v1/extract/link-reference/history", headers=headers)
            assert history.status_code == 200
            items = history.json()
            assert len(items) == 1
            assert items[0]["title"] == "失败者联盟"
            assert items[0]["historyId"] == items[0]["id"]
            assert items[0]["images"][0]["url"] == "https://source.example.test/cover.webp"
            assert items[0]["createdAt"]

            other_headers = {"Authorization": f"Bearer {create_access_token('u_other')}"}
            other_history = client.get("/api/v1/extract/link-reference/history", headers=other_headers)
            assert other_history.status_code == 200
            assert other_history.json() == []
        finally:
            app.dependency_overrides.clear()


def test_extract_history_can_bind_to_creation_and_task():
    with db_session() as session:
        app.dependency_overrides[get_service] = lambda: DBService(session)
        app.dependency_overrides[get_extract_reference_service] = lambda: FakeExtractReferenceService()

        try:
            client = TestClient(app)
            headers = auth_headers(client)
            account_id = client.get("/api/v1/accounts", headers=headers).json()[0]["id"]
            creation_id = "manual_extract_1"
            created = client.post(
                "/api/v1/extract/link-reference",
                json={
                    "text": "8.25 复制打开抖音，看看【GBD的图文作品】失败者联盟。https://v.douyin.com/xdSvtgg4xpo/ ATl:/",
                    "accountId": account_id,
                    "creationId": creation_id,
                },
                headers=headers,
            )
            assert created.status_code == 200
            assert created.json()["hashtags"] == ["#热梗", "#失败者联盟"]
            assert created.json()["videos"][0]["url"].endswith("/video.mp4")

            history = client.get(
                f"/api/v1/extract/link-reference/history?accountId={account_id}&creationId={creation_id}",
                headers=headers,
            )
            assert history.status_code == 200
            item = history.json()[0]
            assert item["accountId"] == account_id
            assert item["creationId"] == creation_id
            assert item["taskId"] is None

            task = client.post(
                f"/api/v1/accounts/{account_id}/tasks",
                json={
                    "title": "解析绑定任务",
                    "type": "video",
                    "targetPlatform": "抖音",
                },
                headers=headers,
            )
            assert task.status_code == 200

            bound = client.patch(
                "/api/v1/extract/link-reference/history/bind",
                json={
                    "creationId": creation_id,
                    "taskId": task.json()["id"],
                    "historyIds": [item["id"]],
                },
                headers=headers,
            )
            assert bound.status_code == 200
            assert bound.json()[0]["taskId"] == task.json()["id"]

            task_history = client.get(
                f"/api/v1/extract/link-reference/history?taskId={task.json()['id']}",
                headers=headers,
            )
            assert task_history.status_code == 200
            assert task_history.json()[0]["id"] == item["id"]
        finally:
            app.dependency_overrides.clear()


def test_creation_auto_save_does_not_enqueue_asset_persistence():
    with db_session() as session:
        scheduler = RecordingCreationScheduler()
        app.dependency_overrides[get_service] = lambda: DBService(session)
        app.dependency_overrides[get_creation_scheduler] = lambda: scheduler
        try:
            client = TestClient(app)
            headers = auth_headers(client)
            account_id = client.get("/api/v1/accounts", headers=headers).json()[0]["id"]
            response = client.post(
                f"/api/v1/accounts/{account_id}/creations/creation_auto_save/submit-task",
                json={
                    "targetPlatform": "抖音",
                    "type": "video",
                    "content": _creation_content(),
                    "persistExtractAssets": False,
                },
                headers=headers,
            )

            assert response.status_code == 200
            assert response.json()["assetPersistence"] is None
            assert scheduler.calls == []
            workflows = session.query(WorkflowRecord).filter_by(type="asset_persistence").all()
            assert workflows == []
        finally:
            app.dependency_overrides.clear()


def test_explicit_script_save_immediately_persists_business_records_and_enqueues_assets():
    with db_session() as session:
        scheduler = RecordingCreationScheduler()
        app.dependency_overrides[get_service] = lambda: DBService(session)
        app.dependency_overrides[get_extract_reference_service] = lambda: FakeExtractReferenceService()
        app.dependency_overrides[get_creation_scheduler] = lambda: scheduler
        try:
            client = TestClient(app)
            headers = auth_headers(client)
            account_id = client.get("/api/v1/accounts", headers=headers).json()[0]["id"]
            extracted = client.post(
                "/api/v1/extract/link-reference",
                json={"text": "8.25 复制打开抖音 https://v.douyin.com/xdSvtgg4xpo/", "accountId": account_id},
                headers=headers,
            ).json()

            response = client.post(
                f"/api/v1/accounts/{account_id}/creations/creation_explicit_save/submit-task",
                json={
                    "targetPlatform": "抖音",
                    "type": "video",
                    "content": _creation_content(),
                    "creationState": {"linkReference": extracted},
                    "persistExtractAssets": True,
                    "extractHistoryId": extracted["historyId"],
                    "linkReference": extracted,
                    "saveScriptMaterial": True,
                },
                headers=headers,
            )

            assert response.status_code == 200
            payload = response.json()
            assert payload["creationId"] == "creation_explicit_save"
            assert payload["material"]["type"] == "script"
            assert [item["kind"] for item in payload["material"]["assets"]] == ["image", "video"]
            assert payload["assetPersistence"]["status"] == "pending"
            assert payload["assetPersistence"]["historyId"] == extracted["historyId"]
            assert scheduler.calls == [
                ("asset_persistence", payload["assetPersistence"]["jobId"], {})
            ]

            creation = session.get(ContentCreationRecord, "creation_explicit_save")
            material = session.get(MaterialRecord, payload["material"]["id"])
            workflow = session.get(WorkflowRecord, payload["assetPersistence"]["jobId"])
            assert [item["kind"] for item in creation.assets] == ["image", "video"]
            assert creation.creation_state["assetPersistence"]["status"] == "pending"
            assert material.assets == creation.assets
            assert workflow.status == "pending"
            assert workflow.input_payload["historyId"] == extracted["historyId"]
            assert workflow.input_payload["materialIds"] == [material.id]

            repeated = client.post(
                f"/api/v1/accounts/{account_id}/creations/creation_explicit_save/submit-task",
                json={
                    "targetPlatform": "抖音",
                    "type": "video",
                    "content": _creation_content(),
                    "creationState": {"linkReference": extracted},
                    "persistExtractAssets": True,
                    "extractHistoryId": extracted["historyId"],
                    "linkReference": extracted,
                    "saveScriptMaterial": True,
                },
                headers=headers,
            )
            assert repeated.status_code == 200
            assert repeated.json()["assetPersistence"]["jobId"] == workflow.id
            assert len(scheduler.calls) == 1
            session.refresh(workflow)
            assert len(workflow.input_payload["materialIds"]) == 2
        finally:
            app.dependency_overrides.clear()


def test_explicit_save_rejects_extract_history_owned_by_another_user():
    with db_session() as session:
        session.add(
            UserRecord(
                id="u_extract_other",
                email="extract-other@starx.ai",
                password_hash=get_password_hash("secret123"),
                nickname="Extract Other",
                status="active",
            )
        )
        session.commit()
        other_service = FakeExtractReferenceService()
        app.dependency_overrides[get_service] = lambda: DBService(session)
        app.dependency_overrides[get_extract_reference_service] = lambda: other_service
        app.dependency_overrides[get_creation_scheduler] = lambda: RecordingCreationScheduler()
        try:
            client = TestClient(app)
            headers = auth_headers(client)
            account_id = client.get("/api/v1/accounts", headers=headers).json()[0]["id"]
            other_headers = {"Authorization": f"Bearer {create_access_token('u_extract_other')}"}
            extracted = client.post(
                "/api/v1/extract/link-reference",
                json={"text": "8.25 复制打开抖音 https://v.douyin.com/xdSvtgg4xpo/", "accountId": account_id},
                headers=other_headers,
            ).json()

            response = client.post(
                f"/api/v1/accounts/{account_id}/creations/creation_forbidden/submit-task",
                json={
                    "targetPlatform": "抖音",
                    "type": "video",
                    "content": _creation_content(),
                    "persistExtractAssets": True,
                    "extractHistoryId": extracted["historyId"],
                    "linkReference": extracted,
                },
                headers=headers,
            )

            assert response.status_code == 404
            assert response.json()["detail"] == "extract history is not available"
            assert session.get(ContentCreationRecord, "creation_forbidden") is None
        finally:
            app.dependency_overrides.clear()
