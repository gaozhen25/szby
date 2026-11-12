import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.api.deps import get_ai_service, get_service
from app.api.routes.generation import get_generation_jobs, get_generation_scheduler
from app.api.routes.uploads import get_direct_upload_service
from app.db.models import TopicRecord, WorkflowRecord
from app.main import app
from app.services.db_service import DBService
from app.services.workflow import WorkflowService
from tests.db_test_utils import db_session
from tests.test_generation_jobs import FakeAIService, FakeStorage


class InlineWorkflowScheduler:
    def __init__(self, service: WorkflowService) -> None:
        self.service = service

    def submit(self, job_type: str, job_id: str, context=None) -> None:  # noqa: ANN001, ARG002
        self.service.run_job(job_type, job_id)


class StubDirectUploads:
    def verify_ref(self, *, ref, **kwargs):  # noqa: ANN001, ARG002
        return SimpleNamespace(object_url=ref.url)

    @staticmethod
    def mark_consumed(records, **kwargs):  # noqa: ANN001, ARG004
        return None


class RecordingWorkflowScheduler:
    def __init__(self) -> None:
        self.submissions: list[tuple[str, str]] = []

    def submit(self, job_type: str, job_id: str, context=None) -> None:  # noqa: ANN001, ARG002
        self.submissions.append((job_type, job_id))


class ImagePromptPlanAIService(FakeAIService):
    async def chat_completion(self, messages, system_prompt=None, temperature=0.7):  # noqa: ANN001, ARG002
        self.chat_completion_inputs.append(str(messages[0]["content"]))
        return json.dumps(
            {
                "sharedStyle": "同一位女性、奶油色调、柔和侧光、居中构图、顶部文字安全区",
                "prompts": [
                    {"title": "封面", "prompt": "人物展示不同口红的对比"},
                    {"title": "内容页 1", "prompt": "手臂试色展示暖调颜色"},
                    {"title": "内容页 2", "prompt": "自然光下展示上唇效果"},
                    {"title": "收尾页", "prompt": "人物拿着选中的口红看向镜头"},
                ],
                "negativePrompt": "模糊、畸变、文字乱码",
                "publishCopy": "黄皮选口红，先看这组显白方向。",
                "hashtags": ["#黄皮口红", "#美妆分享"],
            },
            ensure_ascii=False,
        )


def test_generation_route_uses_new_workflow_service_package():
    from app.api.routes import generation

    assert generation.WorkflowService.__module__.startswith("app.services.workflow.")
    assert not generation.WorkflowService.__module__.startswith("app.services.workflow_service")


def _auth_headers(client: TestClient) -> dict[str, str]:
    login = client.post("/api/v1/auth/login", json={"email": "demo@starx.ai", "password": "demo123"})
    token = login.json()["accessToken"]
    return {"Authorization": f"Bearer {token}"}


def test_video_script_job_api_creates_pending_job_with_exact_preferences():
    with db_session() as session:
        scheduler = RecordingWorkflowScheduler()
        app.dependency_overrides[get_service] = lambda: DBService(session)
        app.dependency_overrides[get_generation_scheduler] = lambda: scheduler

        try:
            client = TestClient(app)
            headers = _auth_headers(client)
            payload = {
                "topicId": "t1",
                "targetPlatform": "小红书",
                "durationSeconds": 90,
                "contentGoal": "acquisition",
                "videoFormat": "knowledge_explainer",
                "toneStyle": "conversational",
                "customRequirements": "开头直接点出通勤时间紧张",
            }

            created = client.post(
                "/api/v1/accounts/acc1/generation/video-script-jobs",
                json=payload,
                headers=headers,
            )

            assert created.status_code == 200
            response = created.json()
            assert response["type"] == "video_script"
            assert response["status"] == "pending"
            assert response["requestedCount"] == 1
            assert response["topicTitle"] == "早八通勤妆5分钟搞定"
            assert response["inputPayload"] == {
                **payload,
                "schemaVersion": 3,
                "manualVersion": "2026-07-10.v1",
            }
            assert scheduler.submissions == [("video_script", response["id"])]
        finally:
            app.dependency_overrides.clear()


@pytest.mark.parametrize(
    ("topic_id", "payload_update"),
    [
        ("t1", {"durationSeconds": 45}),
        ("t1", {"contentGoal": "engagement"}),
        ("t1", {"videoFormat": "cinematic"}),
        ("t1", {"toneStyle": "dramatic"}),
        ("t1", {"customRequirements": "需" * 501}),
        ("t2", {}),
        ("t1", {"targetPlatform": "抖音"}),
        ("foreign-video", {}),
    ],
    ids=[
        "duration",
        "goal",
        "format",
        "tone",
        "requirements",
        "non-video-topic",
        "platform-not-configured",
        "topic-not-owned",
    ],
)
def test_video_script_job_api_rejects_invalid_preferences_or_topic(topic_id, payload_update):  # noqa: ANN001
    with db_session() as session:
        session.add(
            TopicRecord(
                id="acc2_foreign-video",
                account_id="acc2",
                title="其他账号的视频选题",
                source="AI推荐",
                category="探店",
                content_type="video",
            )
        )
        session.commit()
        scheduler = RecordingWorkflowScheduler()
        app.dependency_overrides[get_service] = lambda: DBService(session)
        app.dependency_overrides[get_generation_scheduler] = lambda: scheduler

        try:
            client = TestClient(app)
            headers = _auth_headers(client)
            payload = {
                "topicId": topic_id,
                "targetPlatform": "小红书",
                "durationSeconds": 60,
                "contentGoal": "auto",
                "videoFormat": "auto",
                "toneStyle": "auto",
                "customRequirements": "",
                **payload_update,
            }

            response = client.post(
                "/api/v1/accounts/acc1/generation/video-script-jobs",
                json=payload,
                headers=headers,
            )

            assert response.status_code == 422
            assert scheduler.submissions == []
            assert session.scalars(
                select(WorkflowRecord).where(WorkflowRecord.type == "video_script")
            ).all() == []
        finally:
            app.dependency_overrides.clear()


def test_prompt_job_api_creates_job_and_background_generates_prompt(monkeypatch):
    with db_session() as session:
        storage = FakeStorage()
        service = WorkflowService(session, ai_service=FakeAIService(), storage=storage)
        app.dependency_overrides[get_service] = lambda: DBService(session)
        app.dependency_overrides[get_generation_jobs] = lambda: service
        app.dependency_overrides[get_generation_scheduler] = lambda: InlineWorkflowScheduler(service)

        def run_prompt(job_type, job_id, session_factory):  # noqa: ARG001
            return service.run_job(job_type, job_id)

        monkeypatch.setattr(WorkflowService, "run_in_new_session", run_prompt)
        try:
            client = TestClient(app)
            headers = _auth_headers(client)
            account_id = client.get("/api/v1/accounts", headers=headers).json()[0]["id"]

            created = client.post(
                f"/api/v1/accounts/{account_id}/generation/prompt-jobs",
                json={
                    "copyText": "参考文案",
                    "targetPlatform": "小红书",
                    "topicTitle": "通勤妆",
                    "referenceUrls": ["https://cdn.example.test/ref.png"],
                },
                headers=headers,
            )

            assert created.status_code == 200
            assert created.json()["status"] == "pending"
            job_id = created.json()["id"]

            fetched = client.get(f"/api/v1/accounts/{account_id}/generation/jobs/{job_id}", headers=headers)
            assert fetched.status_code == 200
            payload = fetched.json()
            assert payload["status"] == "completed"
            assert payload["prompt"] == "generated image prompt text"
            assert payload["assets"][0]["assetType"] == "reference"
            assert payload["assets"][0]["analysis"] == "reference image analysis"
        finally:
            app.dependency_overrides.clear()


def test_topic_prompt_job_api_creates_text_only_prompt_job(monkeypatch):
    with db_session() as session:
        ai_service = FakeAIService()
        service = WorkflowService(session, ai_service=ai_service, storage=FakeStorage())
        app.dependency_overrides[get_service] = lambda: DBService(session)
        app.dependency_overrides[get_generation_jobs] = lambda: service
        app.dependency_overrides[get_generation_scheduler] = lambda: InlineWorkflowScheduler(service)

        def run_prompt(job_type, job_id, session_factory):  # noqa: ARG001
            return service.run_job(job_type, job_id)

        monkeypatch.setattr(WorkflowService, "run_in_new_session", run_prompt)

        try:
            client = TestClient(app)
            headers = _auth_headers(client)
            account_id = client.get("/api/v1/accounts", headers=headers).json()[0]["id"]

            created = client.post(
                f"/api/v1/accounts/{account_id}/generation/topic-prompt-jobs",
                json={"topicTitle": "通勤妆", "copyText": "轻薄持妆", "targetPlatform": "小红书"},
                headers=headers,
            )

            assert created.status_code == 200
            assert created.json()["status"] == "pending"
            assert created.json()["type"] == "prompt"
            assert created.json()["requestedCount"] == 0
            assert created.json()["inputPayload"]["mode"] == "topic_text"
            job_id = created.json()["id"]

            fetched = client.get(f"/api/v1/accounts/{account_id}/generation/jobs/{job_id}", headers=headers)
            assert fetched.status_code == 200
            payload = fetched.json()
            assert payload["status"] == "completed"
            assert payload["prompt"] == "generated image prompt text"
            assert payload["assets"] == []
            assert ai_service.image_view_inputs == []
            assert "通勤妆" in ai_service.chat_completion_inputs[0]
            assert "分别改写每一张图片" not in ai_service.chat_completion_inputs[0]
        finally:
            app.dependency_overrides.clear()


def test_topic_image_prompt_plan_api_uses_owned_topic_and_generates_no_images(monkeypatch):
    with db_session() as session:
        ai_service = ImagePromptPlanAIService()
        service = WorkflowService(session, ai_service=ai_service, storage=FakeStorage())
        app.dependency_overrides[get_service] = lambda: DBService(session)
        app.dependency_overrides[get_generation_jobs] = lambda: service
        app.dependency_overrides[get_generation_scheduler] = lambda: InlineWorkflowScheduler(service)

        def run_prompt(job_type, job_id, session_factory):  # noqa: ARG001
            return service.run_job(job_type, job_id)

        monkeypatch.setattr(WorkflowService, "run_in_new_session", run_prompt)

        try:
            client = TestClient(app)
            headers = _auth_headers(client)
            preferences = {
                "topicId": "t2",
                "topicTitle": "不应信任客户端标题",
                "copyText": "不应作为主题事实",
                "targetPlatform": "小红书",
                "imageCount": 4,
                "collectionMode": "series",
                "ratio": "3:4",
                "creativityLevel": "medium",
                "visualStyle": "lifestyle_editorial",
                "customRequirements": "奶油色调，人物保持一致",
            }

            created = client.post(
                "/api/v1/accounts/acc1/generation/topic-prompt-jobs",
                json=preferences,
                headers=headers,
            )

            assert created.status_code == 200
            response = created.json()
            assert response["topicTitle"] == "黄皮显白口红合集推荐"
            assert response["requestedCount"] == 4
            assert response["inputPayload"] == {
                "mode": "topic_image_plan",
                "topicId": "t2",
                "targetPlatform": "小红书",
                "imageCount": 4,
                "collectionMode": "series",
                "ratio": "3:4",
                "creativityLevel": "medium",
                "visualStyle": "lifestyle_editorial",
                "customRequirements": "奶油色调，人物保持一致",
                "schemaVersion": 1,
            }

            fetched = client.get(
                f"/api/v1/accounts/acc1/generation/jobs/{response['id']}",
                headers=headers,
            )
            assert fetched.status_code == 200
            completed = fetched.json()
            assert completed["status"] == "completed"
            assert completed["resultPayload"]["imageCount"] == 4
            assert len(completed["resultPayload"]["prompts"]) == 4
            assert completed["prompt"] == completed["resultPayload"]["prompts"][0]["prompt"]
            assert completed["assets"] == []
            assert [step["type"] for step in completed["steps"]] == ["prompt_summary"]
            assert ai_service.image_view_inputs == []
            assert ai_service.image_generation_inputs == []
            assert "黄皮显白口红合集推荐" in ai_service.chat_completion_inputs[0]
            assert "不应信任客户端标题" not in ai_service.chat_completion_inputs[0]
        finally:
            app.dependency_overrides.clear()


def test_topic_image_prompt_plan_reverse_analyzes_bound_hot_note_images(monkeypatch):
    with db_session() as session:
        topic = session.get(TopicRecord, "acc1_t2")
        topic.reference_note = {
            "contentId": "hot-1",
            "platform": "小红书",
            "title": "通勤底妆爆款实测",
            "publicUrl": "https://www.xiaohongshu.com/explore/hot-1",
        }
        session.commit()
        ai_service = ImagePromptPlanAIService()
        service = WorkflowService(session, ai_service=ai_service, storage=FakeStorage())
        app.dependency_overrides[get_service] = lambda: DBService(session)
        app.dependency_overrides[get_generation_jobs] = lambda: service
        app.dependency_overrides[get_generation_scheduler] = lambda: InlineWorkflowScheduler(service)

        def run_prompt(job_type, job_id, session_factory):  # noqa: ARG001
            return service.run_job(job_type, job_id)

        monkeypatch.setattr(WorkflowService, "run_in_new_session", run_prompt)
        try:
            client = TestClient(app)
            headers = _auth_headers(client)
            created = client.post(
                "/api/v1/accounts/acc1/generation/topic-prompt-jobs",
                json={
                    "topicId": "t2",
                    "targetPlatform": "小红书",
                    "imageCount": 4,
                    "collectionMode": "series",
                    "ratio": "3:4",
                    "creativityLevel": "medium",
                    "visualStyle": "lifestyle_editorial",
                    "referenceUrls": [
                        "https://cdn.example.test/hot-1-cover.jpg",
                        "https://cdn.example.test/hot-1-detail.jpg",
                    ],
                },
                headers=headers,
            )
            fetched = client.get(
                f"/api/v1/accounts/acc1/generation/jobs/{created.json()['id']}",
                headers=headers,
            ).json()

            assert fetched["status"] == "completed"
            assert ai_service.image_view_inputs == [
                "https://cdn.example.test/hot-1-cover.jpg",
                "https://cdn.example.test/hot-1-detail.jpg",
            ]
            assert fetched["resultPayload"]["referenceNote"]["contentId"] == "hot-1"
            assert fetched["resultPayload"]["referenceAnalyses"] == [
                "reference image analysis",
                "reference image analysis",
            ]
            step_types = [step["type"] for step in fetched["steps"]]
            assert step_types.count("image_analysis") == 2
            assert step_types.count("prompt_summary") == 1
            assert "referenceImageAnalyses" in ai_service.chat_completion_inputs[0]
            assert ai_service.image_generation_inputs == []
        finally:
            app.dependency_overrides.clear()


@pytest.mark.parametrize(
    ("topic_id", "payload_update"),
    [
        ("t1", {}),
        ("t2", {"imageCount": 0}),
        ("t2", {"imageCount": 5}),
        ("t2", {"imageCount": 1, "collectionMode": "series"}),
        ("t2", {"targetPlatform": "抖音"}),
        ("t2", {"ratio": "2:3"}),
        ("t2", {"visualStyle": "cinematic"}),
        ("t2", {"creativityLevel": "extreme"}),
        ("t2", {"customRequirements": "需" * 501}),
        ("foreign-image", {}),
    ],
    ids=[
        "video-topic",
        "count-zero",
        "count-five",
        "single-image-series",
        "platform-not-configured",
        "ratio",
        "style",
        "creativity",
        "requirements",
        "topic-not-owned",
    ],
)
def test_topic_image_prompt_plan_api_rejects_invalid_preferences_or_topic(topic_id, payload_update):  # noqa: ANN001
    with db_session() as session:
        session.add(
            TopicRecord(
                id="acc2_foreign-image",
                account_id="acc2",
                title="其他账号的图片选题",
                source="AI推荐",
                category="探店",
                content_type="image",
            )
        )
        session.commit()
        scheduler = RecordingWorkflowScheduler()
        app.dependency_overrides[get_service] = lambda: DBService(session)
        app.dependency_overrides[get_generation_scheduler] = lambda: scheduler

        try:
            client = TestClient(app)
            headers = _auth_headers(client)
            payload = {
                "topicId": topic_id,
                "targetPlatform": "小红书",
                "imageCount": 2,
                "collectionMode": "independent",
                "ratio": "3:4",
                "creativityLevel": "medium",
                "visualStyle": "auto",
                "customRequirements": "",
                **payload_update,
            }

            response = client.post(
                "/api/v1/accounts/acc1/generation/topic-prompt-jobs",
                json=payload,
                headers=headers,
            )

            assert response.status_code == 422
            assert scheduler.submissions == []
            assert session.scalars(
                select(WorkflowRecord).where(
                    WorkflowRecord.type == "prompt",
                    WorkflowRecord.input_payload["mode"].as_string() == "topic_image_plan",
                )
            ).all() == []
        finally:
            app.dependency_overrides.clear()


def test_image_job_api_creates_job_and_background_generates_images(monkeypatch):
    async def fake_generated_image_download(url: str) -> tuple[bytes, str]:
        assert url == "https://cdn.example.test/generated.png"
        return b"generated image", "image/png"

    monkeypatch.setattr(
        "app.services.workflow.workflows.generated_image_persistence._download_generated_image",
        fake_generated_image_download,
    )
    monkeypatch.setattr(
        "app.services.workflow.workflows.generated_image_persistence.embed_photo_exif",
        lambda data, content_type, parameters: data,
    )
    with db_session() as session:
        storage = FakeStorage()
        service = WorkflowService(
            session,
            ai_service=FakeAIService([{"url": "https://cdn.example.test/generated.png", "revisedPrompt": "refined"}]),
            storage=storage,
        )
        app.dependency_overrides[get_service] = lambda: DBService(session)
        app.dependency_overrides[get_generation_jobs] = lambda: service
        app.dependency_overrides[get_generation_scheduler] = lambda: InlineWorkflowScheduler(service)

        def run_image(job_type, job_id, session_factory):  # noqa: ARG001
            return service.run_job(job_type, job_id)

        monkeypatch.setattr(WorkflowService, "run_in_new_session", run_image)

        try:
            client = TestClient(app)
            headers = _auth_headers(client)
            account_id = client.get("/api/v1/accounts", headers=headers).json()[0]["id"]

            created = client.post(
                f"/api/v1/accounts/{account_id}/generation/image-jobs",
                json={"prompt": "make one image", "count": 1, "ratio": "1:1"},
                headers=headers,
            )

            assert created.status_code == 200
            assert created.json()["status"] == "pending"
            job_id = created.json()["id"]

            fetched = client.get(f"/api/v1/accounts/{account_id}/generation/jobs/{job_id}", headers=headers)
            assert fetched.status_code == 200
            payload = fetched.json()
            assert payload["status"] == "completed"
            assert payload["resultPayload"]["images"] == [
                {"url": payload["assets"][0]["url"], "revisedPrompt": "refined"}
            ]
            assert payload["assets"][0]["url"].startswith("http://localhost:9000/starx-assets/")
            assert payload["assets"][0]["meta"]["source"] == "url_persisted"
            assert payload["assets"][0]["meta"]["sourceHost"] == "cdn.example.test"
        finally:
            app.dependency_overrides.clear()


def test_image_job_api_accepts_reference_and_material_urls(monkeypatch):
    with db_session() as session:
        storage = FakeStorage()
        ai_service = FakeAIService([{"url": "https://cdn.example.test/generated.png"}])
        service = WorkflowService(session, ai_service=ai_service, storage=storage)
        app.dependency_overrides[get_service] = lambda: DBService(session)
        app.dependency_overrides[get_generation_jobs] = lambda: service
        app.dependency_overrides[get_generation_scheduler] = lambda: InlineWorkflowScheduler(service)

        def run_image(job_type, job_id, session_factory):  # noqa: ARG001
            return service.run_job(job_type, job_id)

        monkeypatch.setattr(WorkflowService, "run_in_new_session", run_image)

        try:
            client = TestClient(app)
            headers = _auth_headers(client)
            account_id = client.get("/api/v1/accounts", headers=headers).json()[0]["id"]

            created = client.post(
                f"/api/v1/accounts/{account_id}/generation/image-jobs",
                json={
                    "prompt": "知识库融合后的提示词",
                    "count": 1,
                    "ratio": "1:1",
                    "referenceStrength": 88,
                    "materialStrength": "高",
                    "slots": [],
                    "selectedTagIds": [],
                    "referenceUrls": ["https://cdn.example.test/ref.png"],
                    "materialUrls": ["https://cdn.example.test/mat.webp"],
                },
                headers=headers,
            )

            assert created.status_code == 200
            job_id = created.json()["id"]

            fetched = client.get(f"/api/v1/accounts/{account_id}/generation/jobs/{job_id}", headers=headers)
            assert fetched.status_code == 200
            payload = fetched.json()
            input_assets = [asset for asset in payload["assets"] if asset["assetType"] in {"reference", "material"}]
            assert [asset["assetType"] for asset in input_assets] == ["reference", "material"]
            assert input_assets[0]["meta"]["strength"] == 88
            assert input_assets[1]["meta"]["strength"] == "高"
            assert ai_service.image_generation_inputs == []
            assert ai_service.image_edit_inputs[0]["input_reference"] == [
                {"type": "image_url", "image_url": {"url": input_assets[0]["url"]}},
                {"type": "image_url", "image_url": {"url": input_assets[1]["url"]}},
            ]
            assert ai_service.image_edit_inputs[0]["extra_body"] is None
        finally:
            app.dependency_overrides.clear()


def test_person_replacement_job_api_preserves_image_roles_and_records_consent():
    with db_session() as session:
        scheduler = RecordingWorkflowScheduler()
        storage = FakeStorage()
        service = WorkflowService(session, ai_service=FakeAIService(), storage=storage)
        app.dependency_overrides[get_service] = lambda: DBService(session)
        app.dependency_overrides[get_generation_jobs] = lambda: service
        app.dependency_overrides[get_generation_scheduler] = lambda: scheduler
        app.dependency_overrides[get_direct_upload_service] = lambda: StubDirectUploads()
        app.dependency_overrides[get_direct_upload_service] = lambda: StubDirectUploads()

        try:
            client = TestClient(app)
            headers = _auth_headers(client)
            account_id = client.get("/api/v1/accounts", headers=headers).json()[0]["id"]

            created = client.post(
                f"/api/v1/accounts/{account_id}/generation/person-replacement-jobs",
                json={
                    "consentConfirmed": True,
                    "ratio": "1235:1552",
                    "count": 3,
                    "targetImage": {"url": "https://oss.example.test/target.jpg"},
                    "personImage": {"url": "https://oss.example.test/person.webp"},
                },
                headers=headers,
            )

            assert created.status_code == 200
            payload = created.json()
            assert payload["status"] == "pending"
            assert payload["ratio"] == "1235:1552"
            assert payload["requestedCount"] == 3
            assert payload["inputPayload"]["operation"] == "person_replacement"
            assert payload["inputPayload"]["consentConfirmed"] is True
            assert "图片 1 是场景底图" in payload["prompt"]
            assert "图片 2 是目标人物参考图" in payload["prompt"]
            input_assets = [asset for asset in payload["assets"] if asset["assetType"] in {"reference", "material"}]
            assert [asset["assetType"] for asset in input_assets] == ["reference", "material"]
            assert [asset["fileName"] for asset in input_assets] == ["target.jpg", "person.webp"]
            assert scheduler.submissions == [("image", payload["id"])]
        finally:
            app.dependency_overrides.clear()


def test_person_replacement_job_api_requires_explicit_consent():
    with db_session() as session:
        scheduler = RecordingWorkflowScheduler()
        service = WorkflowService(session, ai_service=FakeAIService(), storage=FakeStorage())
        app.dependency_overrides[get_service] = lambda: DBService(session)
        app.dependency_overrides[get_generation_jobs] = lambda: service
        app.dependency_overrides[get_generation_scheduler] = lambda: scheduler
        app.dependency_overrides[get_direct_upload_service] = lambda: StubDirectUploads()

        try:
            client = TestClient(app)
            headers = _auth_headers(client)
            response = client.post(
                "/api/v1/accounts/acc1/generation/person-replacement-jobs",
                json={
                    "consentConfirmed": False,
                    "ratio": "3:4",
                    "targetImage": {"url": "https://oss.example.test/target.png"},
                    "personImage": {"url": "https://oss.example.test/person.png"},
                },
                headers=headers,
            )

            assert response.status_code == 422
            assert response.json()["detail"] == "请确认已获得目标人物授权"
            assert scheduler.submissions == []
            assert session.scalars(select(WorkflowRecord).where(WorkflowRecord.type == "image")).all() == []
        finally:
            app.dependency_overrides.clear()


def test_person_replacement_job_api_rejects_unissued_oss_urls():
    with db_session() as session:
        scheduler = RecordingWorkflowScheduler()
        service = WorkflowService(session, ai_service=FakeAIService(), storage=FakeStorage())
        app.dependency_overrides[get_service] = lambda: DBService(session)
        app.dependency_overrides[get_generation_jobs] = lambda: service
        app.dependency_overrides[get_generation_scheduler] = lambda: scheduler

        try:
            client = TestClient(app)
            headers = _auth_headers(client)
            account_id = client.get("/api/v1/accounts", headers=headers).json()[0]["id"]
            response = client.post(
                f"/api/v1/accounts/{account_id}/generation/person-replacement-jobs",
                json={
                    "consentConfirmed": True,
                    "ratio": "3:4",
                    "targetImage": {"url": "https://oss.example.test/target.png"},
                    "personImage": {"url": "https://oss.example.test/person.png"},
                },
                headers=headers,
            )

            assert response.status_code == 422
            assert "not issued" in response.json()["detail"]
            assert scheduler.submissions == []
            assert session.scalars(select(WorkflowRecord).where(WorkflowRecord.type == "image")).all() == []
        finally:
            app.dependency_overrides.clear()


def test_person_replacement_result_download_returns_authenticated_attachment(monkeypatch):
    from app.api.routes import generation

    with db_session() as session:
        scheduler = RecordingWorkflowScheduler()
        service = WorkflowService(session, ai_service=FakeAIService(), storage=FakeStorage())
        app.dependency_overrides[get_service] = lambda: DBService(session)
        app.dependency_overrides[get_generation_jobs] = lambda: service
        app.dependency_overrides[get_generation_scheduler] = lambda: scheduler
        app.dependency_overrides[get_direct_upload_service] = lambda: StubDirectUploads()

        async def fake_download(url: str) -> tuple[bytes, str]:
            assert url == "https://provider.example.test/generated-2.png"
            return b"generated-image-bytes", "image/png"

        monkeypatch.setattr(generation, "download_generated_image", fake_download)

        try:
            client = TestClient(app)
            headers = _auth_headers(client)
            account_id = client.get("/api/v1/accounts", headers=headers).json()[0]["id"]
            created = client.post(
                f"/api/v1/accounts/{account_id}/generation/person-replacement-jobs",
                json={
                    "consentConfirmed": True,
                    "ratio": "3:4",
                    "targetImage": {"url": "https://oss.example.test/target.png"},
                    "personImage": {"url": "https://oss.example.test/person.png"},
                },
                headers=headers,
            ).json()
            record = session.get(WorkflowRecord, created["id"])
            record.result_payload = {
                "images": [
                    {"url": "https://provider.example.test/generated-1.png"},
                    {"url": "https://provider.example.test/generated-2.png"},
                ],
                "persistenceStatus": "persisting",
            }
            session.commit()

            response = client.get(
                f"/api/v1/accounts/{account_id}/generation/jobs/{created['id']}/result-image?imageIndex=1",
                headers=headers,
            )

            assert response.status_code == 200
            assert response.content == b"generated-image-bytes"
            assert response.headers["content-type"] == "image/png"
            assert response.headers["content-disposition"].startswith("attachment;")
            assert "-2.png" in response.headers["content-disposition"]
            assert response.headers["cache-control"] == "private, no-store"
        finally:
            app.dependency_overrides.clear()


def test_image_job_api_accepts_reference_urls(monkeypatch):
    with db_session() as session:
        storage = FakeStorage()
        ai_service = FakeAIService([{"url": "https://cdn.example.test/generated.png"}])
        service = WorkflowService(session, ai_service=ai_service, storage=storage)
        app.dependency_overrides[get_service] = lambda: DBService(session)
        app.dependency_overrides[get_generation_jobs] = lambda: service
        app.dependency_overrides[get_generation_scheduler] = lambda: InlineWorkflowScheduler(service)

        def run_image(job_type, job_id, session_factory):  # noqa: ARG001
            return service.run_job(job_type, job_id)

        monkeypatch.setattr(WorkflowService, "run_in_new_session", run_image)

        try:
            client = TestClient(app)
            headers = _auth_headers(client)
            account_id = client.get("/api/v1/accounts", headers=headers).json()[0]["id"]

            created = client.post(
                f"/api/v1/accounts/{account_id}/generation/image-jobs",
                json={
                    "prompt": "按原图风格生成",
                    "count": 1,
                    "ratio": "3:4",
                    "referenceUrls": ["https://oss.example.test/extract/rednote/source.webp"],
                    "referenceStrength": 91,
                },
                headers=headers,
            )

            assert created.status_code == 200
            job_id = created.json()["id"]

            fetched = client.get(f"/api/v1/accounts/{account_id}/generation/jobs/{job_id}", headers=headers)
            assert fetched.status_code == 200
            payload = fetched.json()
            input_assets = [asset for asset in payload["assets"] if asset["assetType"] == "reference"]
            assert input_assets[0]["url"] == "https://oss.example.test/extract/rednote/source.webp"
            assert input_assets[0]["meta"]["source"] == "reference_url"
            assert input_assets[0]["meta"]["strength"] == 91
            assert ai_service.image_generation_inputs == []
            assert ai_service.image_edit_inputs[0]["input_reference"] == [
                {"type": "image_url", "image_url": {"url": "https://oss.example.test/extract/rednote/source.webp"}}
            ]
        finally:
            app.dependency_overrides.clear()


def test_presign_api_rejects_unsupported_upload_type():
    with db_session() as session:
        service = WorkflowService(session, ai_service=FakeAIService(), storage=FakeStorage())
        app.dependency_overrides[get_service] = lambda: DBService(session)
        app.dependency_overrides[get_generation_jobs] = lambda: service
        app.dependency_overrides[get_generation_scheduler] = lambda: InlineWorkflowScheduler(service)

        try:
            client = TestClient(app)
            headers = _auth_headers(client)
            account_id = client.get("/api/v1/accounts", headers=headers).json()[0]["id"]

            response = client.post(
                "/api/v1/uploads/presign",
                json={
                    "accountId": account_id,
                    "purpose": "generation_reference",
                    "filename": "bad.gif",
                    "contentType": "image/gif",
                    "sizeBytes": 9,
                },
                headers=headers,
            )

            assert response.status_code == 422
            assert "not allowed" in response.json()["detail"]
        finally:
            app.dependency_overrides.clear()


def test_presign_api_rejects_oversized_upload(monkeypatch):
    from app.core.config import settings

    with db_session() as session:
        service = WorkflowService(session, ai_service=FakeAIService(), storage=FakeStorage())
        app.dependency_overrides[get_service] = lambda: DBService(session)
        app.dependency_overrides[get_generation_jobs] = lambda: service
        app.dependency_overrides[get_generation_scheduler] = lambda: InlineWorkflowScheduler(service)
        monkeypatch.setattr(settings, "max_upload_image_bytes", 4)

        try:
            client = TestClient(app)
            headers = _auth_headers(client)
            account_id = client.get("/api/v1/accounts", headers=headers).json()[0]["id"]

            response = client.post(
                "/api/v1/uploads/presign",
                json={
                    "accountId": account_id,
                    "purpose": "generation_reference",
                    "filename": "large.png",
                    "contentType": "image/png",
                    "sizeBytes": 5,
                },
                headers=headers,
            )

            assert response.status_code == 422
            assert "upload limit" in response.json()["detail"]
        finally:
            app.dependency_overrides.clear()


def test_prompt_job_api_accepts_oss_reference_urls(monkeypatch):
    with db_session() as session:
        storage = FakeStorage()
        service = WorkflowService(session, ai_service=FakeAIService(), storage=storage)
        app.dependency_overrides[get_service] = lambda: DBService(session)
        app.dependency_overrides[get_generation_jobs] = lambda: service
        app.dependency_overrides[get_generation_scheduler] = lambda: InlineWorkflowScheduler(service)

        def run_prompt(job_type, job_id, session_factory):  # noqa: ARG001
            return service.run_job(job_type, job_id)

        monkeypatch.setattr(WorkflowService, "run_in_new_session", run_prompt)

        try:
            client = TestClient(app)
            headers = _auth_headers(client)
            account_id = client.get("/api/v1/accounts", headers=headers).json()[0]["id"]

            created = client.post(
                f"/api/v1/accounts/{account_id}/generation/prompt-jobs",
                json={
                    "copyText": "提取出的正文",
                    "targetPlatform": "抖音",
                    "referenceUrls": ["https://oss.example.test/extract/douyin/cover.webp"],
                },
                headers=headers,
            )

            assert created.status_code == 200
            job_id = created.json()["id"]

            fetched = client.get(f"/api/v1/accounts/{account_id}/generation/jobs/{job_id}", headers=headers)
            assert fetched.status_code == 200
            payload = fetched.json()
            assert payload["status"] == "completed"
            assert payload["assets"][0]["url"] == "https://oss.example.test/extract/douyin/cover.webp"
            assert payload["assets"][0]["meta"]["source"] == "direct_or_reference_url"
        finally:
            app.dependency_overrides.clear()


def test_prompt_tag_api_lists_tags_composes_prompt_and_manages_templates():
    with db_session() as session:
        service = WorkflowService(session, ai_service=FakeAIService(), storage=FakeStorage())
        app.dependency_overrides[get_service] = lambda: DBService(session)
        app.dependency_overrides[get_generation_jobs] = lambda: service
        app.dependency_overrides[get_generation_scheduler] = lambda: InlineWorkflowScheduler(service)

        try:
            client = TestClient(app)
            headers = _auth_headers(client)
            account_id = client.get("/api/v1/accounts", headers=headers).json()[0]["id"]

            tags = client.get(f"/api/v1/accounts/{account_id}/generation/prompt-tags", headers=headers)
            assert tags.status_code == 200
            assert tags.json()[-1]["id"] == "quality"

            composed = client.post(
                f"/api/v1/accounts/{account_id}/generation/prompts/compose",
                json={"prompt": "未来城市街头的女孩", "selectedTagIds": ["photography", "8k"]},
                headers=headers,
            )
            assert composed.status_code == 200
            assert composed.json()["finalPrompt"].endswith("8K ultra HD，extremely detailed，high resolution")
            assert [tag["id"] for tag in composed.json()["selectedTags"]] == ["photography", "8k"]

            created = client.post(
                f"/api/v1/accounts/{account_id}/generation/prompt-templates",
                json={
                    "name": "赛博朋克人物通用",
                    "description": "夜景人物封面",
                    "prompt": "人物半身像",
                    "selectedTagIds": ["photography", "8k"],
                    "negativePrompt": "低清晰度",
                    "params": {"ratio": "3:4", "count": "2"},
                },
                headers=headers,
            )
            assert created.status_code == 200
            template = created.json()
            assert template["name"] == "赛博朋克人物通用"
            assert template["previewPrompt"].endswith("8K ultra HD，extremely detailed，high resolution")

            listed = client.get(f"/api/v1/accounts/{account_id}/generation/prompt-templates", headers=headers)
            assert listed.status_code == 200
            assert [item["id"] for item in listed.json()] == [template["id"]]

            updated = client.patch(
                f"/api/v1/accounts/{account_id}/generation/prompt-templates/{template['id']}",
                json={"name": "更新后的模板", "selectedTagIds": ["night_market"]},
                headers=headers,
            )
            assert updated.status_code == 200
            assert updated.json()["name"] == "更新后的模板"
            assert updated.json()["selectedTagIds"] == ["night_market"]

            deleted = client.delete(
                f"/api/v1/accounts/{account_id}/generation/prompt-templates/{template['id']}",
                headers=headers,
            )
            assert deleted.status_code == 204
            assert client.get(f"/api/v1/accounts/{account_id}/generation/prompt-templates", headers=headers).json() == []
        finally:
            app.dependency_overrides.clear()


def test_reverse_prompt_returns_404_when_account_is_not_available():
    with db_session() as session:
        app.dependency_overrides[get_service] = lambda: DBService(session)

        try:
            client = TestClient(app)
            headers = _auth_headers(client)

            response = client.post(
                "/api/v1/accounts/missing-account/generation/reverse-prompt",
                json={"imageUrl": "https://example.test/image.png"},
                headers=headers,
            )

            assert response.status_code == 404
            assert response.json() == {"detail": "missing-account"}
        finally:
            app.dependency_overrides.clear()


def test_reverse_prompt_analyzes_uploaded_oss_url_from_json():
    class ReversePromptAI:
        def __init__(self) -> None:
            self.image_urls: list[str] = []
            self.prompts: list[str] = []

        async def image_view(self, prompt, image_url, model=None, temperature=0.2):  # noqa: ANN001, ARG002
            self.image_urls.append(image_url)
            self.prompts.append(prompt)
            return json.dumps(
                {
                    "positive": "柔和自然光人像",
                    "negative": "模糊",
                    "publishCopy": "在柔和自然光里，记录松弛的一刻。",
                    "styleTags": ["摄影"],
                },
                ensure_ascii=False,
            )

    with db_session() as session:
        ai_service = ReversePromptAI()
        app.dependency_overrides[get_service] = lambda: DBService(session)
        app.dependency_overrides[get_ai_service] = lambda: ai_service

        try:
            client = TestClient(app)
            headers = _auth_headers(client)
            account_id = client.get("/api/v1/accounts", headers=headers).json()[0]["id"]

            response = client.post(
                f"/api/v1/accounts/{account_id}/generation/reverse-prompt",
                json={
                    "imageUrl": "https://cdn.example.test/reference.png",
                    "title": "随机一日三餐",
                    "description": "看看今天会吃到什么",
                    "targetPlatform": "小红书",
                },
                headers=headers,
            )

            assert response.status_code == 200
            payload = response.json()
            assert payload["positive"] == "柔和自然光人像"
            assert payload["publishCopy"] == "在柔和自然光里，记录松弛的一刻。"
            assert payload["imageUrl"] == "https://cdn.example.test/reference.png"
            assert ai_service.image_urls == [payload["imageUrl"]]
            assert '"publishCopy"' in ai_service.prompts[0]
            assert "正面提示词、负面提示词、发布文案和风格标签必须全部使用中文" in ai_service.prompts[0]
            assert "不得使用英文提示词或英文标签" in ai_service.prompts[0]
            assert "标题：随机一日三餐" in ai_service.prompts[0]
            assert "正文：看看今天会吃到什么" in ai_service.prompts[0]
            assert "目标平台：小红书" in ai_service.prompts[0]
        finally:
            app.dependency_overrides.clear()


def test_reverse_prompt_rejects_browser_blob_url():
    with db_session() as session:
        app.dependency_overrides[get_service] = lambda: DBService(session)

        try:
            client = TestClient(app)
            headers = _auth_headers(client)
            account_id = client.get("/api/v1/accounts", headers=headers).json()[0]["id"]

            response = client.post(
                f"/api/v1/accounts/{account_id}/generation/reverse-prompt",
                json={"imageUrl": "blob:https://stars.bytech.tech/local-reference"},
                headers=headers,
            )

            assert response.status_code == 422
            assert "blob URL" in response.json()["detail"]
        finally:
            app.dependency_overrides.clear()


def test_prompt_tag_api_manages_custom_categories_and_child_tags():
    with db_session() as session:
        service = WorkflowService(session, ai_service=FakeAIService(), storage=FakeStorage())
        app.dependency_overrides[get_service] = lambda: DBService(session)
        app.dependency_overrides[get_generation_jobs] = lambda: service
        app.dependency_overrides[get_generation_scheduler] = lambda: InlineWorkflowScheduler(service)

        try:
            client = TestClient(app)
            headers = _auth_headers(client)
            account_id = client.get("/api/v1/accounts", headers=headers).json()[0]["id"]

            category_response = client.post(
                f"/api/v1/accounts/{account_id}/generation/prompt-tag-categories",
                json={"label": "自定义镜头"},
                headers=headers,
            )
            assert category_response.status_code == 200
            category = category_response.json()
            assert category["label"] == "自定义镜头"
            assert category["source"] == "custom"
            assert category["tags"] == []

            tag_response = client.post(
                f"/api/v1/accounts/{account_id}/generation/prompt-tag-categories/{category['id']}/tags",
                json={"label": "低角度英雄镜头", "prompt": "低角度拍摄，主体更有力量感，背景纵深明显"},
                headers=headers,
            )
            assert tag_response.status_code == 200
            tag = tag_response.json()
            assert tag["categoryId"] == category["id"]
            assert tag["prompt"] == "低角度拍摄，主体更有力量感，背景纵深明显"

            listed = client.get(f"/api/v1/accounts/{account_id}/generation/prompt-tags", headers=headers)
            custom_category = next(item for item in listed.json() if item["id"] == category["id"])
            assert custom_category["tags"][0]["id"] == tag["id"]

            composed = client.post(
                f"/api/v1/accounts/{account_id}/generation/prompts/compose",
                json={"prompt": "新品手机海报", "selectedTagIds": [tag["id"]]},
                headers=headers,
            )
            assert composed.status_code == 200
            assert composed.json()["finalPrompt"] == "新品手机海报，低角度拍摄，主体更有力量感，背景纵深明显"

            updated_category = client.patch(
                f"/api/v1/accounts/{account_id}/generation/prompt-tag-categories/{category['id']}",
                json={"label": "自定义构图"},
                headers=headers,
            )
            assert updated_category.status_code == 200
            assert updated_category.json()["label"] == "自定义构图"

            updated_tag = client.patch(
                f"/api/v1/accounts/{account_id}/generation/prompt-tags/{tag['id']}",
                json={"label": "俯视陈列", "prompt": "俯视角度，元素整齐排列，画面留白清晰"},
                headers=headers,
            )
            assert updated_tag.status_code == 200
            assert updated_tag.json()["label"] == "俯视陈列"

            assert client.delete(
                f"/api/v1/accounts/{account_id}/generation/prompt-tags/{tag['id']}",
                headers=headers,
            ).status_code == 204
            assert client.delete(
                f"/api/v1/accounts/{account_id}/generation/prompt-tag-categories/{category['id']}",
                headers=headers,
            ).status_code == 204
        finally:
            app.dependency_overrides.clear()


def test_image_job_api_composes_selected_prompt_tags_on_backend(monkeypatch):
    with db_session() as session:
        ai_service = FakeAIService([{"url": "https://cdn.example.test/generated.png"}])
        service = WorkflowService(session, ai_service=ai_service, storage=FakeStorage())
        app.dependency_overrides[get_service] = lambda: DBService(session)
        app.dependency_overrides[get_generation_jobs] = lambda: service
        app.dependency_overrides[get_generation_scheduler] = lambda: InlineWorkflowScheduler(service)

        def run_image(job_type, job_id, session_factory):  # noqa: ARG001
            return service.run_job(job_type, job_id)

        monkeypatch.setattr(WorkflowService, "run_in_new_session", run_image)

        try:
            client = TestClient(app)
            headers = _auth_headers(client)
            account_id = client.get("/api/v1/accounts", headers=headers).json()[0]["id"]

            created = client.post(
                f"/api/v1/accounts/{account_id}/generation/image-jobs",
                json={
                    "prompt": "未来城市街头的女孩",
                    "selectedTagIds": ["photography", "8k"],
                    "negativePrompt": "低清晰度",
                    "count": 1,
                    "ratio": "1:1",
                },
                headers=headers,
            )

            assert created.status_code == 200
            job_id = created.json()["id"]

            fetched = client.get(f"/api/v1/accounts/{account_id}/generation/jobs/{job_id}", headers=headers)
            assert fetched.status_code == 200
            payload = fetched.json()
            assert payload["prompt"] == (
                "未来城市街头的女孩，超现实、高分辨率的照片，皮肤完美光滑，眼睛细节丰富，"
                "光线自然，专业影棚布光，电影级画质，超细节，4K，"
                "8K ultra HD，extremely detailed，high resolution"
            )
            assert payload["inputPayload"]["basePrompt"] == "未来城市街头的女孩"
            assert payload["inputPayload"]["selectedTagIds"] == ["photography", "8k"]
            assert payload["inputPayload"]["negativePrompt"] == "低清晰度"
            assert ai_service.image_generation_inputs[0]["prompt"] == payload["prompt"]
        finally:
            app.dependency_overrides.clear()
