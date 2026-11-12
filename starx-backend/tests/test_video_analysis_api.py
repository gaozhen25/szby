import json

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_ai_service, get_service
from app.api.routes.extract import get_video_analysis_scheduler
from app.core.config import settings
from app.core.security import create_access_token, get_password_hash
from app.db.models import UserRecord
from app.main import app
from app.services.db_service import DBService
from app.services.extract_service.video_audio_preprocessing import (
    PreparedVideoAudio,
    VideoAudioSegment,
)
from app.services.workflow import WorkflowService
from tests.db_test_utils import db_session
from tests.test_api_flows import auth_headers


MANAGED_VIDEO_URL = f"{settings.object_storage_public_base_url}/extract/video.mp4"


class FakeVideoAnalysisAIService:
    token = "fake-token"

    async def speech_filetrans(self, **kwargs):
        return {
            "transcripts": [{
                "text": "开场钩子",
                "sentences": [{
                    "begin_time": 0,
                    "end_time": 3000,
                    "text": "开场钩子",
                    "emotion": "surprised",
                    "language": "zh",
                    "words": [],
                }],
            }],
        }

    async def chat_completion(self, **kwargs):
        return json.dumps(
            {
                "shotBreakdown": [{"shot": 1, "timeRange": "00:00-00:03", "script": "开场钩子"}],
                "rewriteReferences": [{"title": "原结构复刻版", "rhythm": "悬念开场", "script": ["仿写脚本"]}],
                "publishCopy": "随机挑战的一日三餐，结局比想象中更离谱。",
                "replicationPrompt": "复刻提示词",
            },
            ensure_ascii=False,
        )


class FakeAudioPreprocessor:
    def __init__(self, storage):  # noqa: ANN001
        self.storage = storage

    def prepare(self, video_url, **kwargs):  # noqa: ANN001, ARG002
        audio_url = video_url.removesuffix(".mp4") + ".mp3"
        return PreparedVideoAudio(
            audio_url=audio_url,
            duration_seconds=3,
            size_bytes=1024,
            segments=(VideoAudioSegment(0, audio_url, 0, 3),),
        )


@pytest.fixture(autouse=True)
def use_fake_audio_preprocessor(monkeypatch):
    monkeypatch.setattr(settings, "video_analysis_use_filetrans", True)
    monkeypatch.setattr(
        "app.services.workflow.workflows.video_analysis.VideoAudioPreprocessor",
        FakeAudioPreprocessor,
    )


class InlineVideoAnalysisScheduler:
    def __init__(self, session, ai_service):  # noqa: ANN001
        self.session = session
        self.ai_service = ai_service

    def submit(self, job_type: str, job_id: str, context=None) -> None:  # noqa: ANN001, ARG002
        WorkflowService(self.session, ai_service=self.ai_service).run_job(job_type, job_id)


def test_video_analysis_job_api_creates_runs_and_lists_by_owner():
    with db_session() as session:
        ai_service = FakeVideoAnalysisAIService()
        app.dependency_overrides[get_service] = lambda: DBService(session)
        app.dependency_overrides[get_ai_service] = lambda: ai_service
        app.dependency_overrides[get_video_analysis_scheduler] = lambda: InlineVideoAnalysisScheduler(session, ai_service)

        try:
            client = TestClient(app)
            headers = auth_headers(client)
            account_id = client.get("/api/v1/accounts", headers=headers).json()[0]["id"]
            creation_id = "manual_video_analysis_1"

            created = client.post(
                "/api/v1/extract/video-analysis-jobs",
                headers=headers,
                json={
                    "accountId": account_id,
                    "creationId": creation_id,
                    "sourceUrl": "https://www.douyin.com/video/123",
                    "videoUrl": MANAGED_VIDEO_URL,
                    "coverUrl": "https://oss.example.test/cover.webp",
                    "platform": "抖音",
                    "title": "会飞的鱼",
                    "description": "花一百万做了一条会飞的鱼",
                },
            )

            assert created.status_code == 200
            job = created.json()
            assert job["status"] == "pending"
            assert job["accountId"] == account_id
            assert job["creationId"] == creation_id

            fetched = client.get(f"/api/v1/extract/video-analysis-jobs/{job['id']}", headers=headers)
            assert fetched.status_code == 200
            assert fetched.json()["id"] == job["id"]
            assert fetched.json()["status"] == "completed"
            assert fetched.json()["resultPayload"]["videoScript"][0]["text"] == "开场钩子"
            assert fetched.json()["resultPayload"]["publishCopy"] == "随机挑战的一日三餐，结局比想象中更离谱。"
            assert fetched.json()["resultPayload"]["replicationPrompt"] == "复刻提示词"

            listed = client.get(
                f"/api/v1/extract/video-analysis-jobs?accountId={account_id}&creationId={creation_id}",
                headers=headers,
            )
            assert listed.status_code == 200
            assert [item["id"] for item in listed.json()] == [job["id"]]
        finally:
            app.dependency_overrides.clear()


def test_video_analysis_job_api_rejects_other_users_job():
    with db_session() as session:
        ai_service = FakeVideoAnalysisAIService()
        session.add(
            UserRecord(
                id="u_other_video",
                email="other-video@starx.ai",
                password_hash=get_password_hash("secret123"),
                nickname="Other User",
                status="active",
            )
        )
        session.commit()
        app.dependency_overrides[get_service] = lambda: DBService(session)
        app.dependency_overrides[get_ai_service] = lambda: ai_service
        app.dependency_overrides[get_video_analysis_scheduler] = lambda: InlineVideoAnalysisScheduler(session, ai_service)

        try:
            client = TestClient(app)
            headers = auth_headers(client)
            created = client.post(
                "/api/v1/extract/video-analysis-jobs",
                headers=headers,
                json={"videoUrl": MANAGED_VIDEO_URL, "title": "会飞的鱼"},
            )
            assert created.status_code == 200

            other_headers = {"Authorization": f"Bearer {create_access_token('u_other_video')}"}
            fetched = client.get(
                f"/api/v1/extract/video-analysis-jobs/{created.json()['id']}",
                headers=other_headers,
            )
            assert fetched.status_code == 404
        finally:
            app.dependency_overrides.clear()


def test_video_analysis_job_api_bounds_extracted_title_and_preserves_description():
    long_copy = "买暖宝宝就直接搜炸弹，关注我" * 40

    with db_session() as session:
        ai_service = FakeVideoAnalysisAIService()
        app.dependency_overrides[get_service] = lambda: DBService(session)
        app.dependency_overrides[get_ai_service] = lambda: ai_service
        app.dependency_overrides[get_video_analysis_scheduler] = lambda: InlineVideoAnalysisScheduler(session, ai_service)

        try:
            client = TestClient(app)
            created = client.post(
                "/api/v1/extract/video-analysis-jobs",
                headers=auth_headers(client),
                json={
                    "videoUrl": MANAGED_VIDEO_URL,
                    "title": long_copy,
                    "description": long_copy,
                },
            )

            assert created.status_code == 200
            assert created.json()["title"] == long_copy[:255]
            assert created.json()["description"] == long_copy
        finally:
            app.dependency_overrides.clear()
