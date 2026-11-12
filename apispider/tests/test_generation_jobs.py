import asyncio
import base64
import json
import logging
from dataclasses import dataclass

import httpx
import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from app.db.base import Base
from app.db.models import AccountRecord, GenerationAssetRecord, KnowledgeBaseRecord, WorkflowRecord, WorkflowStepRecord, UserRecord
from app.services.workflow import WorkflowService


@dataclass
class FakeUpload:
    filename: str
    content_type: str
    data: bytes

    def read(self) -> bytes:
        return self.data


class FakeAIService:
    def __init__(self, image_results: list[dict[str, str]] | None = None) -> None:
        self.image_results = image_results or [
            {"url": "https://cdn.example.test/generated-1.png"},
            {"url": "https://cdn.example.test/generated-2.png"},
        ]
        self.image_view_inputs: list[str] = []
        self.chat_completion_inputs: list[str] = []
        self.image_generation_inputs: list[dict[str, object]] = []
        self.image_edit_inputs: list[dict[str, object]] = []

    async def image_view(self, prompt: str, image_url: str) -> str:  # noqa: ARG002
        self.image_view_inputs.append(image_url)
        return "reference image analysis"

    async def chat_completion(self, messages, system_prompt=None, temperature=0.7):  # noqa: ANN001, ARG002
        self.chat_completion_inputs.append(str(messages[0]["content"]))
        return "generated image prompt text"

    async def image_generation(  # noqa: ANN001, ARG002
        self,
        model,
        prompt: str,
        size: str,
        n: int,
        input_reference=None,
        extra_body=None,
    ):
        start = len(self.image_generation_inputs)
        self.image_generation_inputs.append(
            {"prompt": prompt, "size": size, "n": n, "input_reference": input_reference, "extra_body": extra_body}
        )
        return self.image_results[start : start + n]

    async def image_edit(  # noqa: ANN001, ARG002
        self,
        model,
        prompt: str,
        size: str,
        n: int,
        input_reference,
        extra_body=None,
    ):
        start = len(self.image_edit_inputs)
        self.image_edit_inputs.append(
            {"prompt": prompt, "size": size, "n": n, "input_reference": input_reference, "extra_body": extra_body}
        )
        return self.image_results[start : start + n]

    async def image_evaluation(self, **kwargs):  # noqa: ANN003
        return {"summary": "generated images match the unified style"}


class PerImagePromptAIService(FakeAIService):
    async def image_view(self, prompt: str, image_url: str) -> str:  # noqa: ARG002
        self.image_view_inputs.append(image_url)
        index = len(self.image_view_inputs)
        return f"reference image {index} analysis"

    async def chat_completion(self, messages, system_prompt=None, temperature=0.7):  # noqa: ANN001, ARG002
        self.chat_completion_inputs.append(str(messages[0]["content"]))
        return (
            '{"imagePrompts": ['
            '{"prompt": "rewritten prompt for image 1"}, '
            '{"prompt": "rewritten prompt for image 2"}, '
            '{"prompt": "rewritten prompt for image 3"}'
            "]}"
        )


class FailingImageViewAIService(FakeAIService):
    async def image_view(self, prompt: str, image_url: str) -> str:  # noqa: ARG002
        raise RuntimeError("vision service unavailable")


class TimeoutImageViewAIService(FakeAIService):
    async def image_view(self, prompt: str, image_url: str) -> str:  # noqa: ARG002
        raise httpx.ReadTimeout("")


class EmptyImageViewAIService(FakeAIService):
    async def image_view(self, prompt: str, image_url: str) -> str:  # noqa: ARG002
        return ""


class FailingChatAIService(FakeAIService):
    async def chat_completion(self, messages, system_prompt=None, temperature=0.7):  # noqa: ANN001, ARG002
        raise RuntimeError("prompt service unavailable")


class EmptyPromptAIService(FakeAIService):
    async def chat_completion(self, messages, system_prompt=None, temperature=0.7):  # noqa: ANN001, ARG002
        return ""


class TimeoutImageAIService(FakeAIService):
    async def image_generation(self, model, prompt: str, size: str, n: int):  # noqa: ANN001, ARG002
        raise httpx.ReadTimeout("")


class ConcurrentImageAIService(FakeAIService):
    def __init__(self) -> None:
        super().__init__([{"url": f"https://cdn.example.test/generated-{index}.png"} for index in range(20)])
        self.active = 0
        self.max_active = 0
        self._lock = asyncio.Lock()

    async def image_generation(self, model, prompt: str, size: str, n: int):  # noqa: ANN001, ARG002
        async with self._lock:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        try:
            await asyncio.sleep(0.001)
            return await super().image_generation(model, prompt, size, n)
        finally:
            async with self._lock:
                self.active -= 1


class LengthGuardPromptAIService(FakeAIService):
    async def image_view(self, prompt: str, image_url: str) -> str:  # noqa: ARG002
        return "参考图分析" * 5000

    async def chat_completion(self, messages, system_prompt=None, temperature=0.7):  # noqa: ANN001, ARG002
        content = str(messages[0]["content"])
        self.chat_completion_inputs.append(content)
        if len(content) > 32000:
            raise RuntimeError(f"prompt input too long: {len(content)}")
        return "generated image prompt text"


class MissingTokenAIService(FakeAIService):
    token = ""

    async def image_view(self, prompt: str, image_url: str) -> str:  # noqa: ARG002
        raise AssertionError("AI should not be called without a token")

    async def image_generation(self, model, prompt: str, size: str, n: int):  # noqa: ANN001, ARG002
        raise AssertionError("AI should not be called without a token")


class FakeStorage:
    def __init__(self, fail_on_put: int | None = None) -> None:
        self.objects: dict[str, tuple[bytes, str]] = {}
        self.deleted: list[str] = []
        self._put_count = 0
        self._fail_on_put = fail_on_put

    def put_bytes(self, key: str, data: bytes, content_type: str) -> str:
        self._put_count += 1
        if self._put_count == self._fail_on_put:
            raise RuntimeError("storage upload failed")
        self.objects[key] = (data, content_type)
        return f"http://localhost:9000/starx-assets/{key}"

    def delete_object(self, key: str) -> None:
        self.deleted.append(key)
        self.objects.pop(key, None)


class RemoteUrlStorage(FakeStorage):
    def put_bytes(self, key: str, data: bytes, content_type: str) -> str:
        self._put_count += 1
        if self._put_count == self._fail_on_put:
            raise RuntimeError("storage upload failed")
        self.objects[key] = (data, content_type)
        return f"https://oss.example.test/{key}"


@pytest.fixture(autouse=True)
def _disable_storage_upload_dir(monkeypatch):
    monkeypatch.setenv("OSS_UPLOAD_DIR", "")
    monkeypatch.setattr("app.services.workflow.workflows.generation_helpers.settings.object_storage_upload_dir", "")


def _engine():
    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection, connection_record):  # noqa: ARG001
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(bind=engine)
    return engine


def _seed_demo_account(session: Session) -> None:
    session.add(
        UserRecord(
            id="demo-user",
            email="demo-user@example.test",
            password_hash="not-used",
            nickname="Demo User",
            status="active",
        )
    )
    session.add(
        AccountRecord(
            id="acc1",
            user_id="demo-user",
            name="Beauty",
            avatar="美",
            account_type="专业号",
            platform="小红书",
            platforms=["小红书"],
            description="美妆测评",
            purpose="品牌合作",
            status="active",
        )
    )
    session.commit()


def test_prompt_job_persists_assets_and_prompt():
    engine = _engine()
    with Session(engine) as session:
        _seed_demo_account(session)
        service = WorkflowService(session, ai_service=FakeAIService(), storage=FakeStorage())

        created = service.create_prompt_job(
            user_id="demo-user",
            account_id="acc1",
            images=[FakeUpload("ref.png", "image/png", b"png-bytes")],
            copy_text="copy",
            target_platform="小红书",
            topic_title="topic",
        )

        completed = service.run_job("prompt", created.id)

        assert completed.status == "completed"
        assert "generated image prompt text" in completed.prompt
        assert len(completed.assets) == 1
        assert completed.assets[0].assetType == "reference"
        assert completed.assets[0].analysis == "reference image analysis"
        assert completed.assets[0].status == "completed"


def test_prompt_job_persists_image_analysis_sub_tasks():
    engine = _engine()
    with Session(engine) as session:
        _seed_demo_account(session)
        service = WorkflowService(session, ai_service=FakeAIService(), storage=FakeStorage())

        created = service.create_prompt_job(
            user_id="demo-user",
            account_id="acc1",
            images=[
                FakeUpload("ref-1.png", "image/png", b"png-bytes-1"),
                FakeUpload("ref-2.png", "image/png", b"png-bytes-2"),
            ],
            copy_text="copy",
            target_platform="小红书",
            topic_title="topic",
        )

        completed = service.run_job("prompt", created.id)
        sub_tasks = (
            session.query(WorkflowStepRecord)
            .filter(WorkflowStepRecord.parent_job_id == created.id)
            .order_by(WorkflowStepRecord.sort_order)
            .all()
        )

        assert completed.status == "completed"
        image_analysis_tasks = [task for task in sub_tasks if task.sub_type == "image_analysis"]
        assert [task.sub_type for task in image_analysis_tasks] == ["image_analysis", "image_analysis"]
        assert [task.status for task in image_analysis_tasks] == ["completed", "completed"]
        assert [task.result_payload["analysis"] for task in image_analysis_tasks] == [
            "reference image analysis",
            "reference image analysis",
        ]
        assert any(task.sub_type == "prompt_summary" and task.status == "completed" for task in sub_tasks)


def test_prompt_job_does_not_query_sub_tasks_while_ai_sub_jobs_are_running():
    engine = _engine()
    fail_sub_task_select = True

    @event.listens_for(engine, "before_cursor_execute")
    def _fail_sub_task_select(conn, cursor, statement, parameters, context, executemany):  # noqa: ANN001, ARG001
        if fail_sub_task_select and statement.startswith("SELECT") and "job_sub_tasks" in statement:
            raise OperationalError(statement, parameters, RuntimeError("query timeout"))

    with Session(engine) as session:
        _seed_demo_account(session)
        service = WorkflowService(session, ai_service=FakeAIService(), storage=FakeStorage())
        created = service.create_prompt_job(
            user_id="demo-user",
            account_id="acc1",
            images=[FakeUpload("ref.png", "image/png", b"png-bytes")],
            copy_text="copy",
            target_platform="小红书",
            topic_title="topic",
        )

        completed = service.run_job("prompt", created.id)

        assert completed.status == "completed"
        fail_sub_task_select = False
        sub_task = (
            session.query(WorkflowStepRecord)
            .filter(WorkflowStepRecord.parent_job_id == created.id, WorkflowStepRecord.sub_type == "image_analysis")
            .one()
        )
        assert sub_task.status == "completed"
        assert sub_task.result_payload["analysis"] == "reference image analysis"


def test_prompt_job_rewrites_each_reference_image_prompt_individually():
    engine = _engine()
    with Session(engine) as session:
        _seed_demo_account(session)
        ai_service = PerImagePromptAIService(
            [
                {"url": "https://cdn.example.test/generated-1.png"},
                {"url": "https://cdn.example.test/generated-2.png"},
                {"url": "https://cdn.example.test/generated-3.png"},
            ]
        )
        service = WorkflowService(session, ai_service=ai_service, storage=FakeStorage())
        prompt_job = service.create_prompt_job(
            user_id="demo-user",
            account_id="acc1",
            images=[
                FakeUpload("ref-1.png", "image/png", b"png-bytes-1"),
                FakeUpload("ref-2.png", "image/png", b"png-bytes-2"),
                FakeUpload("ref-3.png", "image/png", b"png-bytes-3"),
            ],
            copy_text="copy",
            target_platform="小红书",
            topic_title="topic",
        )

        completed_prompt = service.run_job("prompt", prompt_job.id)
        image_job = service.create_image_job(
            user_id="demo-user",
            account_id="acc1",
            prompt=completed_prompt.prompt,
            count=3,
            ratio="3:4",
            prompt_job_id=prompt_job.id,
        )
        completed_image = service.run_job("image", image_job.id)

        assert completed_prompt.status == "completed"
        assert [item["prompt"] for item in completed_prompt.resultPayload["imagePrompts"]] == [
            "rewritten prompt for image 1",
            "rewritten prompt for image 2",
            "rewritten prompt for image 3",
        ]
        assert completed_prompt.prompt == "\n\n".join(
            [
                "rewritten prompt for image 1",
                "rewritten prompt for image 2",
                "rewritten prompt for image 3",
            ]
        )
        assert completed_image.status == "completed"
        assert [item["prompt"] for item in ai_service.image_generation_inputs] == [
            "rewritten prompt for image 1",
            "rewritten prompt for image 2",
            "rewritten prompt for image 3",
        ]


def test_slot_image_job_uses_each_parent_image_prompt_for_matching_slot():
    engine = _engine()
    with Session(engine) as session:
        _seed_demo_account(session)
        ai_service = PerImagePromptAIService(
            [
                {"url": "https://cdn.example.test/generated-1.png"},
                {"url": "https://cdn.example.test/generated-2.png"},
                {"url": "https://cdn.example.test/generated-3.png"},
            ]
        )
        service = WorkflowService(session, ai_service=ai_service, storage=FakeStorage())
        prompt_job = service.create_prompt_job(
            user_id="demo-user",
            account_id="acc1",
            images=[
                FakeUpload("ref-1.png", "image/png", b"png-bytes-1"),
                FakeUpload("ref-2.png", "image/png", b"png-bytes-2"),
                FakeUpload("ref-3.png", "image/png", b"png-bytes-3"),
            ],
            copy_text="copy",
            target_platform="小红书",
            topic_title="topic",
        )
        completed_prompt = service.run_job("prompt", prompt_job.id)

        image_job = service.create_image_job(
            user_id="demo-user",
            account_id="acc1",
            prompt=completed_prompt.prompt,
            count=3,
            ratio="3:4",
            prompt_job_id=prompt_job.id,
            slots=[
                {"slotId": "slot_ref_1", "sourceType": "upload", "sourceUrl": "ref-1.png"},
                {"slotId": "slot_ref_2", "sourceType": "upload", "sourceUrl": "ref-2.png"},
                {"slotId": "slot_ref_3", "sourceType": "upload", "sourceUrl": "ref-3.png"},
            ],
            variants_per_slot=1,
        )
        completed_image = service.run_job("image", image_job.id)

        assert completed_image.status == "completed"
        assert [item["prompt"] for item in ai_service.image_generation_inputs] == [
            "rewritten prompt for image 1",
            "rewritten prompt for image 2",
            "rewritten prompt for image 3",
        ]


def test_prompt_job_logs_step_durations(caplog):
    engine = _engine()
    with Session(engine) as session:
        _seed_demo_account(session)
        service = WorkflowService(session, ai_service=FakeAIService(), storage=FakeStorage())
        created = service.create_prompt_job(
            user_id="demo-user",
            account_id="acc1",
            images=[FakeUpload("ref.png", "image/png", b"png-bytes")],
            copy_text="copy",
            target_platform="小红书",
            topic_title="topic",
        )

        with caplog.at_level(logging.INFO, logger="app.services.workflow.scheduler"):
            completed = service.run_job("prompt", created.id)

        assert completed.status == "completed"
        messages = [record.getMessage() for record in caplog.records]
        assert any("generation job started" in message for message in messages)
        assert any("generation job completed" in message and "total_duration_ms=" in message for message in messages)


def test_prompt_job_passes_reference_oss_url_directly_to_image_view():
    engine = _engine()
    ai_service = FakeAIService()
    with Session(engine) as session:
        _seed_demo_account(session)
        service = WorkflowService(session, ai_service=ai_service, storage=RemoteUrlStorage())
        created = service.create_prompt_job(
            user_id="demo-user",
            account_id="acc1",
            images=[FakeUpload("ref.png", "image/png", b"png-bytes")],
            copy_text="copy",
            target_platform="小红书",
            topic_title="topic",
        )

        completed = service.run_job("prompt", created.id)

        assert completed.status == "completed"
        assert ai_service.image_view_inputs == [completed.assets[0].url]


def test_prompt_job_upload_keys_include_configured_storage_prefix(monkeypatch):
    monkeypatch.setenv("OSS_UPLOAD_DIR", "starx")
    monkeypatch.setattr("app.services.workflow.workflows.generation_helpers.settings.object_storage_upload_dir", "starx")
    engine = _engine()
    storage = FakeStorage()
    with Session(engine) as session:
        _seed_demo_account(session)
        service = WorkflowService(session, ai_service=FakeAIService(), storage=storage)

        created = service.create_prompt_job(
            user_id="demo-user",
            account_id="acc1",
            images=[FakeUpload("ref.png", "image/png", b"png-bytes")],
            copy_text="copy",
            target_platform="小红书",
            topic_title="topic",
        )

        assert created.assets[0].url.startswith("http://localhost:9000/starx-assets/starx/")
        assert list(storage.objects) == [created.assets[0].url.removeprefix("http://localhost:9000/starx-assets/")]


def test_prompt_job_prevalidates_all_uploads_before_writing():
    engine = _engine()
    storage = FakeStorage()
    with Session(engine) as session:
        _seed_demo_account(session)
        service = WorkflowService(session, ai_service=FakeAIService(), storage=storage)

        with pytest.raises(ValueError, match="unsupported image content type"):
            service.create_prompt_job(
                user_id="demo-user",
                account_id="acc1",
                images=[
                    FakeUpload("ref.png", "image/png", b"png-bytes"),
                    FakeUpload("bad.gif", "image/gif", b"gif-bytes"),
                ],
                copy_text="copy",
                target_platform="小红书",
                topic_title="topic",
            )

        assert storage.objects == {}
        assert session.query(WorkflowRecord).count() == 0


def test_image_job_rejects_oversized_reference_upload(monkeypatch):
    from app.core.config import settings

    engine = _engine()
    with Session(engine) as session:
        _seed_demo_account(session)
        monkeypatch.setattr(settings, "max_upload_image_bytes", 4)
        service = WorkflowService(session, ai_service=FakeAIService(), storage=FakeStorage())

        with pytest.raises(ValueError, match="image upload exceeds"):
            service.create_image_job(
                user_id="demo-user",
                account_id="acc1",
                prompt="make one image",
                count=1,
                ratio="3:4",
                prompt_job_id=None,
                reference_images=[FakeUpload("large.png", "image/png", b"12345")],
            )


def test_prompt_job_rolls_back_db_and_cleans_storage_when_later_upload_fails():
    engine = _engine()
    storage = FakeStorage(fail_on_put=2)
    with Session(engine) as session:
        _seed_demo_account(session)
        service = WorkflowService(session, ai_service=FakeAIService(), storage=storage)

        with pytest.raises(RuntimeError, match="storage upload failed"):
            service.create_prompt_job(
                user_id="demo-user",
                account_id="acc1",
                images=[
                    FakeUpload("ref-1.png", "image/png", b"png-bytes-1"),
                    FakeUpload("ref-2.png", "image/png", b"png-bytes-2"),
                ],
                copy_text="copy",
                target_platform="小红书",
                topic_title="topic",
            )

        assert session.query(WorkflowRecord).count() == 0
        assert session.query(GenerationAssetRecord).count() == 0
        assert storage.objects == {}
        assert len(storage.deleted) == 1


def test_prompt_job_marks_reference_asset_failed_when_image_view_raises():
    engine = _engine()
    with Session(engine) as session:
        _seed_demo_account(session)
        service = WorkflowService(session, ai_service=FailingImageViewAIService(), storage=FakeStorage())
        created = service.create_prompt_job(
            user_id="demo-user",
            account_id="acc1",
            images=[FakeUpload("ref.png", "image/png", b"png-bytes")],
            copy_text="copy",
            target_platform="小红书",
            topic_title="topic",
        )

        completed = service.run_job("prompt", created.id)

        assert completed.status == "failed"
        assert "vision service unavailable" in completed.error
        assert completed.assets[0].status == "failed"
        assert "vision service unavailable" in completed.assets[0].error


def test_prompt_job_surfaces_image_view_timeout_instead_of_empty_result():
    engine = _engine()
    with Session(engine) as session:
        _seed_demo_account(session)
        service = WorkflowService(session, ai_service=TimeoutImageViewAIService(), storage=FakeStorage())
        created = service.create_prompt_job(
            user_id="demo-user",
            account_id="acc1",
            images=[FakeUpload("ref.png", "image/png", b"png-bytes")],
            copy_text="copy",
            target_platform="小红书",
            topic_title="topic",
        )

        completed = service.run_job("prompt", created.id)

        assert completed.status == "failed"
        assert completed.error == "ReadTimeout"
        assert "empty result" not in completed.error
        assert completed.assets[0].status == "failed"
        assert completed.assets[0].error == "ReadTimeout"


def test_prompt_job_fails_when_image_analysis_is_empty():
    engine = _engine()
    with Session(engine) as session:
        _seed_demo_account(session)
        service = WorkflowService(session, ai_service=EmptyImageViewAIService(), storage=FakeStorage())
        created = service.create_prompt_job(
            user_id="demo-user",
            account_id="acc1",
            images=[FakeUpload("ref.png", "image/png", b"png-bytes")],
            copy_text="copy",
            target_platform="小红书",
            topic_title="topic",
        )

        completed = service.run_job("prompt", created.id)

        assert completed.status == "failed"
        assert "empty result" in completed.error
        assert completed.prompt == ""
        assert completed.assets[0].status == "failed"
        assert "empty result" in completed.assets[0].error


def test_prompt_job_marks_running_asset_failed_when_prompt_generation_raises():
    engine = _engine()
    with Session(engine) as session:
        _seed_demo_account(session)
        service = WorkflowService(session, ai_service=FailingChatAIService(), storage=FakeStorage())
        created = service.create_prompt_job(
            user_id="demo-user",
            account_id="acc1",
            images=[FakeUpload("ref.png", "image/png", b"png-bytes")],
            copy_text="copy",
            target_platform="小红书",
            topic_title="topic",
        )

        completed = service.run_job("prompt", created.id)

        assert completed.status == "failed"
        assert "prompt service unavailable" in completed.error
        assert completed.assets[0].status == "completed"
        assert completed.assets[0].analysis == "reference image analysis"


def test_prompt_job_rolls_back_when_reference_analysis_persist_times_out():
    engine = _engine()
    fail_analysis_update = True

    @event.listens_for(engine, "before_cursor_execute")
    def _fail_analysis_update(conn, cursor, statement, parameters, context, executemany):  # noqa: ANN001, ARG001
        if fail_analysis_update and statement.startswith("UPDATE generation_assets") and "analysis" in statement:
            raise OperationalError(statement, parameters, RuntimeError("query timeout"))

    with Session(engine) as session:
        _seed_demo_account(session)
        service = WorkflowService(session, ai_service=FakeAIService(), storage=FakeStorage())
        created = service.create_prompt_job(
            user_id="demo-user",
            account_id="acc1",
            images=[FakeUpload("ref.png", "image/png", b"png-bytes")],
            copy_text="copy",
            target_platform="小红书",
            topic_title="topic",
        )

        completed = service.run_job("prompt", created.id)

        assert completed.status == "failed"
        assert "query timeout" in completed.error
        assert "previous exception during flush" not in completed.error

        fail_analysis_update = False
        session.rollback()
        persisted = session.get(WorkflowRecord, created.id)
        assert persisted is not None
        assert persisted.status == "failed"
        assert persisted.error == "query timeout"


def test_prompt_job_rejects_empty_generated_prompt():
    engine = _engine()
    with Session(engine) as session:
        _seed_demo_account(session)
        service = WorkflowService(session, ai_service=EmptyPromptAIService(), storage=FakeStorage())
        created = service.create_prompt_job(
            user_id="demo-user",
            account_id="acc1",
            images=[FakeUpload("ref.png", "image/png", b"png-bytes")],
            copy_text="copy",
            target_platform="小红书",
            topic_title="topic",
        )

        completed = service.run_job("prompt", created.id)

        assert completed.status == "failed"
        assert "empty prompt" in completed.error
        assert completed.prompt == ""


def test_prompt_job_bounds_prompt_generation_input_length():
    engine = _engine()
    with Session(engine) as session:
        _seed_demo_account(session)
        ai_service = LengthGuardPromptAIService()
        service = WorkflowService(session, ai_service=ai_service, storage=FakeStorage())
        created = service.create_prompt_job(
            user_id="demo-user",
            account_id="acc1",
            images=[FakeUpload("ref.png", "image/png", b"png-bytes")],
            copy_text="超长文案" * 8000,
            target_platform="小红书",
            topic_title="topic",
        )

        completed = service.run_job("prompt", created.id)

        assert completed.status == "completed"
        assert len(ai_service.chat_completion_inputs[0]) <= 32000
        assert completed.resultPayload["truncated"] is True


def test_prompt_job_fails_clearly_when_ai_token_is_missing():
    engine = _engine()
    with Session(engine) as session:
        _seed_demo_account(session)
        service = WorkflowService(session, ai_service=MissingTokenAIService(), storage=FakeStorage())
        created = service.create_prompt_job(
            user_id="demo-user",
            account_id="acc1",
            images=[FakeUpload("ref.png", "image/png", b"png-bytes")],
            copy_text="copy",
            target_platform="小红书",
            topic_title="topic",
        )

        completed = service.run_job("prompt", created.id)

        assert completed.status == "failed"
        assert completed.error == "AI service token is not configured"
        assert completed.assets[0].status == "pending"


def test_image_job_persists_generated_results():
    engine = _engine()
    with Session(engine) as session:
        _seed_demo_account(session)
        service = WorkflowService(
            session,
            ai_service=FakeAIService(
                [
                    {"url": "https://cdn.example.test/generated-1.png", "revisedPrompt": "revised one"},
                    {"url": "https://cdn.example.test/generated-2.png", "revised_prompt": "revised two"},
                ]
            ),
            storage=FakeStorage(),
        )

        created = service.create_image_job(
            user_id="demo-user",
            account_id="acc1",
            prompt="make two images",
            count=2,
            ratio="1:1",
            prompt_job_id=None,
        )

        completed = service.run_job("image", created.id)

        assert completed.status == "completed"
        assert len(completed.assets) == 2
        assert [asset.assetType for asset in completed.assets] == ["result", "result"]
        assert completed.resultPayload["images"] == [
            {"url": "https://cdn.example.test/generated-1.png", "revisedPrompt": "revised one"},
            {"url": "https://cdn.example.test/generated-2.png", "revisedPrompt": "revised two"},
        ]
        assert completed.assets[0].meta["revisedPrompt"] == "revised one"
        assert completed.assets[1].meta["revisedPrompt"] == "revised two"


def test_image_job_passes_reference_and_material_images_to_edit_model():
    engine = _engine()
    with Session(engine) as session:
        _seed_demo_account(session)
        ai_service = FakeAIService([{"url": "https://cdn.example.test/generated-with-inputs.png"}])
        storage = FakeStorage()
        service = WorkflowService(session, ai_service=ai_service, storage=storage)

        created = service.create_image_job(
            user_id="demo-user",
            account_id="acc1",
            prompt="知识库融合后的护肤品海报提示词",
            count=1,
            ratio="1:1",
            prompt_job_id=None,
            reference_images=[FakeUpload("reference.png", "image/png", b"reference-bytes")],
            material_images=[FakeUpload("material.webp", "image/webp", b"material-bytes")],
            reference_strength=82,
            material_strength="高",
        )

        completed = service.run_job("image", created.id)

        assert completed.status == "completed"
        input_assets = [asset for asset in completed.assets if asset.assetType in {"reference", "material"}]
        assert [asset.assetType for asset in input_assets] == ["reference", "material"]
        assert input_assets[0].meta["role"] == "reference"
        assert input_assets[0].meta["strength"] == 82
        assert input_assets[1].meta["role"] == "material"
        assert input_assets[1].meta["strength"] == "高"
        assert ai_service.image_generation_inputs == []
        assert len(ai_service.image_edit_inputs) == 1
        edit_input = ai_service.image_edit_inputs[0]
        assert edit_input["input_reference"] == [
            {"type": "image_url", "image_url": {"url": input_assets[0].url}},
            {"type": "image_url", "image_url": {"url": input_assets[1].url}},
        ]
        assert edit_input["extra_body"] is None
        assert "参考图" in edit_input["prompt"]
        assert "素材图" in edit_input["prompt"]


def test_image_job_uses_image_edit_when_reference_url_is_present():
    engine = _engine()
    with Session(engine) as session:
        _seed_demo_account(session)
        ai_service = FakeAIService([{"url": "https://cdn.example.test/edited.png"}])
        service = WorkflowService(session, ai_service=ai_service, storage=FakeStorage())

        created = service.create_image_job(
            user_id="demo-user",
            account_id="acc1",
            prompt="把图中人物的衣服改成绿色",
            count=1,
            ratio="3:4",
            prompt_job_id=None,
            reference_urls=["https://oss.example.test/extract/douyin/source.webp"],
        )
        completed = service.run_job("image", created.id)

        assert completed.status == "completed"
        assert ai_service.image_generation_inputs == []
        assert len(ai_service.image_edit_inputs) == 1
        assert ai_service.image_edit_inputs[0]["input_reference"] == [
            {"type": "image_url", "image_url": {"url": "https://oss.example.test/extract/douyin/source.webp"}}
        ]


def test_image_job_does_not_include_account_knowledge_context_in_generation_prompt():
    engine = _engine()
    with Session(engine) as session:
        _seed_demo_account(session)
        session.add(
            KnowledgeBaseRecord(
                id="kb1",
                user_id="demo-user",
                name="品牌知识库",
                product_name="星颜精华",
                product_intro="主打敏感肌修护",
                brand_story="专业温和护肤品牌",
                price="299元",
                website_url="https://example.test",
                image_materials=[],
                enabled_fields={},
            )
        )
        account = session.get(AccountRecord, "acc1")
        account.knowledge_base_id = "kb1"
        session.commit()
        ai_service = FakeAIService([{"url": "https://cdn.example.test/generated-without-knowledge.png"}])
        service = WorkflowService(session, ai_service=ai_service, storage=FakeStorage())

        created = service.create_image_job(
            user_id="demo-user",
            account_id="acc1",
            prompt="反推后的高质量海报提示词",
            count=1,
            ratio="1:1",
            prompt_job_id=None,
        )
        completed = service.run_job("image", created.id)

        assert completed.status == "completed"
        generation_prompt = str(ai_service.image_generation_inputs[0]["prompt"])
        assert "账号知识库" not in generation_prompt
        assert "星颜精华" not in generation_prompt
        assert "主打敏感肌修护" not in generation_prompt


def test_image_job_groups_two_variants_per_slot():
    engine = _engine()
    with Session(engine) as session:
        _seed_demo_account(session)
        ai_service = FakeAIService(
            [
                {"url": "https://cdn.example.test/slot-1-a.png"},
                {"url": "https://cdn.example.test/slot-1-b.png"},
                {"url": "https://cdn.example.test/slot-2-a.png"},
                {"url": "https://cdn.example.test/slot-2-b.png"},
            ]
        )
        service = WorkflowService(session, ai_service=ai_service, storage=FakeStorage())

        created = service.create_image_job(
            user_id="demo-user",
            account_id="acc1",
            prompt="统一风格提示词",
            count=2,
            ratio="3:4",
            prompt_job_id=None,
            slots=[
                {
                    "slotId": "slot_ref_1",
                    "sourceType": "reference_image",
                    "sourceUrl": "https://cdn.example.test/ref-1.png",
                    "sourcePrompt": "参考图 1 分析",
                },
                {
                    "slotId": "slot_ref_2",
                    "sourceType": "reference_image",
                    "sourceUrl": "https://cdn.example.test/ref-2.png",
                    "sourcePrompt": "参考图 2 分析",
                },
            ],
            variants_per_slot=2,
        )

        completed = service.run_job("image", created.id)

        assert completed.status == "completed"
        assert len(completed.resultPayload["images"]) == 4
        assert [group["slotId"] for group in completed.resultPayload["imageGroups"]] == ["slot_ref_1", "slot_ref_2"]
        assert [len(group["variants"]) for group in completed.resultPayload["imageGroups"]] == [2, 2]
        assert completed.resultPayload["imageGroups"][0]["sourceUrl"] == "https://cdn.example.test/ref-1.png"
        assert completed.resultPayload["imageGroups"][0]["variants"][0]["variantIndex"] == 0
        assert completed.resultPayload["imageGroups"][0]["variants"][1]["variantIndex"] == 1
        assert completed.resultPayload["images"][0]["slotId"] == "slot_ref_1"
        assert completed.resultPayload["images"][2]["slotId"] == "slot_ref_2"
        assert "参考图 1 分析" in ai_service.image_generation_inputs[0]["prompt"]
        assert "参考图 2 分析" in ai_service.image_generation_inputs[2]["prompt"]


def test_image_plan_slots_send_only_common_constraints_and_current_card_prompt():
    engine = _engine()
    with Session(engine) as session:
        _seed_demo_account(session)
        ai_service = FakeAIService([
            {"url": "https://cdn.example.test/card-a.png"},
            {"url": "https://cdn.example.test/card-b.png"},
        ])
        service = WorkflowService(session, ai_service=ai_service, storage=FakeStorage())

        created = service.create_image_job(
            user_id="demo-user",
            account_id="acc1",
            prompt="公共约束：奶油色调、统一字体",
            count=2,
            ratio="3:4",
            prompt_job_id=None,
            slots=[
                {"slotId": "card_a", "sourcePrompt": "A卡专属：口红封面"},
                {"slotId": "card_b", "sourcePrompt": "B卡专属：色号对比"},
            ],
            variants_per_slot=1,
        )

        service.run_job("image", created.id)

        prompt_a = str(ai_service.image_generation_inputs[0]["prompt"])
        prompt_b = str(ai_service.image_generation_inputs[1]["prompt"])
        assert "公共约束：奶油色调、统一字体" in prompt_a
        assert "A卡专属：口红封面" in prompt_a
        assert "B卡专属：色号对比" not in prompt_a
        assert "公共约束：奶油色调、统一字体" in prompt_b
        assert "B卡专属：色号对比" in prompt_b
        assert "A卡专属：口红封面" not in prompt_b


def test_image_job_allows_five_slots_with_two_variants_each():
    engine = _engine()
    with Session(engine) as session:
        _seed_demo_account(session)
        ai_service = FakeAIService(
            [{"url": f"https://cdn.example.test/slot-{index}.png"} for index in range(10)]
        )
        service = WorkflowService(session, ai_service=ai_service, storage=FakeStorage())

        created = service.create_image_job(
            user_id="demo-user",
            account_id="acc1",
            prompt="统一风格提示词",
            count=5,
            ratio="3:4",
            prompt_job_id=None,
            slots=[
                {
                    "slotId": f"slot_ref_{index}",
                    "sourceType": "reference_image",
                    "sourceUrl": f"https://cdn.example.test/ref-{index}.png",
                    "sourcePrompt": f"参考图 {index} 分析",
                }
                for index in range(5)
            ],
            variants_per_slot=2,
        )

        completed = service.run_job("image", created.id)

        assert completed.status == "completed"
        assert completed.requestedCount == 10
        assert len(completed.resultPayload["images"]) == 10
        assert len(completed.resultPayload["imageGroups"]) == 5
        assert [len(group["variants"]) for group in completed.resultPayload["imageGroups"]] == [2, 2, 2, 2, 2]


def test_image_job_uses_configured_parallel_image_generation_sub_task_limit(monkeypatch):
    monkeypatch.setattr("app.services.workflow.workflows.steps.IMAGE_GENERATION_SUB_JOB_CONCURRENCY", 2)
    engine = _engine()
    with Session(engine) as session:
        _seed_demo_account(session)
        ai_service = ConcurrentImageAIService()
        service = WorkflowService(session, ai_service=ai_service, storage=FakeStorage())

        created = service.create_image_job(
            user_id="demo-user",
            account_id="acc1",
            prompt="统一风格提示词",
            count=5,
            ratio="3:4",
            prompt_job_id=None,
            slots=[
                {
                    "slotId": f"slot_ref_{index}",
                    "sourceType": "reference_image",
                    "sourceUrl": f"https://cdn.example.test/ref-{index}.png",
                    "sourcePrompt": f"参考图 {index} 分析",
                }
                for index in range(5)
            ],
            variants_per_slot=2,
        )

        completed = service.run_job("image", created.id)

        assert completed.status == "completed"
        assert completed.requestedCount == 10
        assert ai_service.max_active <= 2


def test_image_job_records_single_slot_regeneration_refinement():
    engine = _engine()
    with Session(engine) as session:
        _seed_demo_account(session)
        ai_service = FakeAIService(
            [
                {"url": "https://cdn.example.test/slot-1-refresh-a.png"},
                {"url": "https://cdn.example.test/slot-1-refresh-b.png"},
            ]
        )
        service = WorkflowService(session, ai_service=ai_service, storage=FakeStorage())

        created = service.create_image_job(
            user_id="demo-user",
            account_id="acc1",
            prompt="统一风格提示词",
            count=1,
            ratio="3:4",
            prompt_job_id=None,
            slots=[
                {
                    "slotId": "slot_ref_1",
                    "sourceType": "reference_image",
                    "sourceUrl": "https://cdn.example.test/ref-1.png",
                    "sourcePrompt": "参考图 1 分析",
                }
            ],
            variants_per_slot=2,
            regenerate_slot_id="slot_ref_1",
            refinement="颜色更清爽，减少文字密度",
        )

        completed = service.run_job("image", created.id)

        assert completed.inputPayload["regenerateSlotId"] == "slot_ref_1"
        assert completed.inputPayload["refinement"] == "颜色更清爽，减少文字密度"
        assert completed.resultPayload["imageGroups"][0]["refinement"] == "颜色更清爽，减少文字密度"
        assert len(completed.resultPayload["imageGroups"][0]["variants"]) == 2
        assert "颜色更清爽，减少文字密度" in ai_service.image_generation_inputs[0]["prompt"]


@pytest.mark.parametrize(
    ("ratio", "expected_size"),
    [
        ("1:1", "1024x1024"),
        ("3:4", "960x1280"),
        ("4:3", "1280x960"),
        ("9:16", "1008x1792"),
        ("16:9", "1792x1008"),
    ],
)
def test_image_job_uses_openai_compatible_size_for_ratio(ratio: str, expected_size: str):
    engine = _engine()
    ai_service = FakeAIService([{"url": "https://cdn.example.test/generated-1.png"}])
    with Session(engine) as session:
        _seed_demo_account(session)
        service = WorkflowService(session, ai_service=ai_service, storage=FakeStorage())

        created = service.create_image_job(
            user_id="demo-user",
            account_id="acc1",
            prompt="make one image",
            count=1,
            ratio=ratio,
            prompt_job_id=None,
        )

        completed = service.run_job("image", created.id)

        width, height = [int(part) for part in expected_size.split("x")]
        assert completed.status == "completed"
        assert ai_service.image_generation_inputs[0]["prompt"] == "make one image"
        assert ai_service.image_generation_inputs[0]["size"] == expected_size
        assert ai_service.image_generation_inputs[0]["n"] == 1
        assert width % 16 == 0
        assert height % 16 == 0


def test_image_job_logs_step_durations(caplog):
    engine = _engine()
    with Session(engine) as session:
        _seed_demo_account(session)
        service = WorkflowService(
            session,
            ai_service=FakeAIService([{"url": "https://cdn.example.test/generated-1.png"}]),
            storage=FakeStorage(),
        )

        created = service.create_image_job(
            user_id="demo-user",
            account_id="acc1",
            prompt="make one image",
            count=1,
            ratio="1:1",
            prompt_job_id=None,
        )

        with caplog.at_level(logging.INFO, logger="app.services.workflow.scheduler"):
            completed = service.run_job("image", created.id)

        assert completed.status == "completed"
        messages = [record.getMessage() for record in caplog.records]
        assert any("generation job started" in message for message in messages)
        assert any("generation job completed" in message and "total_duration_ms=" in message for message in messages)


def test_image_job_writes_b64_json_result_to_storage():
    engine = _engine()
    storage = FakeStorage()
    encoded = base64.b64encode(b"tiny image").decode("ascii")
    with Session(engine) as session:
        _seed_demo_account(session)
        service = WorkflowService(session, ai_service=FakeAIService([{"b64_json": encoded}]), storage=storage)

        created = service.create_image_job(
            user_id="demo-user",
            account_id="acc1",
            prompt="make one image",
            count=1,
            ratio="3:4",
            prompt_job_id=None,
        )

        completed = service.run_job("image", created.id)

        assert completed.status == "completed"
        assert len(storage.objects) == 1
        key, (data, content_type) = next(iter(storage.objects.items()))
        assert key.startswith("generation/acc1/")
        assert data == b"tiny image"
        assert content_type == "image/png"
        assert completed.assets[0].url == f"http://localhost:9000/starx-assets/{key}"
        assert completed.resultPayload["images"] == [{"url": completed.assets[0].url, "revisedPrompt": ""}]

        step = session.query(WorkflowStepRecord).filter(
            WorkflowStepRecord.workflow_id == created.id,
            WorkflowStepRecord.type == "image_generation",
        ).one()
        dumped = json.dumps(step.result_payload, ensure_ascii=False)
        assert "b64_json" not in dumped
        assert encoded not in dumped
        assert step.result_payload["image"]["url"] == completed.assets[0].url


def test_image_generation_rejects_oversized_b64_json(monkeypatch):
    from app.core.config import settings

    engine = _engine()
    encoded = base64.b64encode(b"12345").decode("ascii")
    with Session(engine) as session:
        _seed_demo_account(session)
        monkeypatch.setattr(settings, "max_generated_image_bytes", 4)
        service = WorkflowService(session, ai_service=FakeAIService([{"b64_json": encoded}]), storage=FakeStorage())

        created = service.create_image_job(
            user_id="demo-user",
            account_id="acc1",
            prompt="make one image",
            count=1,
            ratio="3:4",
            prompt_job_id=None,
        )

        completed = service.run_job("image", created.id)

        assert completed.status == "failed"
        assert "generated image exceeds" in completed.error


def test_image_job_writes_data_url_b64_json_result_to_storage():
    engine = _engine()
    storage = FakeStorage()
    encoded = base64.b64encode(b"tiny webp image").decode("ascii")
    with Session(engine) as session:
        _seed_demo_account(session)
        service = WorkflowService(
            session,
            ai_service=FakeAIService([{"b64_json": f"data:image/webp;base64,{encoded}"}]),
            storage=storage,
        )

        created = service.create_image_job(
            user_id="demo-user",
            account_id="acc1",
            prompt="make one image",
            count=1,
            ratio="3:4",
            prompt_job_id=None,
        )

        completed = service.run_job("image", created.id)

        assert completed.status == "completed"
        key, (data, content_type) = next(iter(storage.objects.items()))
        assert key.endswith(".webp")
        assert data == b"tiny webp image"
        assert content_type == "image/webp"
        assert completed.assets[0].mimeType == "image/webp"
        assert completed.assets[0].url == f"http://localhost:9000/starx-assets/{key}"
        assert completed.resultPayload["images"] == [{"url": completed.assets[0].url, "revisedPrompt": ""}]


def test_image_job_records_exception_type_when_error_message_is_empty():
    engine = _engine()
    with Session(engine) as session:
        _seed_demo_account(session)
        service = WorkflowService(session, ai_service=TimeoutImageAIService(), storage=FakeStorage())

        created = service.create_image_job(
            user_id="demo-user",
            account_id="acc1",
            prompt="make one image",
            count=1,
            ratio="3:4",
            prompt_job_id=None,
        )

        completed = service.run_job("image", created.id)
        sub_task = session.query(WorkflowStepRecord).filter(WorkflowStepRecord.parent_job_id == created.id).one()

        assert completed.status == "failed"
        assert completed.error == "ReadTimeout"
        assert sub_task.status == "failed"
        assert sub_task.error == "ReadTimeout"


def test_image_job_failure_rolls_back_partial_result_assets_and_payload():
    engine = _engine()
    with Session(engine) as session:
        _seed_demo_account(session)
        service = WorkflowService(
            session,
            ai_service=FakeAIService(
                [
                    {"url": "https://cdn.example.test/generated-1.png", "revisedPrompt": "revised one"},
                    {},
                ]
            ),
            storage=FakeStorage(),
        )

        created = service.create_image_job(
            user_id="demo-user",
            account_id="acc1",
            prompt="make two images",
            count=2,
            ratio="1:1",
            prompt_job_id=None,
        )

        completed = service.run_job("image", created.id)

        assert completed.status == "failed"
        assert "did not include url or b64_json" in completed.error
        assert completed.resultPayload == {}
        assert completed.assets == []
        assert session.query(GenerationAssetRecord).count() == 0


def test_image_job_fails_clearly_when_ai_token_is_missing():
    engine = _engine()
    with Session(engine) as session:
        _seed_demo_account(session)
        service = WorkflowService(session, ai_service=MissingTokenAIService(), storage=FakeStorage())
        created = service.create_image_job(
            user_id="demo-user",
            account_id="acc1",
            prompt="make one image",
            count=1,
            ratio="1:1",
            prompt_job_id=None,
        )

        completed = service.run_job("image", created.id)

        assert completed.status == "failed"
        assert completed.error == "AI service token is not configured"
        assert completed.assets == []


def test_image_job_cleans_b64_storage_when_final_commit_fails():
    engine = _engine()
    storage = FakeStorage()
    encoded = base64.b64encode(b"tiny image").decode("ascii")
    with Session(engine) as session:
        _seed_demo_account(session)
        service = WorkflowService(session, ai_service=FakeAIService([{"b64_json": encoded}]), storage=storage)
        created = service.create_image_job(
            user_id="demo-user",
            account_id="acc1",
            prompt="make one image",
            count=1,
            ratio="3:4",
            prompt_job_id=None,
        )

        original_commit = session.commit
        commit_count = 0

        def fail_final_commit():
            nonlocal commit_count
            commit_count += 1
            if commit_count == 5:
                raise RuntimeError("database commit failed")
            return original_commit()

        session.commit = fail_final_commit
        completed = service.run_job("image", created.id)

        assert completed.status == "failed"
        assert "database commit failed" in completed.error
        assert storage.objects == {}
        assert len(storage.deleted) == 1


def test_prompt_job_new_session_helper_runs_with_isolated_session():
    engine = _engine()
    SessionLocal = sessionmaker(bind=engine)
    storage = FakeStorage()

    with SessionLocal() as session:
        _seed_demo_account(session)
        created = WorkflowService(session, ai_service=FakeAIService(), storage=storage).create_prompt_job(
            user_id="demo-user",
            account_id="acc1",
            images=[FakeUpload("ref.png", "image/png", b"png-bytes")],
            copy_text="copy",
            target_platform="小红书",
            topic_title="topic",
        )

    completed = WorkflowService.run_in_new_session("prompt", 
        created.id,
        SessionLocal,
        ai_service=FakeAIService(),
        storage=storage,
    )

    with SessionLocal() as session:
        persisted = WorkflowService(session, ai_service=FakeAIService(), storage=storage).get_job(
            "demo-user",
            "acc1",
            created.id,
        )

    assert completed.status == "completed"
    assert persisted.status == "completed"
    assert persisted.assets[0].analysis == "reference image analysis"


def test_image_job_new_session_helper_runs_with_isolated_session():
    engine = _engine()
    SessionLocal = sessionmaker(bind=engine)
    storage = FakeStorage()

    with SessionLocal() as session:
        _seed_demo_account(session)
        created = WorkflowService(session, ai_service=FakeAIService(), storage=storage).create_image_job(
            user_id="demo-user",
            account_id="acc1",
            prompt="make one image",
            count=1,
            ratio="1:1",
            prompt_job_id=None,
        )

    completed = WorkflowService.run_in_new_session("image", 
        created.id,
        SessionLocal,
        ai_service=FakeAIService([{"url": "https://cdn.example.test/generated-1.png"}]),
        storage=storage,
    )

    with SessionLocal() as session:
        persisted = WorkflowService(session, ai_service=FakeAIService(), storage=storage).get_job(
            "demo-user",
            "acc1",
            created.id,
        )

    assert completed.status == "completed"
    assert persisted.status == "completed"
    assert len(persisted.assets) == 1


def test_image_workflow_uses_source_prompt_workflow_without_parent_relationship():
    engine = _engine()
    with Session(engine) as session:
        _seed_demo_account(session)
        service = WorkflowService(session, ai_service=FakeAIService(), storage=FakeStorage())
        parent = service.create_prompt_job(
            user_id="demo-user",
            account_id="acc1",
            images=[FakeUpload("ref.png", "image/png", b"png-bytes")],
            copy_text="copy",
            target_platform="视频号",
            topic_title="topic",
        )

        created = service.create_image_job(
            user_id="demo-user",
            account_id="acc1",
            prompt="child prompt",
            count=1,
            ratio="9:16",
            prompt_job_id=parent.id,
        )

        record = session.get(WorkflowRecord, created.id)
        assert created.targetPlatform == "视频号"
        assert created.inputPayload["sourcePromptWorkflowId"] == parent.id
        assert record is not None
        assert record.parent_job_id is None


def test_image_job_rejects_non_prompt_parent_job():
    engine = _engine()
    with Session(engine) as session:
        _seed_demo_account(session)
        service = WorkflowService(session, ai_service=FakeAIService(), storage=FakeStorage())
        parent = service.create_image_job(
            user_id="demo-user",
            account_id="acc1",
            prompt="parent image prompt",
            count=1,
            ratio="1:1",
            prompt_job_id=None,
        )

        with pytest.raises(ValueError, match="sourcePromptWorkflowId must refer to a prompt workflow"):
            service.create_image_job(
                user_id="demo-user",
                account_id="acc1",
                prompt="child prompt",
                count=1,
                ratio="1:1",
                prompt_job_id=parent.id,
            )
