from dataclasses import dataclass
import json
from typing import Annotated,Any

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Request, Response, UploadFile
from sqlalchemy.orm import Session


from app.api.deps import get_ai_service, get_current_user, get_service
from app.models.user import User
from app.services.ai_service import AIService
from app.services.resource_limits import ResourceLimitError, read_upload_file_limited_async
from app.schemas.generation import (
    ComposePromptRequest,
    ComposePromptResponse,
    CreateImageWorkflowRequest,
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
)
from app.services.prompt_tags import prompt_tag_categories as builtin_tag_categories
from app.services.prompt_builder import build_reverse_image_prompt
from app.services.workflow import WorkflowService
from app.services.prompt_tags import build_final_prompt, get_selected_prompt_tags, normalize_selected_tag_ids
from app.services.workflow.scheduler import WorkflowScheduler
from app.services.db_service import DBService
from app.services.workflow.workflows.image_prompt_plan import IMAGE_PROMPT_PLAN_SCHEMA_VERSION
from app.services.topic_repository import find_topic_snapshot

router = APIRouter()


@dataclass(frozen=True)
class UploadedImage:
    filename: str
    content_type: str
    data: bytes


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
    request: Request,
    user: User = Depends(get_current_user),
    ai_service: AIService = Depends(get_ai_service),
    db_service: DBService = Depends(get_service),
) -> ReversePromptResponse:
    try:
        db_service.get_account(user.id, account_id)
    except StopIteration as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    content_type = request.headers.get("content-type", "")
    model: str | None = None
    title = ""
    description = ""
    target_platform = ""
    if content_type.startswith("multipart/form-data"):
        form = await request.form()
        upload = form.get("image")
        if upload is None or not callable(getattr(upload, "read", None)):
            raise HTTPException(status_code=422, detail="image file is required")
        try:
            uploaded = UploadedImage(
                filename=upload.filename or "reference.png",
                content_type=upload.content_type or "application/octet-stream",
                data=await read_upload_file_limited_async(
                    upload,
                    limit=settings.max_upload_image_bytes,
                    label="image upload",
                ),
            )
            file_name, image_content_type, image_data = _validated_upload(uploaded)
        except (ResourceLimitError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        asset_id = f"ga_{uuid4().hex}"
        storage_key = _storage_key(
            f"generation/{account_id}/reverse-prompts/{asset_id}"
            f"{_extension_for(file_name, image_content_type)}"
        )
        try:
            image_url = default_object_storage.put_bytes(storage_key, image_data, image_content_type)
        except Exception as exc:
            raise HTTPException(status_code=502, detail="参考图上传 OSS 失败，请重试") from exc
        model = str(form.get("model") or "").strip() or None
        title = str(form.get("title") or "").strip()
        description = str(form.get("description") or "").strip()
        target_platform = str(form.get("targetPlatform") or "").strip()
    else:
        payload = await request.json()
        image_url = str((payload or {}).get("imageUrl") or "").strip()
        model = str((payload or {}).get("model") or "").strip() or None
        title = str((payload or {}).get("title") or "").strip()
        description = str((payload or {}).get("description") or "").strip()
        target_platform = str((payload or {}).get("targetPlatform") or "").strip()

    if not image_url:
        raise HTTPException(status_code=422, detail="imageUrl is required")
    if image_url.startswith("blob:"):
        raise HTTPException(status_code=422, detail="blob URL 仅在浏览器内有效，请上传图片文件")

    # 调用 AI 反推图片提示词
    system_prompt = build_reverse_image_prompt(
        target_platform=target_platform,
        title=title,
        description=description,
    )
    result_text = await ai_service.image_view(
        image_url=image_url,
        prompt=system_prompt,
        model=model,
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
    user: User = Depends(get_current_user),
    db_service: DBService = Depends(get_service),
    jobs: WorkflowService = Depends(get_generation_jobs),
) -> list[WorkflowSchema]:
    try:
        return jobs.list_jobs(user.id, account_id, page=page, limit=limit)
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


# ======================================================================
# Generation workflow — create & dispatch (new: scheduler.submit)
# ======================================================================

import os
from datetime import UTC, datetime
from urllib.parse import urlparse
from uuid import uuid4

from app.core.config import settings
from app.services.ai_service import default_ai_service
from app.services.object_storage import default_object_storage

ALLOWED_IMAGE_CONTENT_TYPES = {"image/png", "image/jpeg", "image/webp"}


def _load_json_field(value: Any, default: Any) -> Any:
    if value in (None, ""):
        return default
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=422, detail=f"invalid JSON field: {value[:32]}") from exc
    return value


async def _uploaded_images_from_form(form: Any, field_name: str, default_name: str) -> list[UploadedImage]:
    images: list[UploadedImage] = []
    for file in form.getlist(field_name):
        reader = getattr(file, "read", None)
        if not callable(reader):
            continue
        images.append(
            UploadedImage(
                filename=getattr(file, "filename", "") or default_name,
                content_type=getattr(file, "content_type", "") or "application/octet-stream",
                data=await read_upload_file_limited_async(
                    file,
                    limit=settings.max_upload_image_bytes,
                    label="image upload",
                ),
            )
        )
    return images


async def _image_job_request_payload(request: Request) -> tuple[dict[str, Any], list[UploadedImage], list[UploadedImage]]:
    content_type = request.headers.get("content-type", "")
    if content_type.startswith("multipart/form-data"):
        form = await request.form()
        reference_images = await _uploaded_images_from_form(form, "referenceImages", "reference.png")
        material_images = await _uploaded_images_from_form(form, "materialImages", "material.png")
        payload = {
            "prompt": str(form.get("prompt") or ""),
            "selectedTagIds": _load_json_field(form.get("selectedTagIds"), []),
            "negativePrompt": str(form.get("negativePrompt") or ""),
            "count": int(form.get("count") or 1),
            "ratio": str(form.get("ratio") or "3:4"),
            "promptJobId": str(form.get("promptJobId") or "") or None,
            "sourcePromptWorkflowId": str(form.get("sourcePromptWorkflowId") or "") or None,
            "slots": _load_json_field(form.get("slots"), []),
            "variantsPerSlot": int(form.get("variantsPerSlot") or 1),
            "refinement": str(form.get("refinement") or ""),
            "regenerateSlotId": str(form.get("regenerateSlotId") or "") or None,
            "referenceStrength": int(form.get("referenceStrength") or 70),
            "referenceUrls": _parse_reference_urls(form.get("referenceUrls")),
            "materialStrength": str(form.get("materialStrength") or "中"),
        }
        return payload, reference_images, material_images

    payload = await request.json()
    return dict(payload or {}), [], []


@router.post("/accounts/{account_id}/generation/prompt-jobs", response_model=WorkflowSchema)
async def create_prompt_job(
    account_id: str,
    background_tasks: BackgroundTasks,
    images: Annotated[list[UploadFile] | None, File()] = None,
    copyText: Annotated[str, Form()] = "",
    targetPlatform: Annotated[str, Form()] = "",
    topicTitle: Annotated[str | None, Form()] = None,
    referenceUrls: Annotated[str, Form()] = "",
    user: User = Depends(get_current_user),
    db_service: DBService = Depends(get_service),
    scheduler: WorkflowScheduler = Depends(get_generation_scheduler),
) -> WorkflowSchema:
    # ---- validate account ----
    account = db_service.get_account(user.id, account_id)
    remote_refs = _parse_reference_urls(referenceUrls)
    try:
        uploaded_images = [
            UploadedImage(
                filename=img.filename or "upload.png",
                content_type=img.content_type or "application/octet-stream",
                data=await read_upload_file_limited_async(
                    img,
                    limit=settings.max_upload_image_bytes,
                    label="image upload",
                ),
            )
            for img in (images or [])
        ]
    except ResourceLimitError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    ref_count = len(uploaded_images) + len(remote_refs)
    if ref_count == 0:
        raise HTTPException(status_code=422, detail="at least one image is required")
    if ref_count > 8:
        raise HTTPException(status_code=422, detail="at most 8 images are supported")

    try:
        validated = [_validated_upload(img) for img in uploaded_images]
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    now = datetime.now(UTC)
    job_id = f"wf_{uuid4().hex}"
    workflow = WorkflowRecord(
        id=job_id,
        account_id=account.id,
        user_id=user.id,
        type="prompt",
        status="pending",
        target_platform=targetPlatform or account.platform,
        topic_title=topicTitle,
        copy_text=copyText or "",
        prompt="",
        ratio=None,
        requested_count=ref_count,
        error="",
        input_payload={"imageCount": len(uploaded_images), "referenceUrlCount": len(remote_refs), "copyText": copyText or ""},
        result_payload={},
        created_at=now,
        updated_at=now,
    )
    db_service.session.add(workflow)
    uploaded_keys: list[str] = []
    try:
        db_service.session.flush()
        for file_name, content_type, data in validated:
            asset_id = f"ga_{uuid4().hex}"
            key = _storage_key(f"generation/{account_id}/{job_id}/references/{asset_id}{_extension_for(file_name, content_type)}")
            url = default_object_storage.put_bytes(key, data, content_type)
            uploaded_keys.append(key)
            db_service.session.add(
                GenerationAssetRecord(
                    id=asset_id, job_id=job_id, account_id=account_id,
                    asset_type="reference", file_name=file_name, mime_type=content_type,
                    storage_key=key, url=url, status="pending", analysis="", error="",
                    meta={}, created_at=now,
                )
            )
        for ref_url in remote_refs:
            asset_id = f"ga_{uuid4().hex}"
            file_name = _file_name_from_url(ref_url, default=f"{asset_id}.png")
            db_service.session.add(
                GenerationAssetRecord(
                    id=asset_id, job_id=job_id, account_id=account_id,
                    asset_type="reference", file_name=file_name,
                    mime_type=_content_type_from_extension(file_name),
                    storage_key=ref_url, url=ref_url, status="pending",
                    analysis="", error="", meta={"source": "reference_url"}, created_at=now,
                )
            )
        db_service.session.commit()
    except Exception:
        db_service.session.rollback()
        _cleanup_storage_objects(default_object_storage, uploaded_keys)
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
    request: Request,
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
    jobs: WorkflowService = Depends(get_generation_jobs),
    scheduler: WorkflowScheduler = Depends(get_generation_scheduler),
) -> WorkflowSchema:
    try:
        payload, reference_images, material_images = await _image_job_request_payload(request)
    except ResourceLimitError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    try:
        schema = jobs.create_image_job(
            user_id=user.id,
            account_id=account_id,
            prompt=str(payload.get("prompt") or ""),
            count=int(payload.get("count") or 1),
            ratio=str(payload.get("ratio") or "3:4"),
            prompt_job_id=str(payload.get("sourcePromptWorkflowId") or payload.get("promptJobId") or "") or None,
            selected_tag_ids=list(payload.get("selectedTagIds") or []),
            negative_prompt=str(payload.get("negativePrompt") or ""),
            slots=list(payload.get("slots") or []),
            variants_per_slot=int(payload.get("variantsPerSlot") or 1),
            refinement=str(payload.get("refinement") or ""),
            regenerate_slot_id=str(payload.get("regenerateSlotId") or "") or None,
            reference_images=reference_images,
            reference_urls=payload.get("referenceUrls"),
            material_images=material_images,
            reference_strength=int(payload.get("referenceStrength") or 70),
            material_strength=str(payload.get("materialStrength") or "中"),
        )
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


def _validated_upload(image: Any) -> tuple[str, str, bytes]:
    file_name = str(getattr(image, "filename", None) or getattr(image, "file_name", None) or "upload.png")
    content_type = str(getattr(image, "content_type", None) or "application/octet-stream")
    if content_type not in ALLOWED_IMAGE_CONTENT_TYPES:
        raise ValueError(f"unsupported image content type: {content_type}")
    data = getattr(image, "data", None)
    if isinstance(data, bytes):
        return file_name, content_type, data
    reader = getattr(image, "read", None)
    if callable(reader):
        val = reader()
        if isinstance(val, bytes):
            return file_name, content_type, val
    raise ValueError("image bytes are required")


def _file_name_from_url(url: str, *, default: str) -> str:
    parsed = urlparse(url)
    return os.path.basename(parsed.path) or default


def _content_type_from_extension(file_name: str) -> str:
    suffix = os.path.splitext(file_name)[1].lower()
    return {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}.get(suffix, "image/png")


def _extension_for(file_name: str, content_type: str) -> str:
    suffix = os.path.splitext(file_name)[1]
    if suffix:
        return suffix
    return {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp"}.get(content_type, ".bin")


def _storage_key(key: str) -> str:
    upload_dir = settings.object_storage_upload_dir
    if not upload_dir:
        return key
    return f"{upload_dir}/{key.lstrip('/')}"


def _cleanup_storage_objects(storage: Any, keys: list[str]) -> None:
    for key in keys:
        for method_name in ("delete_object", "delete_bytes", "delete"):
            dm = getattr(storage, method_name, None)
            if not callable(dm):
                continue
            try:
                dm(key)
            except Exception:
                pass
            break


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
