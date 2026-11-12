import asyncio
import pytest
from sqlalchemy import event
from sqlalchemy.exc import OperationalError
from app.core.config import settings
from app.db.models import WorkflowStepRecord
from app.services.extract_service.video_audio_preprocessing import (
    PreparedVideoAudio,
    VideoAudioSegment,
)
from app.services.workflow.workflows.video_analysis import (
    normalize_video_analysis_result,
    offset_video_analysis_result,
)
from app.schemas.extract import CreateVideoAnalysisWorkflowRequest
from app.services.workflow import WorkflowService
from sqlalchemy.orm import sessionmaker
from tests.db_test_utils import db_session


MANAGED_VIDEO_URL = f"{settings.object_storage_public_base_url}/extract/video.mp4"


@pytest.fixture(autouse=True)
def use_filetrans_for_exact_timeline_tests(monkeypatch):
    monkeypatch.setattr(settings, "video_analysis_use_filetrans", True)


class FakeVideoAnalysisAIService:
    token = "fake-token"

    async def speech_filetrans(self, **kwargs):
        return _filetrans_payload("开场钩子", 0, 60000, emotion="surprised")

    async def chat_completion(self, **kwargs):
        return (
            '{"shotBreakdown":[{"shot":1,"timeRange":"00:00-01:00",'
            '"script":"开场钩子","visualContent":"创作画面"}],"replicationPrompt":"复刻提示词"}'
        )


class RetryVideoAnalysisAIService:
    token = "fake-token"

    def __init__(self):
        self.audio_calls = []
        self.text_calls = []

    async def speech_filetrans(self, **kwargs):
        self.audio_calls.append(kwargs)
        return _filetrans_payload("开场钩子", 0, 60000)

    async def chat_completion(self, **kwargs):
        self.text_calls.append(kwargs)
        if len(self.text_calls) == 1:
            return '{"shotBreakdown": ['
        return '{"videoScript":[{"timeRange":"00:00-00:03","text":"重试成功"}]}'


class RecordingVideoAnalysisAIService(FakeVideoAnalysisAIService):
    def __init__(self):
        self.calls = []

    async def speech_filetrans(self, **kwargs):
        self.calls.append(kwargs)
        return await super().speech_filetrans(**kwargs)


class FlashFallbackVideoAnalysisAIService:
    token = "fake-token"

    def __init__(self):
        self.audio_calls = []

    async def speech_discern(self, **kwargs):
        self.audio_calls.append(kwargs)
        return "第一句。第二句！"

    async def chat_completion(self, **kwargs):
        return '{"shotBreakdown":[],"replicationPrompt":"降级结果"}'


def _filetrans_payload(text, begin_ms, end_ms, *, emotion="neutral"):  # noqa: ANN001
    return {
        "transcripts": [{
            "text": text,
            "sentences": [{
                "begin_time": begin_ms,
                "end_time": end_ms,
                "text": text,
                "emotion": emotion,
                "language": "zh",
                "words": [{
                    "begin_time": begin_ms,
                    "end_time": end_ms,
                    "text": text,
                    "punctuation": "",
                }],
            }],
        }],
    }


class DirectVideoPreprocessor:
    def __init__(self, storage):  # noqa: ANN001
        self.storage = storage

    def prepare(self, video_url, **kwargs):  # noqa: ANN001, ARG002
        audio_url = video_url.split("?", 1)[0].removesuffix(".mp4") + ".mp3"
        return PreparedVideoAudio(
            audio_url=audio_url,
            duration_seconds=60,
            size_bytes=1024,
            segments=(VideoAudioSegment(0, audio_url, 0, 60),),
        )


def _use_direct_video_preprocessor(monkeypatch):
    monkeypatch.setattr(
        "app.services.workflow.workflows.video_analysis.VideoAudioPreprocessor",
        DirectVideoPreprocessor,
    )


def test_normalize_video_analysis_result_fills_missing_sections():
    result = normalize_video_analysis_result(
        {
            "videoScript": [{"timeRange": "00:00-00:03", "text": "开场钩子"}],
            "publishCopy": "随机挑战的一日三餐，结局比想象中更离谱。",
            "replicationPrompt": "复刻提示词",
        }
    )

    assert result["videoScript"][0]["timeRange"] == "00:00-00:03"
    assert result["videoScript"][0]["text"] == "开场钩子"
    assert result["shotBreakdown"] == []
    assert result["rewriteReferences"] == []
    assert result["publishCopy"] == "随机挑战的一日三餐，结局比想象中更离谱。"
    assert result["replicationPrompt"] == "复刻提示词"


def test_video_analysis_job_runs_in_new_session(monkeypatch):
    _use_direct_video_preprocessor(monkeypatch)
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
        assert refreshed.resultPayload.audioTimeline[0].timeRange == "00:00.000-01:00.000"
        assert refreshed.resultPayload.audioTimeline[0].emotion == "surprised"
        assert refreshed.resultPayload.audioTimeline[0].emotionLabel == "惊讶"
        assert refreshed.resultPayload.sourceAudioUrl.endswith(".mp3")


def test_video_analysis_job_uses_flash_fallback_when_filetrans_is_disabled(monkeypatch):
    monkeypatch.setattr(settings, "video_analysis_use_filetrans", False)
    _use_direct_video_preprocessor(monkeypatch)
    with db_session() as session:
        service = WorkflowService(session)
        created = service.create_video_analysis_job(
            "u_001",
            CreateVideoAnalysisWorkflowRequest(
                accountId="acc1",
                videoUrl=MANAGED_VIDEO_URL,
                title="降级转写",
            ),
        )
        session_factory = sessionmaker(bind=session.get_bind())
        ai_service = FlashFallbackVideoAnalysisAIService()

        WorkflowService.run_in_new_session(
            "video_analysis",
            created.id,
            session_factory,
            ai_service,
        )

        refreshed = service.get_video_analysis_job("u_001", created.id)
        assert refreshed.status == "completed"
        assert [line.text for line in refreshed.resultPayload.audioTimeline] == [
            "第一句。",
            "第二句！",
        ]
        assert [line.timeRange for line in refreshed.resultPayload.audioTimeline] == [
            "00:00.000-00:30.000",
            "00:30.000-01:00.000",
        ]
        assert all(line.emotion == "neutral" for line in refreshed.resultPayload.audioTimeline)
        assert ai_service.audio_calls[0]["model"] == "qwen3-asr-flash"


def test_video_analysis_job_repairs_malformed_json_without_resending_video(monkeypatch):
    _use_direct_video_preprocessor(monkeypatch)
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
        assert refreshed.resultPayload.videoScript[0].text == "开场钩子"
        assert len(ai_service.audio_calls) == 1
        assert len(ai_service.text_calls) == 2
        assert ai_service.text_calls[1]["temperature"] == 0.1


def test_video_analysis_job_persists_external_video_before_ai(monkeypatch):
    _use_direct_video_preprocessor(monkeypatch)
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
        assert ai_service.calls[0]["audio_url"].endswith("/persisted.mp3")


def test_video_analysis_job_falls_back_to_original_video_when_persistence_fails(monkeypatch):
    _use_direct_video_preprocessor(monkeypatch)
    external_url = "http://cdn.example.test/large-video.mp4?sign=temporary"

    class FailingPersistenceService:
        def __init__(self, storage):  # noqa: ANN001
            self.storage = storage

        def persist(self, video_url, **kwargs):  # noqa: ANN001, ARG002
            assert video_url == external_url
            raise RuntimeError("video source exceeds 83886080 bytes")

    monkeypatch.setattr(
        "app.services.workflow.workflows.video_analysis.VideoSourcePersistenceService",
        FailingPersistenceService,
    )

    with db_session() as session:
        service = WorkflowService(session)
        created = service.create_video_analysis_job(
            "u_001",
            CreateVideoAnalysisWorkflowRequest(
                accountId="acc1",
                sourceUrl="https://www.xiaohongshu.com/explore/note-large",
                videoUrl=external_url,
                title="大视频原片",
            ),
        )
        session_factory = sessionmaker(bind=session.get_bind())
        ai_service = RecordingVideoAnalysisAIService()

        WorkflowService.run_in_new_session("video_analysis", created.id, session_factory, ai_service)

        refreshed = service.get_video_analysis_job("u_001", created.id)
        assert refreshed.status == "completed"
        assert refreshed.videoUrl == external_url
        assert ai_service.calls[0]["audio_url"].endswith("/large-video.mp3")


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


def test_video_analysis_job_does_not_query_parent_record_during_ai_call(monkeypatch):
    _use_direct_video_preprocessor(monkeypatch)
    with db_session() as session:
        fail_parent_select = False

        class TransactionGuardAIService(FakeVideoAnalysisAIService):
            async def speech_filetrans(self, **kwargs):
                nonlocal fail_parent_select
                fail_parent_select = False
                return await super().speech_filetrans(**kwargs)

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


def test_video_analysis_job_analyzes_segments_and_offsets_timeline(monkeypatch):
    persisted_url = f"{settings.object_storage_public_base_url}/extract/video-analysis/long.mp4"
    segment_urls = [
        f"{settings.object_storage_public_base_url}/extract/video-analysis/audio-segment-1.mp3",
        f"{settings.object_storage_public_base_url}/extract/video-analysis/audio-segment-2.mp3",
    ]

    class SegmentedPreprocessor:
        def __init__(self, storage):  # noqa: ANN001
            self.storage = storage

        def prepare(self, video_url, **kwargs):  # noqa: ANN001, ARG002
            assert video_url == persisted_url
            return PreparedVideoAudio(
                audio_url=f"{settings.object_storage_public_base_url}/extract/video-analysis/source-audio.mp3",
                duration_seconds=150,
                size_bytes=100 * 1024 * 1024,
                segments=(
                    VideoAudioSegment(0, segment_urls[0], 0, 90),
                    VideoAudioSegment(1, segment_urls[1], 90, 60),
                ),
            )

    class SegmentAIService:
        token = "fake-token"

        def __init__(self):
            self.audio_calls = []
            self.text_calls = []
            self.active_audio_calls = 0
            self.max_active_audio_calls = 0

        async def speech_filetrans(self, **kwargs):
            self.audio_calls.append(kwargs)
            self.active_audio_calls += 1
            self.max_active_audio_calls = max(
                self.max_active_audio_calls,
                self.active_audio_calls,
            )
            try:
                await asyncio.sleep(0.01)
                index = segment_urls.index(kwargs["audio_url"]) + 1
                duration_ms = 90000 if index == 1 else 60000
                emotion = "happy" if index == 1 else "sad"
                return _filetrans_payload(f"片段{index}", 0, duration_ms, emotion=emotion)
            finally:
                self.active_audio_calls -= 1

        async def chat_completion(self, **kwargs):
            self.text_calls.append(kwargs)
            return (
                '{"shotBreakdown":[{"shot":1,"timeRange":"00:00-01:30","script":"片段1"},'
                '{"shot":2,"timeRange":"01:30-02:30","script":"片段2"}]}'
            )

    monkeypatch.setattr(
        "app.services.workflow.workflows.video_analysis.VideoAudioPreprocessor",
        SegmentedPreprocessor,
    )

    with db_session() as session:
        service = WorkflowService(session)
        created = service.create_video_analysis_job(
            "u_001",
            CreateVideoAnalysisWorkflowRequest(
                accountId="acc1",
                videoUrl=persisted_url,
                title="长视频",
            ),
        )
        session_factory = sessionmaker(bind=session.get_bind())
        ai_service = SegmentAIService()

        WorkflowService.run_in_new_session("video_analysis", created.id, session_factory, ai_service)

        refreshed = service.get_video_analysis_job("u_001", created.id)
        assert refreshed.status == "completed"
        assert [item.timeRange for item in refreshed.resultPayload.videoScript] == [
            "00:00.000-01:30.000",
            "01:30.000-02:30.000",
        ]
        assert [item.emotion for item in refreshed.resultPayload.videoScript] == ["happy", "sad"]
        assert [item.shot for item in refreshed.resultPayload.shotBreakdown] == [1, 2]
        assert len(ai_service.audio_calls) == 2
        assert ai_service.max_active_audio_calls == 2
        assert len(ai_service.text_calls) == 1
        steps = (
            session.query(WorkflowStepRecord)
            .filter(WorkflowStepRecord.workflow_id == created.id)
            .order_by(WorkflowStepRecord.sort_order)
            .all()
        )
        assert [step.type for step in steps] == [
            "audio_transcription_segment",
            "audio_transcription_segment",
            "storyboard_generation",
        ]
        assert [step.status for step in steps] == ["completed", "completed", "completed"]


def test_offset_video_analysis_result_supports_hour_timestamps():
    result = offset_video_analysis_result(
        {
            "videoScript": [{"timeRange": "00:20-00:30", "text": "片段"}],
            "shotBreakdown": [{"shot": 1, "timeRange": "00:20-00:30"}],
        },
        3590,
    )

    assert result["videoScript"][0]["timeRange"] == "01:00:10-01:00:20"
    assert result["shotBreakdown"][0]["timeRange"] == "01:00:10-01:00:20"
