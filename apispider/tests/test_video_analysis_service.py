from sqlalchemy import event
from sqlalchemy.exc import OperationalError
from app.core.config import settings
from app.services.workflow.workflows.video_analysis import normalize_video_analysis_result
from app.schemas.extract import CreateVideoAnalysisWorkflowRequest
from app.services.workflow import WorkflowService
from sqlalchemy.orm import sessionmaker
from tests.db_test_utils import db_session


MANAGED_VIDEO_URL = f"{settings.object_storage_public_base_url}/extract/video.mp4"


class FakeVideoAnalysisAIService:
    token = "fake-token"

    async def video_view(self, **kwargs):
        return '{"videoScript":[{"timeRange":"00:00-00:03","text":"开场钩子"}],"replicationPrompt":"复刻提示词"}'


class RetryVideoAnalysisAIService:
    token = "fake-token"

    def __init__(self):
        self.calls = []

    async def video_view(self, **kwargs):
        self.calls.append(kwargs)
        if len(self.calls) == 1:
            return '{"videoScript": ['
        return '{"videoScript":[{"timeRange":"00:00-00:03","text":"重试成功"}]}'


class RecordingVideoAnalysisAIService(FakeVideoAnalysisAIService):
    def __init__(self):
        self.calls = []

    async def video_view(self, **kwargs):
        self.calls.append(kwargs)
        return await super().video_view(**kwargs)


def test_normalize_video_analysis_result_fills_missing_sections():
    result = normalize_video_analysis_result(
        {
            "videoScript": [{"timeRange": "00:00-00:03", "text": "开场钩子"}],
            "publishCopy": "随机挑战的一日三餐，结局比想象中更离谱。",
            "replicationPrompt": "复刻提示词",
        }
    )

    assert result["videoScript"] == [{"timeRange": "00:00-00:03", "text": "开场钩子"}]
    assert result["shotBreakdown"] == []
    assert result["rewriteReferences"] == []
    assert result["publishCopy"] == "随机挑战的一日三餐，结局比想象中更离谱。"
    assert result["replicationPrompt"] == "复刻提示词"


def test_video_analysis_job_runs_in_new_session():
    with db_session() as session:
        service = WorkflowService(session)
        created = service.create_video_analysis_job(
            "u_001",
            CreateVideoAnalysisWorkflowRequest(
                accountId="acc1",
                videoUrl=MANAGED_VIDEO_URL,
                title="会飞的鱼",
            ),
        )
        session_factory = sessionmaker(bind=session.get_bind())

        WorkflowService.run_in_new_session("video_analysis", created.id, session_factory, FakeVideoAnalysisAIService())

        refreshed = service.get_video_analysis_job("u_001", created.id)
        assert refreshed.status == "completed"
        assert refreshed.resultPayload.videoScript[0].text == "开场钩子"


def test_video_analysis_job_retries_malformed_json_once():
    with db_session() as session:
        service = WorkflowService(session)
        created = service.create_video_analysis_job(
            "u_001",
            CreateVideoAnalysisWorkflowRequest(
                accountId="acc1",
                videoUrl=MANAGED_VIDEO_URL,
                title="会飞的鱼",
            ),
        )
        session_factory = sessionmaker(bind=session.get_bind())
        ai_service = RetryVideoAnalysisAIService()

        WorkflowService.run_in_new_session("video_analysis", created.id, session_factory, ai_service)

        refreshed = service.get_video_analysis_job("u_001", created.id)
        assert refreshed.status == "completed"
        assert refreshed.resultPayload.videoScript[0].text == "重试成功"
        assert len(ai_service.calls) == 2
        assert ai_service.calls[1]["temperature"] == 0.1


def test_video_analysis_job_persists_external_video_before_ai(monkeypatch):
    external_url = "http://cdn.example.test/video.mp4?sign=temporary"
    persisted_url = f"{settings.object_storage_public_base_url}/extract/video-analysis/persisted.mp4"

    class FakePersistenceService:
        def __init__(self, storage):  # noqa: ANN001
            self.storage = storage

        def persist(self, video_url, **kwargs):  # noqa: ANN001
            assert video_url == external_url
            assert kwargs["source_url"] == "https://www.xiaohongshu.com/explore/note-1"
            assert kwargs["owner_id"] == "acc1"
            return persisted_url

    monkeypatch.setattr(
        "app.services.workflow.workflows.video_analysis.VideoSourcePersistenceService",
        FakePersistenceService,
    )

    with db_session() as session:
        service = WorkflowService(session)
        created = service.create_video_analysis_job(
            "u_001",
            CreateVideoAnalysisWorkflowRequest(
                accountId="acc1",
                sourceUrl="https://www.xiaohongshu.com/explore/note-1",
                videoUrl=external_url,
                title="会飞的鱼",
            ),
        )
        session_factory = sessionmaker(bind=session.get_bind())
        ai_service = RecordingVideoAnalysisAIService()

        WorkflowService.run_in_new_session("video_analysis", created.id, session_factory, ai_service)

        refreshed = service.get_video_analysis_job("u_001", created.id)
        assert refreshed.status == "completed"
        assert refreshed.videoUrl == persisted_url
        assert ai_service.calls[0]["video_url"] == persisted_url


def test_video_analysis_job_bounds_extracted_title_without_truncating_description():
    long_copy = "人工智能培训避坑指南" * 40

    with db_session() as session:
        created = WorkflowService(session).create_video_analysis_job(
            "u_001",
            CreateVideoAnalysisWorkflowRequest(
                accountId="acc1",
                videoUrl=MANAGED_VIDEO_URL,
                title=long_copy,
                description=long_copy,
            ),
        )

        assert created.title == long_copy[:255]
        assert created.description == long_copy


def test_video_analysis_job_does_not_query_parent_record_during_ai_call():
    with db_session() as session:
        fail_parent_select = False

        class TransactionGuardAIService(FakeVideoAnalysisAIService):
            async def video_view(self, **kwargs):
                nonlocal fail_parent_select
                fail_parent_select = False
                return await super().video_view(**kwargs)

        @event.listens_for(session.get_bind(), "before_cursor_execute")
        def _fail_parent_select(conn, cursor, statement, parameters, context, executemany):  # noqa: ANN001, ARG001
            nonlocal fail_parent_select
            if statement.startswith("UPDATE video_analysis_jobs") and "running" in str(parameters):
                fail_parent_select = True
            if fail_parent_select and statement.startswith("SELECT") and "video_analysis_jobs" in statement:
                raise OperationalError(statement, parameters, RuntimeError("query timeout"))

        service = WorkflowService(session)
        created = service.create_video_analysis_job(
            "u_001",
            CreateVideoAnalysisWorkflowRequest(
                accountId="acc1",
                videoUrl=MANAGED_VIDEO_URL,
                title="会飞的鱼",
            ),
        )
        session_factory = sessionmaker(bind=session.get_bind())

        WorkflowService.run_in_new_session("video_analysis", created.id, session_factory, TransactionGuardAIService())

        fail_parent_select = False
        refreshed = service.get_video_analysis_job("u_001", created.id)
        assert refreshed.status == "completed"
