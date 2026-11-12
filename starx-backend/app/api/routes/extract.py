from datetime import UTC, datetime
import re
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from typing import Any

from app.api.deps import get_ai_service, get_current_user, get_service
from app.core.logging import get_logger
from app.db.models import ExtractHistoryRecord, WorkflowRecord
from app.models.user import User
from app.schemas.extract import (
    BindExtractHistoryRequest,
    CreateVideoAnalysisWorkflowRequest,
    ExtractHistorySchema,
    ExtractLinkRequest,
    ExtractLinkResponse,
    ExtractProfileRequest,
    ExtractProfileResponse,
    VideoAnalysisWorkflowSchema,
)
from app.services.ai_service import AIService
from app.services.db_service import DBService
from app.services.extract_service.extract_service import UnsupportedPlatformError
from app.services.extract_service.platforms.base import ExtractError
from app.services.extract_service.profile_service import ProfileExtractService
from app.services.extract_service.reference_service import (
    ExtractReferenceError,
    ExtractReferenceService,
)
from app.services.workflow import WorkflowService
from app.services.workflow.scheduler import WorkflowScheduler

router = APIRouter(prefix="/extract")
HASHTAG_RE = re.compile(r"#[\w\u4e00-\u9fff-]+")
DESCRIPTION_HASHTAG_RE = re.compile(
    r"#[\w\u4e00-\u9fff-]+(?:\s*\[话题\]\s*#?)?"
)
logger = get_logger("starx.extract")


def get_extract_reference_service() -> ExtractReferenceService:
    return ExtractReferenceService()


def get_profile_extract_service() -> ProfileExtractService:
    return ProfileExtractService()


def get_video_analysis_scheduler() -> WorkflowScheduler:
    return WorkflowScheduler.get_instance()


@router.post("/link-reference", response_model=ExtractLinkResponse)
def extract_link_reference(
    payload: ExtractLinkRequest,
    user: User = Depends(get_current_user),
    db_service: DBService = Depends(get_service),
    extractor_service: ExtractReferenceService = Depends(get_extract_reference_service),
) -> ExtractLinkResponse:
    # Auth reads open a transaction; release it before slow external extraction.
    db_service.session.rollback()
    try:
        result = ExtractLinkResponse.model_validate(extractor_service.extract_from_text(payload.text))
    except UnsupportedPlatformError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ExtractReferenceError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    result.hashtags = result.hashtags or _extract_hashtags(f"{result.title} {result.description}")
    result.description = _strip_hashtags_from_description(result.description)
    result.historyId = _save_history(db_service.session, user.id, result, payload)
    return result


@router.post("/creator-profile", response_model=ExtractProfileResponse)
def extract_creator_profile(
    payload: ExtractProfileRequest,
    user: User = Depends(get_current_user),  # noqa: ARG001
    db_service: DBService = Depends(get_service),
    extractor_service: ProfileExtractService = Depends(get_profile_extract_service),
) -> ExtractProfileResponse:
    # 认证查询会开启事务；在公开网络请求前释放数据库连接。
    db_service.session.rollback()
    try:
        return ExtractProfileResponse.model_validate(
            extractor_service.extract(payload.url, limit=payload.limit)
        )
    except (UnsupportedPlatformError, ExtractError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/link-reference/history", response_model=list[ExtractHistorySchema])
def list_link_reference_history(
    limit: int = 20,
    accountId: str | None = None,
    creationId: str | None = None,
    taskId: str | None = None,
    user: User = Depends(get_current_user),
    db_service: DBService = Depends(get_service),
) -> list[ExtractHistorySchema]:
    bounded_limit = min(max(limit, 1), 100)
    statement = select(ExtractHistoryRecord).where(ExtractHistoryRecord.user_id == user.id)
    if accountId:
        statement = statement.where(ExtractHistoryRecord.account_id == accountId)
    if creationId:
        statement = statement.where(ExtractHistoryRecord.creation_id == creationId)
    if taskId:
        statement = statement.where(ExtractHistoryRecord.task_id == taskId)
    records = db_service.session.scalars(
        statement.order_by(ExtractHistoryRecord.created_at.desc()).limit(bounded_limit)
    ).all()
    return [_history_schema(record) for record in records]


@router.patch("/link-reference/history/bind", response_model=list[ExtractHistorySchema])
def bind_link_reference_history(
    payload: BindExtractHistoryRequest,
    user: User = Depends(get_current_user),
    db_service: DBService = Depends(get_service),
) -> list[ExtractHistorySchema]:
    if not payload.historyIds:
        return []
    records = db_service.session.scalars(
        select(ExtractHistoryRecord).where(
            ExtractHistoryRecord.user_id == user.id,
            ExtractHistoryRecord.id.in_(payload.historyIds),
        )
    ).all()
    for record in records:
        if payload.creationId:
            record.creation_id = payload.creationId
        if payload.taskId:
            record.task_id = payload.taskId
    db_service.session.commit()
    return [_history_schema(record) for record in records]


@router.post("/video-analysis-jobs", response_model=VideoAnalysisWorkflowSchema)
async def create_video_analysis_job(
    payload: CreateVideoAnalysisWorkflowRequest,
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
    db_service: DBService = Depends(get_service),
    scheduler: WorkflowScheduler = Depends(get_video_analysis_scheduler),
    ai_service: AIService = Depends(get_ai_service),
) -> VideoAnalysisWorkflowSchema:
    try:
        schema = WorkflowService(db_service.session).create_video_analysis_job(user.id, payload)
    except StopIteration as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    scheduler.submit(
        "video_analysis",
        schema.id,
        context={
            "video_url": schema.videoUrl,
            "user_id": user.id,
            "account_id": schema.accountId,
            "_ai_service": ai_service,
        },
    )
    return schema


@router.get("/video-analysis-jobs", response_model=list[VideoAnalysisWorkflowSchema])
def list_video_analysis_jobs(
    limit: int = 20,
    accountId: str | None = None,
    creationId: str | None = None,
    user: User = Depends(get_current_user),
    db_service: DBService = Depends(get_service),
) -> list[VideoAnalysisWorkflowSchema]:
    bounded_limit = min(max(limit, 1), 100)
    statement = select(WorkflowRecord).where(
        WorkflowRecord.user_id == user.id,
        WorkflowRecord.type == "video_analysis",
    )
    if accountId:
        statement = statement.where(WorkflowRecord.account_id == accountId)
    if creationId:
        statement = statement.where(WorkflowRecord.creation_id == creationId)
    records = db_service.session.scalars(
        statement.order_by(WorkflowRecord.created_at.desc()).limit(bounded_limit)
    ).all()
    return [_video_analysis_to_schema(record) for record in records]


@router.get("/video-analysis-jobs/{job_id}", response_model=VideoAnalysisWorkflowSchema)
def get_video_analysis_job(
    job_id: str,
    user: User = Depends(get_current_user),
    db_service: DBService = Depends(get_service),
) -> VideoAnalysisWorkflowSchema:
    record = db_service.session.scalar(
        select(WorkflowRecord).where(
            WorkflowRecord.id == job_id,
            WorkflowRecord.user_id == user.id,
            WorkflowRecord.type == "video_analysis",
        )
    )
    if record is None:
        raise HTTPException(status_code=404, detail=f"video analysis job {job_id} was not found")
    return _video_analysis_to_schema(record)


def _extract_hashtags(text: str) -> list[str]:
    tags: list[str] = []
    for match in HASHTAG_RE.findall(text or ""):
        if match not in tags:
            tags.append(match)
    return tags


def _strip_hashtags_from_description(text: str) -> str:
    description = DESCRIPTION_HASHTAG_RE.sub("", text or "")
    description = re.sub(r"[ \t]{2,}", " ", description)
    description = re.sub(r"[ \t]+\n", "\n", description)
    description = re.sub(r"\n[ \t]+", "\n", description)
    description = re.sub(r"\n{3,}", "\n\n", description)
    return description.strip()


def _save_history(
    session: Session,
    user_id: str,
    result: ExtractLinkResponse,
    payload: ExtractLinkRequest,
) -> str | None:
    history_id = f"eh_{uuid4().hex}"
    try:
        session.add(
            ExtractHistoryRecord(
                id=history_id,
                user_id=user_id,
                account_id=payload.accountId,
                creation_id=payload.creationId,
                task_id=payload.taskId,
                url=result.url,
                resolved_url=result.resolvedUrl,
                platform=result.platform,
                content_type=result.type,
                title=result.title,
                description=result.description,
                hashtags=list(result.hashtags or []),
                images=[image.model_dump() for image in result.images],
                videos=[video.model_dump() for video in result.videos],
                cover=result.cover or "",
                raw=result.raw,
                created_at=datetime.now(UTC),
            )
        )
        session.commit()
        return history_id
    except SQLAlchemyError:
        session.rollback()
        logger.warning("failed to save extract history for user %s", user_id, exc_info=True)
        return None


def _history_schema(record: ExtractHistoryRecord) -> ExtractHistorySchema:
    hashtags = record.hashtags or _extract_hashtags(f"{record.title} {record.description}")
    return ExtractHistorySchema(
        id=record.id,
        historyId=record.id,
        accountId=record.account_id,
        creationId=record.creation_id,
        taskId=record.task_id,
        url=record.url,
        resolvedUrl=record.resolved_url,
        platform=record.platform,
        type=record.content_type,
        title=record.title,
        description=_strip_hashtags_from_description(record.description),
        hashtags=hashtags,
        images=record.images or [],
        videos=record.videos or [],
        cover=record.cover or None,
        raw=record.raw or {},
        persistenceStatus=record.persistence_status,
        persistenceJobId=record.persistence_job_id,
        persistenceError=record.persistence_error,
        persistedAt=record.persisted_at,
        mediaUrlMap=record.media_url_map or {},
        createdAt=record.created_at,
    )


def _video_analysis_to_schema(record: WorkflowRecord) -> VideoAnalysisWorkflowSchema:
    return VideoAnalysisWorkflowSchema(
        id=record.id,
        type=record.type,
        accountId=record.account_id,
        creationId=record.creation_id,
        status=record.status,
        progress=record.progress,
        currentStage=record.current_stage,
        sourceUrl=record.source_url,
        videoUrl=record.video_url,
        coverUrl=record.cover_url,
        platform=record.platform,
        title=record.title,
        description=record.description,
        inputPayload=record.input_payload or {},
        resultPayload=record.result_payload or {},
        error=record.error,
        createdAt=record.created_at,
        updatedAt=record.updated_at,
    )


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _resolve_video_url(payload: CreateVideoAnalysisWorkflowRequest) -> str:
    direct_url = _clean(payload.videoUrl)
    if direct_url:
        return direct_url
    for item in payload.videos or []:
        url = _clean(item.url)
        if url:
            return url
    return ""
