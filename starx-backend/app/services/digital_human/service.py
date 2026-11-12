from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.config import settings
from app.db.models import (
    AccountRecord,
    DigitalHumanProfileRecord,
    WorkflowExternalTaskRecord,
    WorkflowRecord,
)
from app.services.object_storage import default_object_storage
from app.services.workflow import WorkflowScheduler

from .training_script import get_training_script

DIGITAL_HUMAN_ENROLLMENT_TYPE = "digital_human_enrollment"
DIGITAL_HUMAN_VIDEO_TYPE = "digital_human_video"
ALLOWED_VIDEO_TYPES = {"video/mp4", "video/quicktime"}
ALLOWED_VIDEO_EXTENSIONS = {".mp4", ".mov"}


class DigitalHumanService:
    def __init__(
        self,
        session: Session,
        *,
        storage: Any = default_object_storage,
        scheduler: WorkflowScheduler | None = None,
    ) -> None:
        self.session = session
        self.storage = storage
        self.scheduler = scheduler or WorkflowScheduler.get_instance()

    def require_account(self, user_id: str, account_id: str) -> AccountRecord:
        account = self.session.scalar(
            select(AccountRecord).where(
                AccountRecord.id == account_id,
                AccountRecord.user_id == user_id,
                AccountRecord.status == "active",
            )
        )
        if account is None:
            raise StopIteration("账号不存在或不可用")
        return account

    def list_profiles(
        self, user_id: str, account_id: str, *, include_disabled: bool = False
    ) -> list[DigitalHumanProfileRecord]:
        self.require_account(user_id, account_id)
        statement = select(DigitalHumanProfileRecord).where(
            DigitalHumanProfileRecord.user_id == user_id,
            DigitalHumanProfileRecord.account_id == account_id,
        )
        if not include_disabled:
            statement = statement.where(DigitalHumanProfileRecord.status != "disabled")
        return list(
            self.session.scalars(
                statement.order_by(DigitalHumanProfileRecord.created_at.desc())
            ).all()
        )

    def get_profile(
        self, user_id: str, account_id: str, profile_id: str
    ) -> DigitalHumanProfileRecord:
        profile = self.session.scalar(
            select(DigitalHumanProfileRecord).where(
                DigitalHumanProfileRecord.id == profile_id,
                DigitalHumanProfileRecord.user_id == user_id,
                DigitalHumanProfileRecord.account_id == account_id,
            )
        )
        if profile is None:
            raise StopIteration("数字人档案不存在")
        return profile

    def create_profile(
        self,
        *,
        user_id: str,
        account_id: str,
        name: str,
        filename: str,
        content_type: str,
        source_video_url: str,
        source_video_storage_key: str,
        source_video_size_bytes: int,
        training_script_version: str,
        consent_confirmed: bool,
    ) -> tuple[DigitalHumanProfileRecord, WorkflowRecord]:
        self.require_account(user_id, account_id)
        clean_name = str(name or "").strip()
        if not clean_name:
            raise ValueError("数字人名称不能为空")
        if not consent_confirmed:
            raise ValueError("必须确认肖像和声音克隆授权")
        suffix = Path(filename or "").suffix.lower()
        if content_type.lower() not in ALLOWED_VIDEO_TYPES or suffix not in ALLOWED_VIDEO_EXTENSIONS:
            raise ValueError("仅支持 MP4 或 MOV 视频")
        if not source_video_url or not source_video_storage_key:
            raise ValueError("上传视频不能为空")
        if source_video_size_bytes <= 0:
            raise ValueError("上传视频不能为空")
        if source_video_size_bytes > settings.digital_human_max_source_video_bytes:
            raise ValueError("上传视频超过允许大小")
        script = get_training_script(training_script_version)
        now = datetime.now(UTC)
        profile_id = f"dhp_{uuid4().hex}"
        workflow_id = f"wf_{uuid4().hex}"
        profile = DigitalHumanProfileRecord(
            id=profile_id,
            user_id=user_id,
            account_id=account_id,
            name=clean_name[:128],
            status="validating",
            source_video_storage_key=source_video_storage_key,
            source_video_url=source_video_url,
            training_script_version=script.version,
            training_script_snapshot=script.text,
            training_script_hash=script.digest,
            validation_report={},
            voice_provider="dashscope",
            voice_status="pending",
            enrollment_workflow_id=workflow_id,
            consent_version="v1",
            consent_confirmed_at=now,
            created_at=now,
            updated_at=now,
        )
        workflow = WorkflowRecord(
            id=workflow_id,
            account_id=account_id,
            user_id=user_id,
            type=DIGITAL_HUMAN_ENROLLMENT_TYPE,
            status="pending",
            progress=0,
            current_stage="uploaded",
            creation_id=None,
            target_platform="",
            title=f"创建数字人：{clean_name[:128]}",
            input_payload={
                "profileId": profile_id,
                "trainingScriptVersion": script.version,
            },
            result_payload={},
            error="",
            created_at=now,
            updated_at=now,
        )
        try:
            # Profile enrollment_workflow_id references this newly-created workflow.
            # Flush it first because there is no ORM relationship between the two
            # records for SQLAlchemy's unit-of-work sorter to infer insert order.
            self.session.add(workflow)
            self.session.flush()
            self.session.add(profile)
            self.session.commit()
        except Exception:
            self.session.rollback()
            raise
        self.session.refresh(profile)
        self.session.refresh(workflow)
        self.scheduler.submit(DIGITAL_HUMAN_ENROLLMENT_TYPE, workflow_id)
        return profile, workflow

    def disable_profile(
        self, user_id: str, account_id: str, profile_id: str
    ) -> DigitalHumanProfileRecord:
        profile = self.get_profile(user_id, account_id, profile_id)
        profile.status = "disabled"
        profile.updated_at = datetime.now(UTC)
        self.session.commit()
        self.session.refresh(profile)
        return profile

    def create_video_workflow(
        self,
        *,
        user_id: str,
        account_id: str,
        profile_id: str,
        creation_id: str,
        title: str,
        script_text: str,
        speed: float,
        subtitles_enabled: bool = True,
        background_url: str = "",
        bubble_url: str = "",
        background_music_url: str = "",
        background_music_gain: float = 0.1,
        idempotency_key: str,
    ) -> WorkflowRecord:
        self.require_account(user_id, account_id)
        profile = self.get_profile(user_id, account_id, profile_id)
        if profile.status != "ready" or not profile.provider_voice_id:
            raise ValueError("数字人尚未创建完成")
        clean_script = str(script_text or "").strip()
        if not clean_script:
            raise ValueError("口播文案不能为空")
        clean_background_url = _clean_media_url(background_url, "背景素材")
        clean_bubble_url = _clean_media_url(bubble_url, "气泡素材")
        clean_background_music_url = _clean_media_url(
            background_music_url, "背景音乐"
        )
        clean_background_music_gain = float(background_music_gain)
        if not 0 <= clean_background_music_gain <= 10:
            raise ValueError("背景音乐 Gain 必须在 0 到 10 之间")
        clean_key = re.sub(r"[^A-Za-z0-9_.:-]", "", str(idempotency_key or ""))[:128]
        if clean_key:
            existing = self.session.scalar(
                select(WorkflowRecord)
                .options(selectinload(WorkflowRecord.assets))
                .where(
                    WorkflowRecord.user_id == user_id,
                    WorkflowRecord.account_id == account_id,
                    WorkflowRecord.type == DIGITAL_HUMAN_VIDEO_TYPE,
                    WorkflowRecord.input_payload["idempotencyKey"].as_string() == clean_key,
                )
                .order_by(WorkflowRecord.created_at.desc())
                .limit(1)
            )
            if existing is not None:
                return existing
        now = datetime.now(UTC)
        workflow = WorkflowRecord(
            id=f"wf_{uuid4().hex}",
            account_id=account_id,
            user_id=user_id,
            type=DIGITAL_HUMAN_VIDEO_TYPE,
            status="pending",
            progress=0,
            current_stage="preparing_voice",
            creation_id=str(creation_id or "").strip() or None,
            target_platform="",
            title=str(title or "").strip()[:255],
            requested_count=1,
            input_payload={
                "profileId": profile.id,
                "scriptText": clean_script,
                "speed": float(speed),
                "editing": {
                    "subtitlesEnabled": bool(subtitles_enabled),
                    "backgroundUrl": clean_background_url,
                    "bubbleUrl": clean_bubble_url,
                    "backgroundMusicUrl": clean_background_music_url,
                    "backgroundMusicGain": clean_background_music_gain,
                },
                "idempotencyKey": clean_key,
            },
            result_payload={},
            error="",
            created_at=now,
            updated_at=now,
        )
        external = WorkflowExternalTaskRecord(
            workflow_id=workflow.id,
            provider="kyy",
            provider_status="pending",
            next_poll_at=now,
            max_poll_attempts=settings.digital_human_poll_max_attempts,
            sanitized_request={"profileId": profile.id, "title": workflow.title},
            last_response={},
            updated_at=now,
        )
        self.session.add(workflow)
        self.session.add(external)
        self.session.commit()
        self.session.refresh(workflow)
        return workflow


def _clean_media_url(value: str, label: str) -> str:
    url = str(value or "").strip()
    if not url:
        return ""
    if urlparse(url).scheme not in {"http", "https"}:
        raise ValueError(f"{label}地址必须使用 HTTP 或 HTTPS")
    return url
