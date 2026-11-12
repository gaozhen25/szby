from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.deps import get_current_user, get_service
from app.models.user import User
from app.schemas.digital_human import (
    CreateDigitalHumanProfileResponse,
    CreateDigitalHumanProfileRequest,
    DigitalHumanProfileSchema,
    DigitalHumanTrainingScriptSchema,
    DigitalHumanVideoCreateRequest,
    DigitalHumanVideoListResponse,
)
from app.schemas.generation import WorkflowSchema
from app.services.digital_human.service import DIGITAL_HUMAN_VIDEO_TYPE, DigitalHumanService
from app.services.digital_human.training_script import DEFAULT_TRAINING_SCRIPT
from app.services.uploads import DirectUploadError, DirectUploadService
from app.api.routes.uploads import get_direct_upload_service
from app.services.workflow.service import WorkflowService
from app.services.db_service import DBService

router = APIRouter()


def get_digital_human_service(
    db_service: DBService = Depends(get_service),
) -> DigitalHumanService:
    return DigitalHumanService(db_service.session)


def get_workflow_service(
    db_service: DBService = Depends(get_service),
) -> WorkflowService:
    return WorkflowService(db_service.session)


@router.get(
    "/digital-human/training-script",
    response_model=DigitalHumanTrainingScriptSchema,
)
def get_training_script() -> DigitalHumanTrainingScriptSchema:
    script = DEFAULT_TRAINING_SCRIPT
    return DigitalHumanTrainingScriptSchema(
        version=script.version,
        text=script.text,
        minDurationSeconds=script.min_duration_seconds,
        maxDurationSeconds=script.max_duration_seconds,
        recommendedDurationSeconds=script.recommended_duration_seconds,
        instructions=list(script.instructions),
    )


@router.get(
    "/accounts/{account_id}/digital-human/profiles",
    response_model=list[DigitalHumanProfileSchema],
)
def list_profiles(
    account_id: str,
    include_disabled: bool = False,
    user: User = Depends(get_current_user),
    service: DigitalHumanService = Depends(get_digital_human_service),
) -> list[DigitalHumanProfileSchema]:
    try:
        records = service.list_profiles(
            user.id, account_id, include_disabled=include_disabled
        )
    except StopIteration as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return [_profile_schema(record) for record in records]


@router.get(
    "/accounts/{account_id}/digital-human/profiles/{profile_id}",
    response_model=DigitalHumanProfileSchema,
)
def get_profile(
    account_id: str,
    profile_id: str,
    user: User = Depends(get_current_user),
    service: DigitalHumanService = Depends(get_digital_human_service),
) -> DigitalHumanProfileSchema:
    try:
        return _profile_schema(service.get_profile(user.id, account_id, profile_id))
    except StopIteration as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post(
    "/accounts/{account_id}/digital-human/profiles",
    response_model=CreateDigitalHumanProfileResponse,
)
def create_profile(
    account_id: str,
    payload: CreateDigitalHumanProfileRequest,
    user: User = Depends(get_current_user),
    service: DigitalHumanService = Depends(get_digital_human_service),
    workflows: WorkflowService = Depends(get_workflow_service),
    uploads: DirectUploadService = Depends(get_direct_upload_service),
) -> CreateDigitalHumanProfileResponse:
    try:
        upload = uploads.verify_ref(
            user_id=user.id,
            ref=payload.sourceVideo,
            purposes={"digital_human_source"},
            account_id=account_id,
        )
        assert upload is not None
        profile, workflow = service.create_profile(
            user_id=user.id,
            account_id=account_id,
            name=payload.name,
            filename=upload.filename,
            content_type=upload.actual_content_type,
            source_video_url=upload.object_url,
            source_video_storage_key=upload.object_key,
            source_video_size_bytes=upload.actual_size_bytes,
            training_script_version=payload.trainingScriptVersion,
            consent_confirmed=payload.consentConfirmed,
        )
        uploads.mark_consumed([upload], resource_type="digital_human_profile", resource_id=profile.id)
        service.session.commit()
        workflow_schema = workflows.get_job(user.id, account_id, workflow.id)
    except DirectUploadError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except StopIteration as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return CreateDigitalHumanProfileResponse(
        profile=_profile_schema(profile),
        workflow=workflow_schema,
    )


@router.delete(
    "/accounts/{account_id}/digital-human/profiles/{profile_id}",
    response_model=DigitalHumanProfileSchema,
)
def disable_profile(
    account_id: str,
    profile_id: str,
    user: User = Depends(get_current_user),
    service: DigitalHumanService = Depends(get_digital_human_service),
) -> DigitalHumanProfileSchema:
    try:
        return _profile_schema(service.disable_profile(user.id, account_id, profile_id))
    except StopIteration as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post(
    "/accounts/{account_id}/digital-human/videos",
    response_model=WorkflowSchema,
)
def create_video(
    account_id: str,
    payload: DigitalHumanVideoCreateRequest,
    user: User = Depends(get_current_user),
    service: DigitalHumanService = Depends(get_digital_human_service),
    workflows: WorkflowService = Depends(get_workflow_service),
    uploads: DirectUploadService = Depends(get_direct_upload_service),
) -> WorkflowSchema:
    try:
        editing_uploads = uploads.verify_urls(
            user_id=user.id,
            urls=[payload.backgroundUrl, payload.bubbleUrl],
            purposes={"digital_human_editing_asset"},
            account_id=account_id,
            allow_external=True,
        )
        music_uploads = uploads.verify_urls(
            user_id=user.id,
            urls=[payload.backgroundMusicUrl],
            purposes={
                "digital_human_background_music",
                "digital_human_editing_asset",
            },
            account_id=account_id,
            allow_external=True,
        )
        if any(
            not (
                str(item.actual_content_type or "").startswith("audio/")
                or str(item.actual_content_type or "") == "video/mp4"
            )
            for item in music_uploads
        ):
            raise ValueError("背景音乐必须是音频文件或带音轨的 MP4 文件")
        workflow = service.create_video_workflow(
            user_id=user.id,
            account_id=account_id,
            profile_id=payload.profileId,
            creation_id=payload.creationId,
            title=payload.title,
            script_text=payload.scriptText,
            speed=payload.speed,
            subtitles_enabled=payload.subtitlesEnabled,
            background_url=payload.backgroundUrl,
            bubble_url=payload.bubbleUrl,
            background_music_url=payload.backgroundMusicUrl,
            background_music_gain=payload.backgroundMusicGain,
            idempotency_key=payload.idempotencyKey,
        )
        uploads.mark_consumed(
            [*editing_uploads, *music_uploads],
            resource_type="digital_human_video",
            resource_id=workflow.id,
        )
        service.session.commit()
        return workflows.get_job(user.id, account_id, workflow.id)
    except DirectUploadError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except StopIteration as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get(
    "/accounts/{account_id}/digital-human/videos",
    response_model=DigitalHumanVideoListResponse,
)
def list_videos(
    account_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(4, alias="pageSize", ge=1, le=100),
    creation_id: str | None = Query(None, alias="creationId", max_length=64),
    user: User = Depends(get_current_user),
    workflows: WorkflowService = Depends(get_workflow_service),
) -> DigitalHumanVideoListResponse:
    try:
        items, total, page_value, page_size_value = workflows.list_jobs_page(
            user.id,
            account_id,
            page=page,
            page_size=page_size,
            job_type=DIGITAL_HUMAN_VIDEO_TYPE,
            creation_id=creation_id,
        )
    except StopIteration as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return DigitalHumanVideoListResponse(
        items=items,
        total=total,
        page=page_value,
        pageSize=page_size_value,
    )


def _profile_schema(record) -> DigitalHumanProfileSchema:  # noqa: ANN001
    return DigitalHumanProfileSchema(
        id=record.id,
        accountId=record.account_id,
        name=record.name,
        status=record.status,
        sourceVideoUrl=record.source_video_url,
        coverUrl=record.cover_url,
        width=record.width,
        height=record.height,
        durationSeconds=record.duration_seconds,
        trainingScriptVersion=record.training_script_version,
        validationReport=record.validation_report or {},
        voiceStatus=record.voice_status,
        voicePreviewUrl=record.voice_preview_url,
        enrollmentWorkflowId=record.enrollment_workflow_id,
        errorCode=record.error_code,
        errorMessage=record.error_message,
        createdAt=record.created_at,
        updatedAt=record.updated_at,
    )
