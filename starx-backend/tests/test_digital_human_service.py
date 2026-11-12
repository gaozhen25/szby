import pytest
from sqlalchemy import event

from app.db.models import DigitalHumanProfileRecord, WorkflowExternalTaskRecord, WorkflowRecord
from app.services.digital_human.service import (
    DIGITAL_HUMAN_ENROLLMENT_TYPE,
    DIGITAL_HUMAN_VIDEO_TYPE,
    DigitalHumanService,
)
from app.services.digital_human.training_script import DEFAULT_TRAINING_SCRIPT
from app.services.workflow.service import WorkflowService
from tests.db_test_utils import db_session
from tests.test_generation_jobs import FakeStorage


class RecordingScheduler:
    def __init__(self) -> None:
        self.submissions: list[tuple[str, str]] = []

    def submit(self, workflow_type: str, workflow_id: str, context=None) -> None:  # noqa: ANN001, ARG002
        self.submissions.append((workflow_type, workflow_id))


class TransactionCheckingStorage(FakeStorage):
    def __init__(self, session) -> None:  # noqa: ANN001
        super().__init__()
        self.session = session
        self.upload_started_without_transaction = False

    def put_bytes(self, key: str, data: bytes, content_type: str) -> str:
        self.upload_started_without_transaction = not self.session.in_transaction()
        return super().put_bytes(key, data, content_type)


def test_training_video_minimum_duration_is_ten_seconds():
    assert DEFAULT_TRAINING_SCRIPT.min_duration_seconds == 10


def test_create_profile_persists_owned_asset_and_enrollment_workflow():
    with db_session() as session:
        insert_order: list[str] = []

        def record_insert(_conn, _cursor, statement, _parameters, _context, _executemany):
            normalized = statement.lower()
            if normalized.startswith("insert into workflows"):
                insert_order.append("workflow")
            elif normalized.startswith("insert into digital_human_profiles"):
                insert_order.append("profile")

        event.listen(session.bind, "before_cursor_execute", record_insert)
        storage = TransactionCheckingStorage(session)
        scheduler = RecordingScheduler()
        service = DigitalHumanService(session, storage=storage, scheduler=scheduler)

        try:
            profile, workflow = service.create_profile(
                user_id="u_001",
                account_id="acc1",
                name="创始人数字分身",
                filename="source.mp4",
                content_type="video/mp4",
                source_video_url="https://oss.example.test/direct/source.mp4",
                source_video_storage_key="direct/source.mp4",
                source_video_size_bytes=11,
                training_script_version="zh_cn_v1",
                consent_confirmed=True,
            )
        finally:
            event.remove(session.bind, "before_cursor_execute", record_insert)

        assert profile.status == "validating"
        assert profile.training_script_version == "zh_cn_v1"
        assert profile.source_video_url == "https://oss.example.test/direct/source.mp4"
        assert workflow.type == DIGITAL_HUMAN_ENROLLMENT_TYPE
        assert workflow.input_payload["profileId"] == profile.id
        assert scheduler.submissions == [(DIGITAL_HUMAN_ENROLLMENT_TYPE, workflow.id)]
        assert storage.objects == {}
        assert insert_order.index("workflow") < insert_order.index("profile")
        assert session.get(DigitalHumanProfileRecord, profile.id) is not None


def test_create_video_workflow_requires_ready_profile_and_is_durable():
    with db_session() as session:
        service = DigitalHumanService(
            session, storage=FakeStorage(), scheduler=RecordingScheduler()
        )
        profile, _ = service.create_profile(
            user_id="u_001",
            account_id="acc1",
            name="讲解员",
            filename="source.mp4",
            content_type="video/mp4",
            source_video_url="https://oss.example.test/direct/source.mp4",
            source_video_storage_key="direct/source.mp4",
            source_video_size_bytes=11,
            training_script_version="zh_cn_v1",
            consent_confirmed=True,
        )
        profile.status = "ready"
        profile.voice_status = "ready"
        profile.provider_voice_id = "voice_test"
        session.commit()

        workflow = service.create_video_workflow(
            user_id="u_001",
            account_id="acc1",
            profile_id=profile.id,
            creation_id="creation_test",
            title="产品口播",
            script_text="这是一段新的口播文案。",
            speed=1.0,
            subtitles_enabled=True,
            background_url="https://cdn.test/background.jpg",
            bubble_url="https://cdn.test/bubble.png",
            background_music_url="https://cdn.test/bgm.mp3",
            background_music_gain=0.12,
            idempotency_key="request-1",
        )

        external = session.get(WorkflowExternalTaskRecord, workflow.id)
        assert workflow.type == DIGITAL_HUMAN_VIDEO_TYPE
        assert workflow.status == "pending"
        assert workflow.current_stage == "preparing_voice"
        assert external is not None
        assert external.provider == "kyy"
        assert external.provider_task_id == ""
        assert workflow.input_payload["editing"] == {
            "subtitlesEnabled": True,
            "backgroundUrl": "https://cdn.test/background.jpg",
            "bubbleUrl": "https://cdn.test/bubble.png",
            "backgroundMusicUrl": "https://cdn.test/bgm.mp3",
            "backgroundMusicGain": 0.12,
        }

        duplicate = service.create_video_workflow(
            user_id="u_001",
            account_id="acc1",
            profile_id=profile.id,
            creation_id="creation_test",
            title="产品口播",
            script_text="这是一段新的口播文案。",
            speed=1.0,
            idempotency_key="request-1",
        )
        assert duplicate.id == workflow.id
        other_workflow = service.create_video_workflow(
            user_id="u_001",
            account_id="acc1",
            profile_id=profile.id,
            creation_id="creation_other",
            title="另一条口播",
            script_text="另一段测试文案。",
            speed=1.0,
            idempotency_key="request-2",
        )
        assert (
            session.query(WorkflowRecord)
            .filter(WorkflowRecord.type == DIGITAL_HUMAN_VIDEO_TYPE)
            .count()
            == 2
        )
        history = WorkflowService(session).list_jobs(
            "u_001",
            "acc1",
            page=1,
            limit=100,
            job_type=DIGITAL_HUMAN_VIDEO_TYPE,
        )
        assert {item.id for item in history} == {workflow.id, other_workflow.id}

        page_items, total, page, page_size = WorkflowService(session).list_jobs_page(
            "u_001",
            "acc1",
            page=2,
            page_size=1,
            job_type=DIGITAL_HUMAN_VIDEO_TYPE,
        )
        assert len(page_items) == 1
        assert total == 2
        assert page == 2
        assert page_size == 1

        creation_items, creation_total, _, _ = WorkflowService(session).list_jobs_page(
            "u_001",
            "acc1",
            page=1,
            page_size=4,
            job_type=DIGITAL_HUMAN_VIDEO_TYPE,
            creation_id="creation_test",
        )
        assert [item.id for item in creation_items] == [workflow.id]
        assert creation_total == 1


def test_create_video_workflow_rejects_gain_outside_aliyun_range():
    with db_session() as session:
        service = DigitalHumanService(
            session, storage=FakeStorage(), scheduler=RecordingScheduler()
        )
        profile, _ = service.create_profile(
            user_id="u_001",
            account_id="acc1",
            name="讲解员",
            filename="source.mp4",
            content_type="video/mp4",
            source_video_url="https://oss.example.test/direct/source.mp4",
            source_video_storage_key="direct/source.mp4",
            source_video_size_bytes=11,
            training_script_version="zh_cn_v1",
            consent_confirmed=True,
        )
        profile.status = "ready"
        profile.provider_voice_id = "voice_test"
        session.commit()

        with pytest.raises(ValueError, match="Gain"):
            service.create_video_workflow(
                user_id="u_001",
                account_id="acc1",
                profile_id=profile.id,
                creation_id="",
                title="产品口播",
                script_text="测试文案",
                speed=1,
                background_music_gain=-1,
                idempotency_key="invalid-gain",
            )
