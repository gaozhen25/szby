from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from app.core.config import settings
from app.core.database import SessionLocal
from app.db.models import DigitalHumanProfileRecord
from app.services.digital_human.media import (
    download_media,
    extract_audio,
    extract_cover,
    inspect_video,
)
from app.services.digital_human.providers import DashScopeVoiceProvider

from .base import BaseWorkflow, WorkflowRegister


@WorkflowRegister.register
class DigitalHumanEnrollmentWorkflow(BaseWorkflow):
    type = "digital_human_enrollment"
    requires_ai = False

    async def execute(self) -> dict[str, Any]:
        record = self.store.get_workflow(self.workflow_id)
        if record is None:
            raise ValueError("数字人创建任务不存在")
        profile_id = str((record.input_payload or {}).get("profileId") or "")
        profile = self._get_profile(profile_id)
        if profile is None:
            raise ValueError("数字人档案不存在")

        try:
            self.store.update_progress(
                self.workflow_id, progress=10, current_stage="validating_video"
            )
            self._update_profile(profile_id, status="validating", error_code="", error_message="")
            with TemporaryDirectory(prefix="starx-digital-human-") as temp_dir:
                temp = Path(temp_dir)
                video_path = temp / "source.mp4"
                audio_path = temp / "source.mp3"
                cover_path = temp / "cover.jpg"
                await download_media(
                    profile.source_video_url,
                    video_path,
                    max_bytes=settings.digital_human_max_source_video_bytes,
                )
                report = await inspect_video(video_path)
                duration = float(report["durationSeconds"])
                if duration < settings.digital_human_source_min_seconds:
                    raise ValueError(
                        f"视频时长不能少于 {settings.digital_human_source_min_seconds} 秒"
                    )
                if duration > settings.digital_human_source_max_seconds:
                    raise ValueError(
                        f"视频时长不能超过 {settings.digital_human_source_max_seconds} 秒"
                    )
                if int(report["width"]) < 720 and int(report["height"]) < 720:
                    raise ValueError("视频分辨率过低，请上传至少 720p 的视频")

                self.store.update_progress(
                    self.workflow_id, progress=30, current_stage="extracting_audio"
                )
                await extract_audio(video_path, audio_path)
                await extract_cover(video_path, cover_path)
                base = f"digital-human/{profile.account_id}/{profile.id}"
                audio_key = f"{base}/source-audio.mp3"
                cover_key = f"{base}/cover.jpg"
                audio_url = self.storage.put_file(audio_key, audio_path, "audio/mpeg")
                cover_url = self.storage.put_file(cover_key, cover_path, "image/jpeg")
                self._update_profile(
                    profile_id,
                    source_audio_storage_key=audio_key,
                    source_audio_url=audio_url,
                    cover_storage_key=cover_key,
                    cover_url=cover_url,
                    width=int(report["width"]),
                    height=int(report["height"]),
                    duration_seconds=round(duration),
                    validation_report={**report, "status": "passed"},
                    status="cloning_voice",
                )

                self.store.update_progress(
                    self.workflow_id, progress=60, current_stage="cloning_voice"
                )
                voice_provider = DashScopeVoiceProvider()
                voice_id = await voice_provider.create_voice(
                    name=f"starx{profile.id[-8:]}",
                    audio_url=audio_url,
                )
                self._update_profile(
                    profile_id,
                    provider_voice_id=voice_id,
                    voice_status="ready",
                )

                self.store.update_progress(
                    self.workflow_id,
                    progress=80,
                    current_stage="generating_voice_preview",
                )
                preview_bytes = await voice_provider.synthesize(
                    voice_id=voice_id,
                    text="你好，这是我的数字人克隆声音试听。",
                )
                preview_key = f"{base}/voice-preview.mp3"
                preview_url = self.storage.put_bytes(
                    preview_key, preview_bytes, "audio/mpeg"
                )
                self._update_profile(
                    profile_id,
                    status="ready",
                    voice_preview_storage_key=preview_key,
                    voice_preview_url=preview_url,
                    updated_at=datetime.now(UTC),
                )
            return {
                "profileId": profile_id,
                "status": "ready",
                "voicePreviewUrl": preview_url,
                "validation": report,
            }
        except Exception as exc:
            self._update_profile(
                profile_id,
                status="failed",
                voice_status="failed",
                error_code="enrollment_failed",
                error_message=str(exc),
                updated_at=datetime.now(UTC),
            )
            raise

    @staticmethod
    def _get_profile(profile_id: str) -> DigitalHumanProfileRecord | None:
        with SessionLocal() as session:
            return session.get(DigitalHumanProfileRecord, profile_id)

    @staticmethod
    def _update_profile(profile_id: str, **values: Any) -> None:
        with SessionLocal() as session:
            profile = session.get(DigitalHumanProfileRecord, profile_id)
            if profile is None:
                return
            for key, value in values.items():
                setattr(profile, key, value)
            profile.updated_at = values.get("updated_at") or datetime.now(UTC)
            session.commit()
