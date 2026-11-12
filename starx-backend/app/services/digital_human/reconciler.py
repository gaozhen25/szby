from __future__ import annotations

import asyncio
import socket
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from urllib.parse import quote
from uuid import uuid4

from sqlalchemy import or_, select
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.database import SessionLocal
from app.core.logging import get_logger
from app.db.models import (
    DigitalHumanProfileRecord,
    GenerationAssetRecord,
    WorkflowExternalTaskRecord,
    WorkflowRecord,
)
from app.services.object_storage import default_object_storage

from .media import (
    download_media,
    inspect_audio,
    inspect_video,
    measure_audio_loudness,
    prepare_background_music,
)
from .providers import (
    AliyunIceEditingProvider,
    DashScopeVoiceProvider,
    EditingOptions,
    KyyProvider,
    NonRetryableEditingError,
)
from .service import DIGITAL_HUMAN_VIDEO_TYPE
from .subtitles import subtitle_cues_from_payload

logger = get_logger(__name__)


class DigitalHumanReconciler:
    def __init__(
        self,
        *,
        scan_seconds: int | None = None,
        voice_provider: Any = None,
        video_provider: Any = None,
        editing_provider: Any = None,
        storage: Any = default_object_storage,
    ) -> None:
        self.scan_seconds = scan_seconds or settings.digital_human_reconciler_scan_seconds
        self.voice_provider = voice_provider or DashScopeVoiceProvider()
        self.video_provider = video_provider or KyyProvider()
        self.editing_provider = editing_provider or AliyunIceEditingProvider()
        self.storage = storage
        self.worker_id = f"{socket.gethostname()}-{uuid4().hex[:8]}"
        self._stop_event: asyncio.Event | None = None
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._stop_event = asyncio.Event()
        self._task = asyncio.create_task(self._run(), name="digital-human-reconciler")

    async def stop(self) -> None:
        if self._task is None:
            return
        if self._stop_event is not None:
            self._stop_event.set()
        await self._task
        self._task = None
        self._stop_event = None

    async def scan_once(self) -> int:
        workflow_ids = self._claim_due(limit=5)
        if workflow_ids:
            await asyncio.gather(
                *(self.process(workflow_id) for workflow_id in workflow_ids),
                return_exceptions=True,
            )
        return len(workflow_ids)

    def _claim_due(self, *, limit: int) -> list[str]:
        now = datetime.now(UTC)
        lease_until = now + timedelta(minutes=3)
        with SessionLocal() as session:
            rows = session.scalars(
                select(WorkflowExternalTaskRecord)
                .join(WorkflowRecord)
                .where(
                    WorkflowRecord.type == DIGITAL_HUMAN_VIDEO_TYPE,
                    WorkflowRecord.status.in_(("pending", "running")),
                    WorkflowExternalTaskRecord.next_poll_at <= now,
                    or_(
                        WorkflowExternalTaskRecord.lease_expires_at.is_(None),
                        WorkflowExternalTaskRecord.lease_expires_at < now,
                    ),
                )
                .order_by(WorkflowExternalTaskRecord.next_poll_at.asc())
                .with_for_update(skip_locked=True)
                .limit(limit)
            ).all()
            ids: list[str] = []
            for row in rows:
                row.lease_owner = self.worker_id
                row.lease_expires_at = lease_until
                row.updated_at = now
                ids.append(row.workflow_id)
            session.commit()
            return ids

    async def process(self, workflow_id: str) -> None:
        try:
            workflow, external, profile = self._load(workflow_id)
            if external.provider == "aliyun_ice":
                await self._poll_editing(workflow, external)
            elif not external.provider_task_id:
                await self._prepare_and_submit(workflow, external, profile)
            else:
                await self._poll_digital_human(workflow, external)
        except Exception as exc:
            logger.exception("digital human task failed workflow_id=%s", workflow_id)
            if isinstance(exc, NonRetryableEditingError):
                self._fail(workflow_id, str(exc))
                return
            self._record_transient_error(workflow_id, str(exc))

    def _load(
        self, workflow_id: str
    ) -> tuple[WorkflowRecord, WorkflowExternalTaskRecord, DigitalHumanProfileRecord]:
        with SessionLocal() as session:
            workflow = session.scalar(
                select(WorkflowRecord)
                .options(selectinload(WorkflowRecord.external_task))
                .where(WorkflowRecord.id == workflow_id)
            )
            if workflow is None or workflow.external_task is None:
                raise ValueError("数字人任务不存在")
            profile_id = str((workflow.input_payload or {}).get("profileId") or "")
            profile = session.get(DigitalHumanProfileRecord, profile_id)
            if profile is None:
                raise ValueError("数字人档案不存在")
            external = workflow.external_task
            session.expunge(external)
            session.expunge(workflow)
            session.expunge(profile)
            return workflow, external, profile

    async def _prepare_and_submit(
        self,
        workflow: WorkflowRecord,
        external: WorkflowExternalTaskRecord,
        profile: DigitalHumanProfileRecord,
    ) -> None:
        payload = dict(workflow.input_payload or {})
        self._update_workflow(
            workflow.id,
            status="running",
            progress=10,
            current_stage="preparing_voice",
        )
        synthesize_timed = getattr(self.voice_provider, "synthesize_timed", None)
        if callable(synthesize_timed):
            synthesized = await synthesize_timed(
                voice_id=profile.provider_voice_id,
                text=str(payload.get("scriptText") or ""),
                speed=float(payload.get("speed") or 1.0),
            )
            audio = synthesized.audio
            subtitle_cues = [
                cue.to_dict() for cue in synthesized.subtitle_cues
            ]
        else:
            audio = await self.voice_provider.synthesize(
                voice_id=profile.provider_voice_id,
                text=str(payload.get("scriptText") or ""),
                speed=float(payload.get("speed") or 1.0),
            )
            subtitle_cues = []
        audio_key = (
            f"digital-human/{workflow.account_id}/jobs/{workflow.id}/speech.mp3"
        )
        # 对象存储 SDK 是同步 I/O。对账器运行在 FastAPI 主事件循环中，
        # 大文件上传必须移入工作线程，否则登录、健康检查等请求会全部饿死。
        audio_url = await asyncio.to_thread(
            self.storage.put_bytes,
            audio_key,
            audio,
            "audio/mpeg",
        )
        self._add_asset(
            workflow,
            asset_type="source_audio",
            file_name="speech.mp3",
            mime_type="audio/mpeg",
            storage_key=audio_key,
            url=audio_url,
        )
        self._update_workflow(
            workflow.id,
            progress=25,
            current_stage="submitting_provider",
        )
        project_id = await self.video_provider.create_video(
            title=workflow.title or "数字人口播视频",
            video_url=profile.source_video_url,
            audio_url=audio_url,
        )
        now = datetime.now(UTC)
        with SessionLocal() as session:
            row = session.get(WorkflowExternalTaskRecord, workflow.id)
            record = session.get(WorkflowRecord, workflow.id)
            if row is None or record is None:
                return
            row.provider_task_id = project_id
            row.provider_status = "processing"
            row.sanitized_request = {
                **dict(row.sanitized_request or {}),
                "subtitleCues": subtitle_cues,
            }
            row.submitted_at = now
            row.next_poll_at = now + timedelta(
                seconds=settings.digital_human_poll_interval_seconds
            )
            row.lease_owner = ""
            row.lease_expires_at = None
            row.consecutive_errors = 0
            row.updated_at = now
            record.status = "running"
            record.progress = 35
            record.current_stage = "provider_generating"
            record.error = ""
            record.updated_at = now
            session.commit()

    async def _poll_digital_human(
        self, workflow: WorkflowRecord, external: WorkflowExternalTaskRecord
    ) -> None:
        if external.poll_attempts >= external.max_poll_attempts:
            self._fail(workflow.id, "数字人视频生成超时")
            return
        result = await self.video_provider.get_video_result(external.provider_task_id)
        if result.state == "failed":
            self._fail(workflow.id, result.error_message or "数字人视频生成失败", result.raw)
            return
        if result.state != "completed":
            self._reschedule(workflow.id, result.raw)
            return

        self._update_workflow(
            workflow.id, progress=70, current_stage="preparing_editing"
        )
        with TemporaryDirectory(prefix="starx-digital-human-result-") as temp_dir:
            path = Path(temp_dir) / "raw.mp4"
            await download_media(
                result.media_url,
                path,
                max_bytes=settings.digital_human_max_result_video_bytes,
            )
            metadata = await inspect_video(path)
            raw_key = (
                f"digital-human/{workflow.account_id}/jobs/{workflow.id}/raw.mp4"
            )
            raw_url = await asyncio.to_thread(
                self.storage.put_file,
                raw_key,
                path,
                "video/mp4",
            )
        self._add_asset(
            workflow,
            asset_type="raw_video",
            file_name="raw.mp4",
            mime_type="video/mp4",
            storage_key=raw_key,
            url=raw_url,
        )
        editing = dict((workflow.input_payload or {}).get("editing") or {})
        background_music_url = str(editing.get("backgroundMusicUrl") or "")
        background_music_meta: dict[str, Any] = {}
        if background_music_url:
            background_music_url, background_music_meta = (
                await self._prepare_background_music_asset(
                    workflow,
                    source_url=background_music_url,
                    duration_seconds=float(metadata.get("durationSeconds") or 0),
                )
            )
        job_id, output_url = await self.editing_provider.submit(
            workflow_id=workflow.id,
            # ICE only accepts canonical OSS URLs from its own region. Persist
            # the KYY result into the unified OSS bucket first, then submit its
            # canonical URL instead of the public CNAME.
            raw_video_url=_ice_source_url(raw_key, fallback=result.media_url),
            duration_seconds=float(metadata.get("durationSeconds") or 0),
            options=EditingOptions(
                title=workflow.title or "数字人口播视频",
                script_text=str(
                    (workflow.input_payload or {}).get("scriptText") or ""
                ),
                subtitles_enabled=bool(editing.get("subtitlesEnabled", True)),
                background_url=str(editing.get("backgroundUrl") or ""),
                bubble_url=str(editing.get("bubbleUrl") or ""),
                background_music_url=background_music_url,
                background_music_gain=_editing_gain(
                    editing.get("backgroundMusicGain")
                ),
                subtitle_cues=subtitle_cues_from_payload(
                    (external.sanitized_request or {}).get("subtitleCues")
                ),
            ),
        )
        now = datetime.now(UTC)
        with SessionLocal() as session:
            row = session.get(WorkflowExternalTaskRecord, workflow.id)
            record = session.get(WorkflowRecord, workflow.id)
            if row is None or record is None:
                return
            row.provider = "aliyun_ice"
            row.provider_task_id = job_id
            row.provider_status = "processing"
            row.poll_attempts = 0
            row.consecutive_errors = 0
            row.sanitized_request = {
                **dict(row.sanitized_request or {}),
                "rawVideoUrl": raw_url,
                "iceOutputUrl": output_url,
                "backgroundMusicMeta": background_music_meta,
            }
            row.last_response = {}
            row.next_poll_at = now + timedelta(
                seconds=settings.digital_human_poll_interval_seconds
            )
            row.lease_owner = ""
            row.lease_expires_at = None
            row.updated_at = now
            record.status = "running"
            record.progress = 80
            record.current_stage = "editing_video"
            record.result_payload = {
                "profileId": (record.input_payload or {}).get("profileId"),
                "rawVideoUrl": result.media_url,
                "persistedRawVideoUrl": raw_url,
                "backgroundMusicMeta": background_music_meta,
            }
            record.error = ""
            record.updated_at = now
            session.commit()

    async def _prepare_background_music_asset(
        self,
        workflow: WorkflowRecord,
        *,
        source_url: str,
        duration_seconds: float,
    ) -> tuple[str, dict[str, Any]]:
        with TemporaryDirectory(prefix="starx-digital-human-bgm-") as temp_dir:
            source_path = Path(temp_dir) / "source"
            prepared_path = Path(temp_dir) / "background-music.wav"
            await download_media(
                source_url,
                source_path,
                max_bytes=settings.digital_human_max_source_video_bytes,
            )
            metadata = await inspect_audio(source_path)
            metadata.update(await measure_audio_loudness(source_path))
            await prepare_background_music(
                source_path,
                prepared_path,
                max_duration_seconds=duration_seconds,
            )
            key = (
                f"digital-human/{workflow.account_id}/jobs/{workflow.id}/"
                "background-music.wav"
            )
            url = await asyncio.to_thread(
                self.storage.put_file,
                key,
                prepared_path,
                "audio/wav",
            )
        self._add_asset(
            workflow,
            asset_type="background_music",
            file_name="background-music.wav",
            mime_type="audio/wav",
            storage_key=key,
            url=url,
        )
        return _ice_source_url(key, fallback=url), metadata

    async def _poll_editing(
        self, workflow: WorkflowRecord, external: WorkflowExternalTaskRecord
    ) -> None:
        if external.poll_attempts >= external.max_poll_attempts:
            self._fail(workflow.id, "阿里云剪辑合成超时")
            return
        result = await self.editing_provider.get_result(external.provider_task_id)
        if result.state == "failed":
            self._fail(
                workflow.id,
                result.error_message or "阿里云剪辑合成失败",
                result.raw,
            )
            return
        if result.state != "completed":
            self._reschedule(workflow.id, result.raw)
            return
        final_source_url = result.media_url or str(
            (external.sanitized_request or {}).get("iceOutputUrl") or ""
        )
        if not final_source_url:
            raise ValueError("阿里云剪辑完成但未返回成片地址")
        self._update_workflow(
            workflow.id, progress=95, current_stage="persisting_video"
        )
        with TemporaryDirectory(prefix="starx-digital-human-final-") as temp_dir:
            path = Path(temp_dir) / "result.mp4"
            await download_media(
                final_source_url,
                path,
                max_bytes=settings.digital_human_max_result_video_bytes,
            )
            final_metadata = await inspect_video(path)
            final_loudness = await measure_audio_loudness(path)
            key = (
                f"digital-human/{workflow.account_id}/jobs/{workflow.id}/result.mp4"
            )
            final_url = await asyncio.to_thread(
                self.storage.put_file,
                key,
                path,
                "video/mp4",
            )
        self._add_asset(
            workflow,
            asset_type="result_video",
            file_name="result.mp4",
            mime_type="video/mp4",
            storage_key=key,
            url=final_url,
        )
        now = datetime.now(UTC)
        with SessionLocal() as session:
            row = session.get(WorkflowExternalTaskRecord, workflow.id)
            record = session.get(WorkflowRecord, workflow.id)
            if row is None or record is None:
                return
            row.provider_status = "completed"
            row.last_response = _sanitize(result.raw)
            row.completed_at = now
            row.lease_owner = ""
            row.lease_expires_at = None
            row.updated_at = now
            record.status = "completed"
            record.progress = 100
            record.current_stage = "completed"
            record.error = ""
            record.result_payload = {
                **dict(record.result_payload or {}),
                "aliyunVideoUrl": final_source_url,
                "finalVideoUrl": final_url,
                "mediaInfo": {
                    **final_metadata,
                    **final_loudness,
                },
            }
            record.updated_at = now
            session.commit()

    def _reschedule(self, workflow_id: str, response: dict[str, Any] | None) -> None:
        now = datetime.now(UTC)
        with SessionLocal() as session:
            row = session.get(WorkflowExternalTaskRecord, workflow_id)
            if row is None:
                return
            row.poll_attempts += 1
            row.consecutive_errors = 0
            row.provider_status = "processing"
            row.last_response = _sanitize(response)
            row.next_poll_at = now + timedelta(seconds=settings.digital_human_poll_interval_seconds)
            row.lease_owner = ""
            row.lease_expires_at = None
            row.updated_at = now
            session.commit()

    def _record_transient_error(self, workflow_id: str, message: str) -> None:
        now = datetime.now(UTC)
        with SessionLocal() as session:
            row = session.get(WorkflowExternalTaskRecord, workflow_id)
            record = session.get(WorkflowRecord, workflow_id)
            if row is None or record is None:
                return
            row.consecutive_errors += 1
            row.poll_attempts += 1
            if (
                row.consecutive_errors
                >= settings.digital_human_max_consecutive_errors
                or row.poll_attempts >= row.max_poll_attempts
            ):
                record.status = "failed"
                record.current_stage = "failed"
                record.error = message[:2000]
                row.provider_status = "failed"
            else:
                delay = min(30 * (2 ** (row.consecutive_errors - 1)), 300)
                row.next_poll_at = now + timedelta(seconds=delay)
                record.error = f"临时错误，系统将自动重试：{message}"[:2000]
            row.lease_owner = ""
            row.lease_expires_at = None
            row.updated_at = now
            record.updated_at = now
            session.commit()

    def _fail(
        self, workflow_id: str, message: str, response: dict[str, Any] | None = None
    ) -> None:
        now = datetime.now(UTC)
        with SessionLocal() as session:
            row = session.get(WorkflowExternalTaskRecord, workflow_id)
            record = session.get(WorkflowRecord, workflow_id)
            if row is None or record is None:
                return
            row.provider_status = "failed"
            row.last_response = _sanitize(response)
            row.lease_owner = ""
            row.lease_expires_at = None
            row.updated_at = now
            record.status = "failed"
            record.current_stage = "failed"
            record.error = message
            record.updated_at = now
            session.commit()

    @staticmethod
    def _update_workflow(workflow_id: str, **values: Any) -> None:
        with SessionLocal() as session:
            record = session.get(WorkflowRecord, workflow_id)
            if record is None:
                return
            for key, value in values.items():
                setattr(record, key, value)
            record.updated_at = datetime.now(UTC)
            session.commit()

    @staticmethod
    def _add_asset(
        workflow: WorkflowRecord,
        *,
        asset_type: str,
        file_name: str,
        mime_type: str,
        storage_key: str,
        url: str,
    ) -> None:
        with SessionLocal() as session:
            existing = session.scalar(
                select(GenerationAssetRecord).where(
                    GenerationAssetRecord.workflow_id == workflow.id,
                    GenerationAssetRecord.asset_type == asset_type,
                )
            )
            if existing is not None:
                existing.file_name = file_name
                existing.mime_type = mime_type
                existing.storage_key = storage_key
                existing.url = url
                existing.status = "completed"
                existing.error = ""
                session.commit()
                return
            session.add(
                GenerationAssetRecord(
                    id=f"ga_{uuid4().hex}",
                    workflow_id=workflow.id,
                    account_id=str(workflow.account_id),
                    asset_type=asset_type,
                    file_name=file_name,
                    mime_type=mime_type,
                    storage_key=storage_key,
                    url=url,
                    status="completed",
                    analysis="",
                    error="",
                    meta={},
                    created_at=datetime.now(UTC),
                )
            )
            session.commit()

    async def _run(self) -> None:
        stop_event = self._stop_event
        if stop_event is None:
            return
        while not stop_event.is_set():
            try:
                await self.scan_once()
            except Exception:
                logger.exception("digital human reconciler scan failed")
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=self.scan_seconds)
            except TimeoutError:
                continue


def _sanitize(value: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    blocked = {"token", "authorization", "app_key", "appId", "secret"}
    return {
        key: ("***" if key.lower() in {item.lower() for item in blocked} else item)
        for key, item in value.items()
    }


def _editing_gain(value: Any) -> float:
    """兼容修复上线前以 dB 负数持久化的少量未完成任务。"""
    if value is None:
        return 0.1
    gain = float(value)
    if gain < 0:
        gain = 10 ** (gain / 20)
    return min(10.0, max(0.0, gain))


def _ice_source_url(storage_key: str, *, fallback: str) -> str:
    if (
        settings.object_storage_provider == "oss"
        and settings.object_storage_region == settings.digital_human_ice_region
        and settings.object_storage_bucket
    ):
        return (
            f"https://{settings.object_storage_bucket}."
            f"oss-{settings.object_storage_region}.aliyuncs.com/"
            f"{quote(storage_key, safe='/')}"
        )
    return fallback


digital_human_reconciler = DigitalHumanReconciler()
