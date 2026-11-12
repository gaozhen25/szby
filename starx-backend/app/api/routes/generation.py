import json
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session


from app.api.deps import get_ai_service, get_current_user, get_service
from app.models.user import User
from app.services.ai_service import AIService
from app.api.routes.uploads import get_direct_upload_service
from app.schemas.generation import (
    ComposePromptRequest,
    ComposePromptResponse,
    CreateImageWorkflowRequest,
    CreatePromptWorkflowRequest,
    CreateTopicPromptWorkflowRequest,
    CreateScriptRewriteWorkflowRequest,
    CreateVideoScriptWorkflowRequest,
    WorkflowSchema,
    PromptTagCategoryCreateRequest,
    PromptTagCategorySchema,
    PromptTagCategoryUpdateRequest,
    PromptTagCreateRequest,
    PromptTagSchema,
    PromptTagUpdateRequest,
    PromptTemplateCreateRequest,
    PromptTemplateSchema,
    PromptTemplateUpdateRequest,
    ReversePromptResponse,
    ReversePromptRequest,
    PersonReplacementRequest,
)
from app.schemas.uploads import UploadedObjectRef
from app.services.prompt_tags import prompt_tag_categories as builtin_tag_categories
from app.services.prompt_builder import build_reverse_image_prompt
from app.services.workflow import WorkflowService
from app.services.prompt_tags import build_final_prompt, get_selected_prompt_tags, normalize_selected_tag_ids
from app.services.workflow.scheduler import WorkflowScheduler
from app.services.db_service import DBService
from app.services.workflow.workflows.image_prompt_plan import IMAGE_PROMPT_PLAN_SCHEMA_VERSION
from app.services.workflow.workflows.generated_image_persistence import download_generated_image
from app.services.topic_repository import find_topic_snapshot
from app.services.uploads import DirectUploadError, DirectUploadService

router = APIRouter()

PERSON_REPLACEMENT_PROMPT = """执行单人物替换编辑。
图片 1 是场景底图：保留其背景、机位、透视关系、画面构图、光线、色调和尺寸。
图片 2 是目标人物参考图：将图片 1 中的主要人物整体替换成图片 2 中的人物。
结果中的人物必须明确呈现图片 2 人物的身份与外观，包括性别、脸型、五官、发型、体型和整体气质；不要保留图片 1 原人物的身份特征。
让图片 2 的人物自然出现在图片 1 原人物的位置，匹配原场景中的姿势、视角、尺度、遮挡和光照；允许为适配场景重新绘制人物。
不要复制图片 2 的背景；不要改变图片 1 中人物区域以外的场景；不要添加多余人物、文字、水印或装饰。"""
PERSON_REPLACEMENT_RATIOS = {"1:1", "3:4", "4:3", "9:16", "16:9"}


def _person_replacement_ratio(value: str) -> str:
    ratio = str(value or "").strip()
    if ratio in PERSON_REPLACEMENT_RATIOS:
        return ratio
    parts = ratio.split(":")
    if len(parts) != 2 or not all(part.isdigit() for part in parts):
        raise ValueError("unsupported person replacement ratio")
    width, height = (int(part) for part in parts)
    if width <= 0 or height <= 0 or width > 100_000 or height > 100_000:
        raise ValueError("unsupported person replacement ratio")
    aspect = width / height
    if not 1 / 3 <= aspect <= 3:
        raise ValueError("person replacement ratio must be between 1:3 and 3:1")
    return f"{width}:{height}"


def get_generation_jobs(db: Session = Depends(get_service)) -> WorkflowService:
    return WorkflowService(db.session)

def get_generation_scheduler() -> WorkflowScheduler:
    return WorkflowScheduler.get_instance()


# ======================================================================
# Prompt tags & templates (unchanged — these are not workflow execution)
# ======================================================================

@router.get("/accounts/{account_id}/generation/prompt-tags", response_model=list[PromptTagCategorySchema])
def list_prompt_tags(
    account_id: str,
    user: User = Depends(get_current_user),
    jobs: WorkflowService = Depends(get_generation_jobs),
) -> list[PromptTagCategorySchema]:
    try:
        return jobs.list_prompt_tag_categories(user.id, account_id)
    except StopIteration as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/accounts/{account_id}/generation/prompts/compose", response_model=ComposePromptResponse)
def compose_prompt(
    account_id: str,
    payload: ComposePromptRequest,
    user: User = Depends(get_current_user),
    jobs: WorkflowService = Depends(get_generation_jobs),
) -> ComposePromptResponse:
    try:
        categories = jobs._prompt_tag_categories(user.id, account_id)
    except StopIteration as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    selected_tag_ids = normalize_selected_tag_ids(payload.selectedTagIds, categories)
    return ComposePromptResponse(
        prompt=payload.prompt.strip(),
        finalPrompt=build_final_prompt(payload.prompt, selected_tag_ids, categories),
        selectedTagIds=selected_tag_ids,
        selectedTags=get_selected_prompt_tags(selected_tag_ids, categories),
        negativePrompt=payload.negativePrompt.strip(),
    )


@router.post("/accounts/{account_id}/generation/reverse-prompt", response_model=ReversePromptResponse)
async def reverse_prompt(
    account_id: str,
    payload: ReversePromptRequest,
    user: User = Depends(get_current_user),
    ai_service: AIService = Depends(get_ai_service),
    db_service: DBService = Depends(get_service),
    uploads: DirectUploadService = Depends(get_direct_upload_service),
) -> ReversePromptResponse:
    try:
        db_service.get_account(user.id, account_id)
    except StopIteration as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    image_url = payload.imageUrl.strip()
    if not image_url:
        raise HTTPException(status_code=422, detail="imageUrl is required")
    if image_url.startswith("blob:"):
        raise HTTPException(status_code=422, detail="blob URL 仅在浏览器内有效，请上传图片文件")
    try:
        uploads.verify_ref(
            user_id=user.id,
            ref=UploadedObjectRef(uploadId=payload.uploadId, url=image_url),
            purposes={"generation_reference"},
            account_id=account_id,
            allow_external=True,
        )
    except DirectUploadError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    # 调用 AI 反推图片提示词
    system_prompt = build_reverse_image_prompt(
        target_platform=payload.targetPlatform,
        title=payload.title,
        description=payload.description,
    )
    result_text = await ai_service.image_view(
        image_url=image_url,
        prompt=system_prompt,
        model=payload.model,
        temperature=0.2,
    )
    if not result_text:
        raise HTTPException(status_code=500, detail="AI 反推失败，请重试")

    import json
    import re
    cleaned = re.sub(r"```(?:json)?\s*([\s\S]*?)\s*```", r"\1", result_text).strip()
    parsed = json.loads(cleaned)

    return ReversePromptResponse(
        positive=str(parsed.get("positive", "")).strip(),
        negative=str(parsed.get("negative", "")).strip(),
        publishCopy=str(parsed.get("publishCopy", "")).strip(),
        styleTags=list(parsed.get("styleTags") or []),
        keyParams={},
        imageUrl=image_url,
    )


@router.post("/accounts/{account_id}/generation/prompt-tag-categories", response_model=PromptTagCategorySchema)
def create_prompt_tag_category(
    account_id: str,
    payload: PromptTagCategoryCreateRequest,
    user: User = Depends(get_current_user),
    jobs: WorkflowService = Depends(get_generation_jobs),
) -> PromptTagCategorySchema:
    try:
        return jobs.create_prompt_tag_category(user.id, account_id, payload)
    except StopIteration as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.patch("/accounts/{account_id}/generation/prompt-tag-categories/{category_id}", response_model=PromptTagCategorySchema)
def update_prompt_tag_category(
    account_id: str,
    category_id: str,
    payload: PromptTagCategoryUpdateRequest,
    user: User = Depends(get_current_user),
    jobs: WorkflowService = Depends(get_generation_jobs),
) -> PromptTagCategorySchema:
    try:
        return jobs.update_prompt_tag_category(user.id, account_id, category_id, payload)
    except StopIteration as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/accounts/{account_id}/generation/prompt-tag-categories/{category_id}", status_code=204)
def delete_prompt_tag_category(
    account_id: str,
    category_id: str,
    user: User = Depends(get_current_user),
    jobs: WorkflowService = Depends(get_generation_jobs),
) -> Response:
    try:
        jobs.delete_prompt_tag_category(user.id, account_id, category_id)
    except StopIteration as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return Response(status_code=204)


@router.post(
    "/accounts/{account_id}/generation/prompt-tag-categories/{category_id}/tags",
    response_model=PromptTagSchema,
)
def create_prompt_tag(
    account_id: str,
    category_id: str,
    payload: PromptTagCreateRequest,
    user: User = Depends(get_current_user),
    jobs: WorkflowService = Depends(get_generation_jobs),
) -> PromptTagSchema:
    try:
        return jobs.create_prompt_tag(user.id, account_id, category_id, payload)
    except StopIteration as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.patch("/accounts/{account_id}/generation/prompt-tags/{tag_id}", response_model=PromptTagSchema)
def update_prompt_tag(
    account_id: str,
    tag_id: str,
    payload: PromptTagUpdateRequest,
    user: User = Depends(get_current_user),
    jobs: WorkflowService = Depends(get_generation_jobs),
) -> PromptTagSchema:
    try:
        return jobs.update_prompt_tag(user.id, account_id, tag_id, payload)
    except StopIteration as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/accounts/{account_id}/generation/prompt-tags/{tag_id}", status_code=204)
def delete_prompt_tag(
    account_id: str,
    tag_id: str,
    user: User = Depends(get_current_user),
    jobs: WorkflowService = Depends(get_generation_jobs),
) -> Response:
    try:
        jobs.delete_prompt_tag(user.id, account_id, tag_id)
    except StopIteration as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return Response(status_code=204)


@router.get("/accounts/{account_id}/generation/prompt-templates", response_model=list[PromptTemplateSchema])
def list_prompt_templates(
    account_id: str,
    user: User = Depends(get_current_user),
    jobs: WorkflowService = Depends(get_generation_jobs),
) -> list[PromptTemplateSchema]:
    try:
        return jobs.list_prompt_templates(user.id, account_id)
    except StopIteration as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/accounts/{account_id}/generation/prompt-templates", response_model=PromptTemplateSchema)
def create_prompt_template(
    account_id: str,
    payload: PromptTemplateCreateRequest,
    user: User = Depends(get_current_user),
    jobs: WorkflowService = Depends(get_generation_jobs),
) -> PromptTemplateSchema:
    try:
        return jobs.create_prompt_template(user.id, account_id, payload)
    except StopIteration as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.patch("/accounts/{account_id}/generation/prompt-templates/{template_id}", response_model=PromptTemplateSchema)
def update_prompt_template(
    account_id: str,
    template_id: str,
    payload: PromptTemplateUpdateRequest,
    user: User = Depends(get_current_user),
    jobs: WorkflowService = Depends(get_generation_jobs),
) -> PromptTemplateSchema:
    try:
        return jobs.update_prompt_template(user.id, account_id, template_id, payload)
    except StopIteration as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/accounts/{account_id}/generation/prompt-templates/{template_id}", status_code=204)
def delete_prompt_template(
    account_id: str,
    template_id: str,
    user: User = Depends(get_current_user),
    jobs: WorkflowService = Depends(get_generation_jobs),
) -> Response:
    try:
        jobs.delete_prompt_template(user.id, account_id, template_id)
    except StopIteration as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return Response(status_code=204)


# ======================================================================
# Generation workflow — listing & detail (new: reads DB directly)
# ======================================================================

from sqlalchemy import select
from app.db.models import WorkflowRecord, GenerationAssetRecord, WorkflowStepRecord
from app.schemas.generation import GenerationAssetSchema, WorkflowStepSchema
from app.services.workflow.workflows.video_script_contract import (
    VIDEO_SCRIPT_MANUAL_VERSION,
    VIDEO_SCRIPT_SCHEMA_VERSION,
)


def _generation_to_schema(record: WorkflowRecord, session: Session) -> WorkflowSchema:
    assets = sorted(getattr(record, "assets", []) or [], key=lambda a: getattr(a, "created_at", 0))
    steps = sorted(getattr(record, "steps", []) or [], key=lambda s: (s.sort_order, s.created_at))
    return WorkflowSchema(
        id=record.id,
        type=record.type,
        status=record.status,
        progress=record.progress,
        currentStage=record.current_stage,
        targetPlatform=record.target_platform,
        topicTitle=record.topic_title,
        copyText=record.copy_text,
        prompt=record.prompt,
        ratio=record.ratio,
        requestedCount=record.requested_count,
        error=record.error,
        inputPayload=record.input_payload or {},
        resultPayload=record.result_payload or {},
        assets=[
            GenerationAssetSchema(
                id=a.id, assetType=a.asset_type, fileName=a.file_name,
                mimeType=a.mime_type, url=a.url, status=a.status,
                analysis=a.analysis, error=a.error, meta=a.meta or {},
            ) for a in assets
        ],
        steps=[
            WorkflowStepSchema(
                id=s.id, type=s.type, status=s.status, progress=s.progress,
                sortOrder=s.sort_order, groupKey=s.group_key, assetId=s.asset_id,
                inputPayload=s.input_payload or {}, resultPayload=s.result_payload or {},
                error=s.error, createdAt=s.created_at, updatedAt=s.updated_at,
            ) for s in steps
        ],
        createdAt=record.created_at,
        updatedAt=record.updated_at,
    )


@router.get("/accounts/{account_id}/generation/jobs", response_model=list[WorkflowSchema])
def list_generation_jobs(
    account_id: str,
    page: int = 1,
    limit: int = 20,
    job_type: str | None = Query(default=None, alias="type"),
    user: User = Depends(get_current_user),
    db_service: DBService = Depends(get_service),
    jobs: WorkflowService = Depends(get_generation_jobs),
) -> list[WorkflowSchema]:
    try:
        return jobs.list_jobs(
            user.id,
            account_id,
            page=page,
            limit=limit,
            job_type=job_type,
        )
    except StopIteration as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/accounts/{account_id}/generation/jobs/{job_id}", response_model=WorkflowSchema)
def get_generation_job(
    account_id: str,
    job_id: str,
    user: User = Depends(get_current_user),
    jobs: WorkflowService = Depends(get_generation_jobs),
) -> WorkflowSchema:
    try:
        return jobs.get_job(user.id, account_id, job_id)
    except StopIteration as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/accounts/{account_id}/generation/jobs/{job_id}/result-image")
async def download_generation_result_image(
    account_id: str,
    job_id: str,
    image_index: int = Query(default=0, alias="imageIndex", ge=0),
    user: User = Depends(get_current_user),
    jobs: WorkflowService = Depends(get_generation_jobs),
) -> Response:
    try:
        job = jobs.get_job(user.id, account_id, job_id)
    except StopIteration as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    images = list((job.resultPayload or {}).get("images") or [])
    selected_image = images[image_index] if image_index < len(images) else {}
    result_url = str(selected_image.get("url") or "").strip()
    if not result_url:
        raise HTTPException(status_code=409, detail="人物替换结果尚未生成")

    try:
        data, content_type = await download_generated_image(result_url)
    except Exception as exc:
        raise HTTPException(status_code=502, detail="结果图片下载失败，请稍后重试") from exc

    extension = {
        "image/jpeg": "jpg",
        "image/webp": "webp",
    }.get(content_type, "png")
    return Response(
        content=data,
        media_type=content_type,
        headers={
            "Content-Disposition": (
                f'attachment; filename="starx-person-replacement-{job_id}-{image_index + 1}.{extension}"'
            ),
            "Cache-Control": "private, no-store",
        },
    )


# ======================================================================
# Generation workflow — create & dispatch (new: scheduler.submit)
# ======================================================================

import os
from datetime import UTC, datetime
from urllib.parse import urlparse
from uuid import uuid4

@router.post("/accounts/{account_id}/generation/prompt-jobs", response_model=WorkflowSchema)
def create_prompt_job(
    account_id: str,
    payload: CreatePromptWorkflowRequest,
    user: User = Depends(get_current_user),
    db_service: DBService = Depends(get_service),
    scheduler: WorkflowScheduler = Depends(get_generation_scheduler),
    uploads: DirectUploadService = Depends(get_direct_upload_service),
) -> WorkflowSchema:
    account = db_service.get_account(user.id, account_id)
    try:
        remote_refs = _parse_reference_urls(payload.referenceUrls)
        upload_records = uploads.verify_urls(
            user_id=user.id,
            urls=remote_refs,
            purposes={"generation_reference"},
            account_id=account_id,
            allow_external=True,
        )
    except (ValueError, DirectUploadError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    now = datetime.now(UTC)
    job_id = f"wf_{uuid4().hex}"
    workflow = WorkflowRecord(
        id=job_id,
        account_id=account.id,
        user_id=user.id,
        type="prompt",
        status="pending",
        target_platform=payload.targetPlatform or account.platform,
        topic_title=payload.topicTitle,
        copy_text=payload.copyText or "",
        prompt="",
        ratio=None,
        requested_count=len(remote_refs),
        error="",
        input_payload={"imageCount": 0, "referenceUrlCount": len(remote_refs), "copyText": payload.copyText or ""},
        result_payload={},
        created_at=now,
        updated_at=now,
    )
    db_service.session.add(workflow)
    try:
        db_service.session.flush()
        for ref_url in remote_refs:
            asset_id = f"ga_{uuid4().hex}"
            file_name = _file_name_from_url(ref_url, default=f"{asset_id}.png")
            db_service.session.add(
                GenerationAssetRecord(
                    id=asset_id, job_id=job_id, account_id=account_id,
                    asset_type="reference", file_name=file_name,
                    mime_type=_content_type_from_extension(file_name),
                    storage_key=ref_url, url=ref_url, status="pending",
                    analysis="", error="", meta={"source": "direct_or_reference_url"}, created_at=now,
                )
            )
        uploads.mark_consumed(upload_records, resource_type="generation_workflow", resource_id=job_id)
        db_service.session.commit()
    except Exception:
        db_service.session.rollback()
        raise

    db_service.session.refresh(workflow)
    schema = _generation_to_schema(workflow, db_service.session)

    scheduler.submit("prompt", job_id)
    return schema


@router.post("/accounts/{account_id}/generation/topic-prompt-jobs", response_model=WorkflowSchema)
def create_topic_prompt_job(
    account_id: str,
    payload: CreateTopicPromptWorkflowRequest,
    background_tasks: BackgroundTasks,  # noqa: ARG001
    user: User = Depends(get_current_user),
    db_service: DBService = Depends(get_service),
    scheduler: WorkflowScheduler = Depends(get_generation_scheduler),
) -> WorkflowSchema:
    account = db_service.get_account(user.id, account_id)
    topic_id = str(payload.topicId or "").strip()
    if topic_id:
        return _create_topic_image_prompt_plan(
            account=account,
            payload=payload,
            user=user,
            db_service=db_service,
            scheduler=scheduler,
        )

    topic_title = str(payload.topicTitle or "").strip()
    copy_text = str(payload.copyText or "").strip()
    if not topic_title and not copy_text:
        raise HTTPException(status_code=422, detail="topicTitle or copyText is required")

    now = datetime.now(UTC)
    job_id = f"wf_{uuid4().hex}"
    workflow = WorkflowRecord(
        id=job_id,
        account_id=account.id,
        user_id=user.id,
        type="prompt",
        status="pending",
        target_platform=payload.targetPlatform or account.platform,
        topic_title=topic_title or None,
        copy_text=copy_text,
        prompt="",
        ratio=None,
        requested_count=0,
        error="",
        input_payload={
            "mode": "topic_text",
            "topicTitle": topic_title,
            "copyText": copy_text,
        },
        result_payload={},
        created_at=now,
        updated_at=now,
    )
    db_service.session.add(workflow)
    db_service.session.commit()
    db_service.session.refresh(workflow)

    schema = _generation_to_schema(workflow, db_service.session)
    scheduler.submit("prompt", job_id)
    return schema


def _create_topic_image_prompt_plan(
    *,
    account: Any,
    payload: CreateTopicPromptWorkflowRequest,
    user: User,
    db_service: DBService,
    scheduler: WorkflowScheduler,
) -> WorkflowSchema:
    topic_id = str(payload.topicId).strip()
    topic = find_topic_snapshot(
        db_service.session,
        account_id=account.id,
        topic_id=topic_id,
        content_type="image",
    )
    if topic is None:
        raise HTTPException(status_code=422, detail="image topic is not available")
    if payload.collectionMode == "series" and payload.imageCount == 1:
        raise HTTPException(status_code=422, detail="series mode requires at least 2 images")

    configured_platforms = account.platforms or [account.platform]
    if payload.targetPlatform not in configured_platforms:
        raise HTTPException(status_code=422, detail="target platform is not configured on the account")

    input_payload = {
        "mode": "topic_image_plan",
        "topicId": topic_id,
        "targetPlatform": payload.targetPlatform,
        "imageCount": payload.imageCount,
        "collectionMode": payload.collectionMode,
        "ratio": payload.ratio,
        "creativityLevel": payload.creativityLevel,
        "visualStyle": payload.visualStyle,
        "customRequirements": payload.customRequirements,
        "schemaVersion": IMAGE_PROMPT_PLAN_SCHEMA_VERSION,
    }
    if topic.reference_note:
        input_payload["referenceNote"] = dict(topic.reference_note)
    if payload.referenceUrls:
        input_payload["referenceUrlCount"] = len(payload.referenceUrls)
    now = datetime.now(UTC)
    workflow = WorkflowRecord(
        id=f"wf_{uuid4().hex}",
        account_id=account.id,
        user_id=user.id,
        type="prompt",
        status="pending",
        target_platform=payload.targetPlatform,
        topic_title=topic.title,
        copy_text="",
        prompt="",
        ratio=payload.ratio,
        requested_count=payload.imageCount,
        error="",
        input_payload=input_payload,
        result_payload={},
        created_at=now,
        updated_at=now,
    )
    db_service.session.add(workflow)
    for reference_url in payload.referenceUrls:
        clean_url = str(reference_url or "").strip()
        if not clean_url:
            continue
        asset_id = f"ga_{uuid4().hex}"
        file_name = _file_name_from_url(clean_url, default=f"{asset_id}.png")
        db_service.session.add(
            GenerationAssetRecord(
                id=asset_id,
                job_id=workflow.id,
                account_id=account.id,
                asset_type="reference",
                file_name=file_name,
                mime_type=_content_type_from_extension(file_name),
                storage_key=clean_url,
                url=clean_url,
                status="pending",
                analysis="",
                error="",
                meta={"source": "topic_reference_note", "referenceNote": dict(topic.reference_note or {})},
                created_at=now,
            )
        )
    db_service.session.commit()
    db_service.session.refresh(workflow)

    schema = _generation_to_schema(workflow, db_service.session)
    scheduler.submit("prompt", workflow.id)
    return schema


@router.post("/accounts/{account_id}/generation/image-jobs", response_model=WorkflowSchema)
async def create_image_job(
    account_id: str,
    payload: CreateImageWorkflowRequest,
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
    jobs: WorkflowService = Depends(get_generation_jobs),
    scheduler: WorkflowScheduler = Depends(get_generation_scheduler),
    uploads: DirectUploadService = Depends(get_direct_upload_service),
) -> WorkflowSchema:
    try:
        reference_records = uploads.verify_urls(
            user_id=user.id,
            urls=payload.referenceUrls,
            purposes={"generation_reference"},
            account_id=account_id,
            allow_external=True,
        )
        material_records = uploads.verify_urls(
            user_id=user.id,
            urls=payload.materialUrls,
            purposes={"generation_material"},
            account_id=account_id,
            allow_external=True,
        )
        schema = jobs.create_image_job(
            user_id=user.id,
            account_id=account_id,
            prompt=payload.prompt,
            count=payload.count,
            ratio=payload.ratio,
            prompt_job_id=payload.sourcePromptWorkflowId or payload.promptJobId,
            selected_tag_ids=payload.selectedTagIds,
            negative_prompt=payload.negativePrompt,
            slots=[slot.model_dump() for slot in payload.slots],
            variants_per_slot=payload.variantsPerSlot,
            refinement=payload.refinement,
            regenerate_slot_id=payload.regenerateSlotId,
            reference_urls=payload.referenceUrls,
            material_urls=payload.materialUrls,
            reference_strength=payload.referenceStrength,
            material_strength=payload.materialStrength,
        )
        uploads.mark_consumed(
            [*reference_records, *material_records],
            resource_type="generation_workflow",
            resource_id=schema.id,
        )
        jobs.session.commit()
    except StopIteration as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    scheduler.submit("image", schema.id)
    return schema


@router.post("/accounts/{account_id}/generation/person-replacement-jobs", response_model=WorkflowSchema)
def create_person_replacement_job(
    account_id: str,
    payload: PersonReplacementRequest,
    user: User = Depends(get_current_user),
    jobs: WorkflowService = Depends(get_generation_jobs),
    scheduler: WorkflowScheduler = Depends(get_generation_scheduler),
    uploads: DirectUploadService = Depends(get_direct_upload_service),
) -> WorkflowSchema:
    if not payload.consentConfirmed:
        raise HTTPException(status_code=422, detail="请确认已获得目标人物授权")
    try:
        ratio = _person_replacement_ratio(payload.ratio)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    try:
        target_upload = uploads.verify_ref(
            user_id=user.id,
            ref=payload.targetImage,
            purposes={"person_replacement_target"},
            account_id=account_id,
        )
        person_upload = uploads.verify_ref(
            user_id=user.id,
            ref=payload.personImage,
            purposes={"person_replacement_person"},
            account_id=account_id,
        )
        assert target_upload is not None and person_upload is not None
        schema = jobs.create_image_job(
            user_id=user.id,
            account_id=account_id,
            prompt=PERSON_REPLACEMENT_PROMPT,
            count=payload.count,
            ratio=ratio,
            prompt_job_id=None,
            reference_urls=[target_upload.object_url],
            material_urls=[person_upload.object_url],
            reference_strength=100,
            material_strength="目标人物",
            operation="person_replacement",
            consent_confirmed=True,
        )
        uploads.mark_consumed(
            [target_upload, person_upload],
            resource_type="generation_workflow",
            resource_id=schema.id,
        )
        jobs.session.commit()
    except DirectUploadError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except StopIteration as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    scheduler.submit("image", schema.id)
    return schema


@router.post("/accounts/{account_id}/generation/script-rewrite-jobs", response_model=WorkflowSchema)
def create_script_rewrite_job(
    account_id: str,
    payload: CreateScriptRewriteWorkflowRequest,
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
    db_service: DBService = Depends(get_service),
    scheduler: WorkflowScheduler = Depends(get_generation_scheduler),
) -> WorkflowSchema:
    account = db_service.get_account(user.id, account_id)
    script_lines = [str(line).strip() for line in payload.originalScript if str(line).strip()]
    if not script_lines:
        raise HTTPException(status_code=422, detail="original script is required")

    now = datetime.now(UTC)
    job_id = f"wf_{uuid4().hex}"
    workflow = WorkflowRecord(
        id=job_id,
        account_id=account.id,
        user_id=user.id,
        type="script_rewrite",
        status="pending",
        target_platform=payload.targetPlatform or account.platform,
        topic_title=payload.topicTitle,
        copy_text=str(payload.copyText or "").strip(),
        prompt="",
        ratio=None,
        requested_count=len(script_lines),
        error="",
        input_payload={"originalScript": script_lines, "copyText": str(payload.copyText or "").strip()},
        result_payload={},
        created_at=now, updated_at=now,
    )
    db_service.session.add(workflow)
    db_service.session.commit()
    db_service.session.refresh(workflow)

    schema = _generation_to_schema(workflow, db_service.session)
    scheduler.submit("script_rewrite", job_id)
    return schema


@router.post("/accounts/{account_id}/generation/video-script-jobs", response_model=WorkflowSchema)
def create_video_script_job(
    account_id: str,
    payload: CreateVideoScriptWorkflowRequest,
    background_tasks: BackgroundTasks,  # noqa: ARG001
    user: User = Depends(get_current_user),
    db_service: DBService = Depends(get_service),
    scheduler: WorkflowScheduler = Depends(get_generation_scheduler),
) -> WorkflowSchema:
    try:
        account = db_service.get_account(user.id, account_id)
    except StopIteration as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    topic = find_topic_snapshot(
        db_service.session,
        account_id=account.id,
        topic_id=payload.topicId,
        content_type="video",
    )
    if topic is None:
        raise HTTPException(status_code=422, detail="video topic is not available")

    configured_platforms = account.platforms or [account.platform]
    if payload.targetPlatform not in configured_platforms:
        raise HTTPException(status_code=422, detail="target platform is not configured on the account")

    input_payload = {
        **payload.model_dump(),
        "schemaVersion": VIDEO_SCRIPT_SCHEMA_VERSION,
        "manualVersion": VIDEO_SCRIPT_MANUAL_VERSION,
    }
    now = datetime.now(UTC)
    job_id = f"wf_{uuid4().hex}"
    workflow = WorkflowRecord(
        id=job_id,
        account_id=account.id,
        user_id=user.id,
        type="video_script",
        status="pending",
        target_platform=payload.targetPlatform,
        topic_title=topic.title,
        copy_text="",
        prompt="",
        ratio=None,
        requested_count=1,
        error="",
        input_payload=input_payload,
        result_payload={},
        created_at=now,
        updated_at=now,
    )
    db_service.session.add(workflow)
    db_service.session.commit()
    db_service.session.refresh(workflow)

    schema = _generation_to_schema(workflow, db_service.session)
    scheduler.submit("video_script", job_id)
    return schema


# ======================================================================
# helpers
# ======================================================================

def _parse_reference_urls(value: str | list[str] | None) -> list[str]:
    if value is None:
        return []
    raw = value if isinstance(value, list) else str(value).splitlines()
    urls: list[str] = []
    seen = set()
    for item in raw:
        for candidate in str(item).split(","):
            url = candidate.strip()
            if not url or url in seen:
                continue
            if not url.startswith(("http://", "https://")):
                raise ValueError(f"unsupported reference url: {url}")
            seen.add(url)
            urls.append(url)
    return urls


def _file_name_from_url(url: str, *, default: str) -> str:
    parsed = urlparse(url)
    return os.path.basename(parsed.path) or default


def _content_type_from_extension(file_name: str) -> str:
    suffix = os.path.splitext(file_name)[1].lower()
    return {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}.get(suffix, "image/png")


def _normalize_image_slots(slots: list[Any] | None, count: int) -> list[dict[str, str]]:
    normalized: list[dict[str, str]] = []
    for idx, slot in enumerate(slots or []):
        d = slot.model_dump() if hasattr(slot, "model_dump") else (dict(slot) if isinstance(slot, dict) else {})
        slot_id = str(d.get("slotId") or "").strip() or f"slot_{idx + 1}"
        normalized.append({
            "slotId": slot_id,
            "sourceType": str(d.get("sourceType") or "").strip() or "manual",
            "sourceUrl": str(d.get("sourceUrl") or "").strip(),
            "sourcePrompt": str(d.get("sourcePrompt") or "").strip(),
        })
    if normalized:
        return normalized
    return [
        {"slotId": f"slot_{i + 1}", "sourceType": "manual", "sourceUrl": "", "sourcePrompt": ""}
        for i in range(count)
    ]


def _get_prompt_tag_categories(user_id: str, account_id: str, session: Session) -> list[dict[str, Any]]:
    from app.db.models import GenerationPromptTagCategoryRecord
    from app.services.prompt_tags import prompt_tag_categories as builtin
    custom_records = (
        session.query(GenerationPromptTagCategoryRecord)
        .filter(
            GenerationPromptTagCategoryRecord.account_id == account_id,
            GenerationPromptTagCategoryRecord.user_id == user_id,
        )
        .order_by(GenerationPromptTagCategoryRecord.sort_order, GenerationPromptTagCategoryRecord.created_at)
        .all()
    )
    result: list[dict[str, Any]] = [dict(cat) for cat in builtin]
    for rec in custom_records:
        result.append({
            "id": rec.id, "label": rec.label, "source": "custom", "sortOrder": rec.sort_order,
            "tags": [
                {"id": tag.id, "categoryId": rec.id, "label": tag.label, "prompt": tag.prompt, "source": "custom", "sortOrder": tag.sort_order}
                for tag in sorted(rec.tags, key=lambda item: (item.sort_order, item.created_at))
            ],
        })
    return result
