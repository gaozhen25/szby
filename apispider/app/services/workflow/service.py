"""API-facing facade for workflow records and workflow dispatch."""

from __future__ import annotations

import asyncio
import os
import threading
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any, Callable, Iterator
from urllib.parse import urlparse
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.db.models import (
    AccountRecord,
    GenerationAssetRecord,
    GenerationPromptTagCategoryRecord,
    GenerationPromptTagRecord,
    GenerationPromptTemplateRecord,
    WorkflowRecord,
)
from app.schemas.extract import CreateVideoAnalysisWorkflowRequest, VideoAnalysisWorkflowSchema
from app.schemas.generation import (
    GenerationAssetSchema,
    PromptTagCategoryCreateRequest,
    PromptTagCategorySchema,
    PromptTagCategoryUpdateRequest,
    PromptTagCreateRequest,
    PromptTagSchema,
    PromptTagUpdateRequest,
    PromptTemplateCreateRequest,
    PromptTemplateSchema,
    PromptTemplateUpdateRequest,
    WorkflowSchema,
    WorkflowStepSchema,
)
from app.services.ai_service import default_ai_service
from app.services.account_report.workflow_types import (
    ACCOUNT_REPORT_WORKFLOW_TYPE,
    ACCOUNT_REPORT_WORKFLOW_TYPES,
    section_workflow_type,
)
from app.core.config import settings
from app.services.object_storage import default_object_storage
from app.services.prompt_tags import build_final_prompt, normalize_selected_tag_ids, prompt_tag_categories
from app.services.resource_limits import read_upload_file_limited
from app.services.workflow.scheduler import WorkflowScheduler
from app.services.workflow.workflow_store import WorkflowStore
from app.services.workflow.workflows.base import WorkflowRegister
from app.services.workflow.workflows.generation_helpers import _new_asset_id, _storage_key, cleanup_storage_objects
from app.services.workflow.workflows.steps import ALLOWED_IMAGE_CONTENT_TYPES, IMAGE_EXTENSION_BY_CONTENT_TYPE
from app.services.workflow.workflows.video_analysis import (
    normalize_video_analysis_result,
    to_schema as video_analysis_to_schema,
)

MAX_IMAGE_JOB_RESULTS = 16
WORKFLOW_TITLE_MAX_LENGTH = 255
GENERATION_JOB_TYPES = ("prompt", "image", "script_rewrite", "video_script")
TOPIC_RECOMMENDATION_TYPE = "topic_recommendation"
ACCOUNT_REPORT_TYPE = ACCOUNT_REPORT_WORKFLOW_TYPE


class WorkflowService:
    """Create, query, and dispatch workflows for API routes."""

    def __init__(
        self,
        session: Session,
        ai_service: Any = default_ai_service,
        storage: Any = default_object_storage,
    ) -> None:
        self.session = session
        self.ai_service = ai_service
        self.storage = storage

    def _require_account(self, user_id: str, account_id: str) -> AccountRecord:
        account = (
            self.session.query(AccountRecord)
            .filter(
                AccountRecord.id == account_id,
                AccountRecord.user_id == user_id,
                AccountRecord.status == "active",
            )
            .one_or_none()
        )
        if account is None:
            raise StopIteration(f"account {account_id} is not available for user {user_id}")
        return account

    # ------------------------------------------------------------------
    # generation records
    # ------------------------------------------------------------------

    def get_job(self, user_id: str, account_id: str, job_id: str) -> WorkflowSchema:
        self._require_account(user_id, account_id)
        return job_schema(_get_generation_record(self.session, job_id, account_id=account_id, user_id=user_id))

    def list_jobs(self, user_id: str, account_id: str, page: int = 1, limit: int = 20) -> list[WorkflowSchema]:
        self._require_account(user_id, account_id)
        bounded_page = max(page, 1)
        bounded_limit = min(max(limit, 1), 100)
        records = (
            self.session.query(WorkflowRecord)
            .options(selectinload(WorkflowRecord.assets))
            .filter(
                WorkflowRecord.account_id == account_id,
                WorkflowRecord.user_id == user_id,
                WorkflowRecord.type.in_(GENERATION_JOB_TYPES),
            )
            .order_by(WorkflowRecord.created_at.desc())
            .offset((bounded_page - 1) * bounded_limit)
            .limit(bounded_limit)
            .all()
        )
        return [job_summary_schema(record) for record in records]

    def create_prompt_job(
        self,
        user_id: str,
        account_id: str,
        images: list[Any],
        copy_text: str,
        target_platform: str,
        topic_title: str | None,
        reference_urls: str | list[str] | None = None,
    ) -> WorkflowSchema:
        account = self._require_account(user_id, account_id)
        remote_references = _parse_reference_urls(reference_urls)
        reference_count = len(images) + len(remote_references)
        if reference_count == 0:
            raise ValueError("at least one image is required")
        if reference_count > 8:
            raise ValueError("at most 8 images are supported")
        validated_images = [_validated_upload(image) for image in images]

        now = datetime.now(UTC)
        record = WorkflowRecord(
            id=_new_workflow_id(),
            account_id=account.id,
            user_id=user_id,
            type="prompt",
            status="pending",
            target_platform=target_platform or account.platform,
            topic_title=topic_title,
            copy_text=copy_text or "",
            prompt="",
            ratio=None,
            requested_count=reference_count,
            error="",
            input_payload={
                "imageCount": len(images),
                "referenceUrlCount": len(remote_references),
                "copyText": copy_text or "",
            },
            result_payload={},
            created_at=now,
            updated_at=now,
        )
        self.session.add(record)
        uploaded_keys: list[str] = []
        try:
            self.session.flush()
            for file_name, content_type, data in validated_images:
                asset_id = _new_asset_id()
                key = _storage_key(
                    f"generation/{account_id}/{record.id}/references/{asset_id}{_extension_for(content_type)}"
                )
                url = self.storage.put_bytes(key, data, content_type)
                uploaded_keys.append(key)
                self.session.add(
                    GenerationAssetRecord(
                        id=asset_id,
                        job_id=record.id,
                        account_id=account_id,
                        asset_type="reference",
                        file_name=file_name,
                        mime_type=content_type,
                        storage_key=key,
                        url=url,
                        status="pending",
                        analysis="",
                        error="",
                        meta={},
                        created_at=now,
                    )
                )

            for reference_url in remote_references:
                asset_id = _new_asset_id()
                file_name = _file_name_from_url(reference_url, default=f"{asset_id}.png")
                self.session.add(
                    GenerationAssetRecord(
                        id=asset_id,
                        job_id=record.id,
                        account_id=account_id,
                        asset_type="reference",
                        file_name=file_name,
                        mime_type=_content_type_from_extension(file_name),
                        storage_key=reference_url,
                        url=reference_url,
                        status="pending",
                        analysis="",
                        error="",
                        meta={"source": "reference_url"},
                        created_at=now,
                    )
                )

            self.session.commit()
        except Exception:
            self.session.rollback()
            cleanup_storage_objects(self.storage, uploaded_keys)
            raise
        return self.get_job(user_id, account_id, record.id)

    def create_image_job(
        self,
        user_id: str,
        account_id: str,
        prompt: str,
        count: int,
        ratio: str,
        prompt_job_id: str | None,
        *,
        selected_tag_ids: list[str] | None = None,
        negative_prompt: str = "",
        slots: list[dict[str, object]] | None = None,
        variants_per_slot: int = 1,
        refinement: str = "",
        regenerate_slot_id: str | None = None,
        reference_images: list[Any] | None = None,
        reference_urls: str | list[str] | None = None,
        material_images: list[Any] | None = None,
        reference_strength: int | None = None,
        material_strength: str = "",
    ) -> WorkflowSchema:
        account = self._require_account(user_id, account_id)
        base_prompt = str(prompt or "").strip()
        prompt_categories = self._prompt_tag_categories(user_id, account_id)
        clean_selected_tag_ids = normalize_selected_tag_ids(selected_tag_ids, prompt_categories)
        clean_prompt = build_final_prompt(base_prompt, clean_selected_tag_ids, prompt_categories)
        if not clean_prompt:
            raise ValueError("prompt is required")
        if count < 1 or count > 8:
            raise ValueError("count must be between 1 and 8")

        uses_slots = bool(slots)
        clean_slots = _normalize_image_slots(slots, count)
        clean_variants_per_slot = min(max(int(variants_per_slot or 1), 1), 2)
        total_count = len(clean_slots) * clean_variants_per_slot
        if total_count < 1 or total_count > MAX_IMAGE_JOB_RESULTS:
            raise ValueError(f"total generated images must be between 1 and {MAX_IMAGE_JOB_RESULTS}")

        clean_refinement = str(refinement or "").strip()
        clean_regenerate_slot_id = str(regenerate_slot_id or "").strip() or None
        clean_reference_strength = reference_strength if reference_strength is not None else 70
        clean_material_strength = str(material_strength or "").strip() or "中"
        remote_references = _parse_reference_urls(reference_urls)
        validated_reference_images = [_validated_upload(image) for image in (reference_images or [])]
        validated_material_images = [_validated_upload(image) for image in (material_images or [])]
        if len(validated_reference_images) + len(remote_references) > 8:
            raise ValueError("at most 8 reference images are supported")

        source_prompt_workflow_id = str(prompt_job_id or "").strip() or None
        parent: WorkflowRecord | None = None
        if source_prompt_workflow_id:
            parent = _get_generation_record(
                self.session,
                source_prompt_workflow_id,
                account_id=account_id,
                user_id=user_id,
            )
            if parent.type != "prompt":
                raise ValueError("sourcePromptWorkflowId must refer to a prompt workflow")

        now = datetime.now(UTC)
        record = WorkflowRecord(
            id=_new_workflow_id(),
            account_id=account_id,
            user_id=user_id,
            type="image",
            status="pending",
            target_platform=parent.target_platform if parent is not None else account.platform,
            topic_title=parent.topic_title if parent is not None else None,
            copy_text="",
            prompt=clean_prompt,
            ratio=ratio or "3:4",
            requested_count=total_count,
            error="",
            input_payload={
                "prompt": clean_prompt,
                "basePrompt": base_prompt,
                "sourcePromptWorkflowId": parent.id if parent is not None else None,
                "selectedTagIds": clean_selected_tag_ids,
                "negativePrompt": str(negative_prompt or "").strip(),
                "count": len(clean_slots),
                "ratio": ratio or "3:4",
                "slots": clean_slots,
                "usesSlots": uses_slots,
                "variantsPerSlot": clean_variants_per_slot,
                "refinement": clean_refinement,
                "regenerateSlotId": clean_regenerate_slot_id,
                "referenceImageCount": len(validated_reference_images),
                "referenceUrlCount": len(remote_references),
                "materialImageCount": len(validated_material_images),
                "referenceStrength": clean_reference_strength,
                "materialStrength": clean_material_strength,
            },
            result_payload={},
            created_at=now,
            updated_at=now,
        )
        self.session.add(record)
        uploaded_keys: list[str] = []
        try:
            self.session.flush()
            for role, strength, images in (
                ("reference", clean_reference_strength, validated_reference_images),
                ("material", clean_material_strength, validated_material_images),
            ):
                for file_name, content_type, data in images:
                    asset_id = _new_asset_id()
                    key = _storage_key(
                        f"generation/{account_id}/{record.id}/{role}s/{asset_id}{_extension_for(content_type)}"
                    )
                    url = self.storage.put_bytes(key, data, content_type)
                    uploaded_keys.append(key)
                    self.session.add(
                        GenerationAssetRecord(
                            id=asset_id,
                            job_id=record.id,
                            account_id=account_id,
                            asset_type=role,
                            file_name=file_name,
                            mime_type=content_type,
                            storage_key=key,
                            url=url,
                            status="completed",
                            analysis="",
                            error="",
                            meta={"role": role, "strength": strength},
                            created_at=now,
                        )
                    )
            for reference_url in remote_references:
                asset_id = _new_asset_id()
                file_name = _file_name_from_url(reference_url, default=f"{asset_id}.png")
                self.session.add(
                    GenerationAssetRecord(
                        id=asset_id,
                        job_id=record.id,
                        account_id=account_id,
                        asset_type="reference",
                        file_name=file_name,
                        mime_type=_content_type_from_extension(file_name),
                        storage_key=reference_url,
                        url=reference_url,
                        status="completed",
                        analysis="",
                        error="",
                        meta={
                            "role": "reference",
                            "source": "reference_url",
                            "strength": clean_reference_strength,
                        },
                        created_at=now,
                    )
                )
            self.session.commit()
        except Exception:
            self.session.rollback()
            cleanup_storage_objects(self.storage, uploaded_keys)
            raise
        return self.get_job(user_id, account_id, record.id)

    def create_script_rewrite_job(
        self,
        user_id: str,
        account_id: str,
        original_script: list[str],
        copy_text: str,
        target_platform: str,
        topic_title: str | None,
    ) -> WorkflowSchema:
        account = self._require_account(user_id, account_id)
        script_lines = [str(line).strip() for line in original_script if str(line).strip()]
        if not script_lines:
            raise ValueError("original script is required")

        now = datetime.now(UTC)
        record = WorkflowRecord(
            id=_new_workflow_id(),
            account_id=account.id,
            user_id=user_id,
            type="script_rewrite",
            status="pending",
            target_platform=target_platform or account.platform,
            topic_title=topic_title,
            copy_text=str(copy_text or "").strip(),
            prompt="",
            ratio=None,
            requested_count=len(script_lines),
            error="",
            input_payload={"originalScript": script_lines, "copyText": str(copy_text or "").strip()},
            result_payload={},
            created_at=now,
            updated_at=now,
        )
        self.session.add(record)
        self.session.commit()
        return self.get_job(user_id, account_id, record.id)

    # ------------------------------------------------------------------
    # prompt tags and templates
    # ------------------------------------------------------------------

    def list_prompt_tag_categories(self, user_id: str, account_id: str) -> list[PromptTagCategorySchema]:
        self._require_account(user_id, account_id)
        return [_prompt_tag_category_schema(category) for category in self._prompt_tag_categories(user_id, account_id)]

    def create_prompt_tag_category(
        self,
        user_id: str,
        account_id: str,
        payload: PromptTagCategoryCreateRequest,
    ) -> PromptTagCategorySchema:
        account = self._require_account(user_id, account_id)
        now = datetime.now(UTC)
        record = GenerationPromptTagCategoryRecord(
            id=f"ptc_{uuid4().hex}",
            account_id=account.id,
            user_id=user_id,
            label=payload.label.strip(),
            sort_order=payload.sortOrder,
            created_at=now,
            updated_at=now,
        )
        self.session.add(record)
        self.session.commit()
        return _custom_prompt_tag_category_schema(record)

    def update_prompt_tag_category(
        self,
        user_id: str,
        account_id: str,
        category_id: str,
        payload: PromptTagCategoryUpdateRequest,
    ) -> PromptTagCategorySchema:
        record = self._get_custom_prompt_tag_category(user_id, account_id, category_id)
        if payload.label is not None:
            record.label = payload.label.strip()
        if payload.sortOrder is not None:
            record.sort_order = payload.sortOrder
        record.updated_at = datetime.now(UTC)
        self.session.commit()
        return _custom_prompt_tag_category_schema(record)

    def delete_prompt_tag_category(self, user_id: str, account_id: str, category_id: str) -> None:
        record = self._get_custom_prompt_tag_category(user_id, account_id, category_id)
        self.session.delete(record)
        self.session.commit()

    def create_prompt_tag(
        self,
        user_id: str,
        account_id: str,
        category_id: str,
        payload: PromptTagCreateRequest,
    ) -> PromptTagSchema:
        category = self._get_custom_prompt_tag_category(user_id, account_id, category_id)
        now = datetime.now(UTC)
        record = GenerationPromptTagRecord(
            id=f"pt_{uuid4().hex}",
            category_id=category.id,
            account_id=account_id,
            user_id=user_id,
            label=payload.label.strip(),
            prompt=payload.prompt.strip(),
            sort_order=payload.sortOrder,
            created_at=now,
            updated_at=now,
        )
        self.session.add(record)
        self.session.commit()
        return _custom_prompt_tag_schema(record)

    def update_prompt_tag(
        self,
        user_id: str,
        account_id: str,
        tag_id: str,
        payload: PromptTagUpdateRequest,
    ) -> PromptTagSchema:
        record = self._get_custom_prompt_tag(user_id, account_id, tag_id)
        if payload.label is not None:
            record.label = payload.label.strip()
        if payload.prompt is not None:
            record.prompt = payload.prompt.strip()
        if payload.sortOrder is not None:
            record.sort_order = payload.sortOrder
        record.updated_at = datetime.now(UTC)
        self.session.commit()
        return _custom_prompt_tag_schema(record)

    def delete_prompt_tag(self, user_id: str, account_id: str, tag_id: str) -> None:
        record = self._get_custom_prompt_tag(user_id, account_id, tag_id)
        self.session.delete(record)
        self.session.commit()

    def list_prompt_templates(self, user_id: str, account_id: str) -> list[PromptTemplateSchema]:
        self._require_account(user_id, account_id)
        records = (
            self.session.query(GenerationPromptTemplateRecord)
            .filter(
                GenerationPromptTemplateRecord.account_id == account_id,
                GenerationPromptTemplateRecord.user_id == user_id,
            )
            .order_by(GenerationPromptTemplateRecord.created_at.desc())
            .all()
        )
        return [_prompt_template_schema(record) for record in records]

    def create_prompt_template(
        self,
        user_id: str,
        account_id: str,
        payload: PromptTemplateCreateRequest,
    ) -> PromptTemplateSchema:
        account = self._require_account(user_id, account_id)
        prompt_categories = self._prompt_tag_categories(user_id, account_id)
        selected_tag_ids = normalize_selected_tag_ids(payload.selectedTagIds, prompt_categories)
        now = datetime.now(UTC)
        record = GenerationPromptTemplateRecord(
            id=f"tpl_{uuid4().hex}",
            account_id=account.id,
            user_id=user_id,
            name=payload.name.strip(),
            description=str(payload.description or "").strip(),
            prompt=str(payload.prompt or "").strip(),
            selected_tag_ids=selected_tag_ids,
            negative_prompt=str(payload.negativePrompt or "").strip(),
            params=payload.params.model_dump(),
            preview_prompt=build_final_prompt(payload.prompt, selected_tag_ids, prompt_categories),
            created_at=now,
            updated_at=now,
        )
        self.session.add(record)
        self.session.commit()
        return _prompt_template_schema(record)

    def update_prompt_template(
        self,
        user_id: str,
        account_id: str,
        template_id: str,
        payload: PromptTemplateUpdateRequest,
    ) -> PromptTemplateSchema:
        self._require_account(user_id, account_id)
        record = self._get_prompt_template_record(user_id, account_id, template_id)
        if payload.name is not None:
            record.name = payload.name.strip()
        if payload.description is not None:
            record.description = str(payload.description or "").strip()
        if payload.prompt is not None:
            record.prompt = str(payload.prompt or "").strip()
        if payload.selectedTagIds is not None:
            record.selected_tag_ids = normalize_selected_tag_ids(
                payload.selectedTagIds,
                self._prompt_tag_categories(user_id, account_id),
            )
        if payload.negativePrompt is not None:
            record.negative_prompt = str(payload.negativePrompt or "").strip()
        if payload.params is not None:
            record.params = payload.params.model_dump()
        record.preview_prompt = build_final_prompt(
            record.prompt,
            record.selected_tag_ids,
            self._prompt_tag_categories(user_id, account_id),
        )
        record.updated_at = datetime.now(UTC)
        self.session.commit()
        return _prompt_template_schema(record)

    def delete_prompt_template(self, user_id: str, account_id: str, template_id: str) -> None:
        self._require_account(user_id, account_id)
        record = self._get_prompt_template_record(user_id, account_id, template_id)
        self.session.delete(record)
        self.session.commit()

    def _prompt_tag_categories(self, user_id: str, account_id: str) -> list[dict[str, object]]:
        db_categories = (
            self.session.query(GenerationPromptTagCategoryRecord)
            .filter(
                GenerationPromptTagCategoryRecord.account_id == account_id,
                GenerationPromptTagCategoryRecord.user_id == user_id,
            )
            .order_by(GenerationPromptTagCategoryRecord.sort_order, GenerationPromptTagCategoryRecord.created_at)
            .all()
        )
        builtin_labels = {cat["label"] for cat in prompt_tag_categories}
        db_builtins: list[dict[str, object]] = []
        db_customs: list[dict[str, object]] = []
        for category in db_categories:
            if category.label in builtin_labels:
                db_builtins.append(_custom_prompt_tag_category_dict(category))
            else:
                db_customs.append(_custom_prompt_tag_category_dict(category))
        return db_builtins + [dict(category) for category in prompt_tag_categories] + db_customs

    def _get_custom_prompt_tag_category(
        self,
        user_id: str,
        account_id: str,
        category_id: str,
    ) -> GenerationPromptTagCategoryRecord:
        self._require_account(user_id, account_id)
        record = (
            self.session.query(GenerationPromptTagCategoryRecord)
            .filter(
                GenerationPromptTagCategoryRecord.id == category_id,
                GenerationPromptTagCategoryRecord.account_id == account_id,
                GenerationPromptTagCategoryRecord.user_id == user_id,
            )
            .one_or_none()
        )
        if record is None:
            raise StopIteration(f"prompt tag category {category_id} was not found")
        return record

    def _get_custom_prompt_tag(
        self,
        user_id: str,
        account_id: str,
        tag_id: str,
    ) -> GenerationPromptTagRecord:
        self._require_account(user_id, account_id)
        record = (
            self.session.query(GenerationPromptTagRecord)
            .filter(
                GenerationPromptTagRecord.id == tag_id,
                GenerationPromptTagRecord.account_id == account_id,
                GenerationPromptTagRecord.user_id == user_id,
            )
            .one_or_none()
        )
        if record is None:
            raise StopIteration(f"prompt tag {tag_id} was not found")
        return record

    def _get_prompt_template_record(
        self,
        user_id: str,
        account_id: str,
        template_id: str,
    ) -> GenerationPromptTemplateRecord:
        record = (
            self.session.query(GenerationPromptTemplateRecord)
            .filter(
                GenerationPromptTemplateRecord.id == template_id,
                GenerationPromptTemplateRecord.account_id == account_id,
                GenerationPromptTemplateRecord.user_id == user_id,
            )
            .one_or_none()
        )
        if record is None:
            raise StopIteration(f"prompt template {template_id} was not found")
        return record

    def create_topic_recommendation_job(self, user_id: str, account_id: str) -> tuple[WorkflowSchema, bool]:
        account = self.session.scalar(
            select(AccountRecord)
            .where(
                AccountRecord.id == account_id,
                AccountRecord.user_id == user_id,
                AccountRecord.status == "active",
            )
            .with_for_update()
        )
        if account is None:
            raise StopIteration(f"account {account_id} is not available for user {user_id}")
        existing = self.session.scalar(
            select(WorkflowRecord)
            .where(
                WorkflowRecord.user_id == user_id,
                WorkflowRecord.account_id == account_id,
                WorkflowRecord.type == TOPIC_RECOMMENDATION_TYPE,
                WorkflowRecord.status.in_(["pending", "running"]),
            )
            .order_by(WorkflowRecord.created_at.desc())
            .limit(1)
        )
        if existing is not None:
            return job_schema(_get_generation_record(self.session, existing.id, account_id=account_id, user_id=user_id)), False

        now = datetime.now(UTC)
        record = WorkflowRecord(
            id=_new_workflow_id(),
            account_id=account.id,
            user_id=user_id,
            type=TOPIC_RECOMMENDATION_TYPE,
            status="pending",
            progress=0,
            current_stage="pending",
            target_platform=account.platform,
            topic_title=None,
            copy_text="",
            prompt="",
            ratio=None,
            requested_count=8,
            error="",
            input_payload={"accountId": account.id, "platforms": list(account.platforms or [account.platform])},
            result_payload={},
            created_at=now,
            updated_at=now,
        )
        self.session.add(record)
        self.session.commit()
        self.session.refresh(record)
        return job_schema(_get_generation_record(self.session, record.id, account_id=account_id, user_id=user_id)), True

    def get_topic_recommendation_job(self, user_id: str, account_id: str, workflow_id: str) -> WorkflowSchema:
        self._require_account(user_id, account_id)
        record = self.session.scalar(
            select(WorkflowRecord).where(
                WorkflowRecord.id == workflow_id,
                WorkflowRecord.user_id == user_id,
                WorkflowRecord.account_id == account_id,
                WorkflowRecord.type == TOPIC_RECOMMENDATION_TYPE,
            )
        )
        if record is None:
            raise StopIteration(f"topic recommendation workflow {workflow_id} was not found")
        return job_schema(_get_generation_record(self.session, workflow_id, account_id=account_id, user_id=user_id))

    def mark_topic_recommendation_job_failed(
        self,
        user_id: str,
        account_id: str,
        workflow_id: str,
        error: str,
    ) -> WorkflowSchema:
        record = self.session.scalar(
            select(WorkflowRecord).where(
                WorkflowRecord.id == workflow_id,
                WorkflowRecord.user_id == user_id,
                WorkflowRecord.account_id == account_id,
                WorkflowRecord.type == TOPIC_RECOMMENDATION_TYPE,
            )
        )
        if record is None:
            raise StopIteration(f"topic recommendation workflow {workflow_id} was not found")
        record.status = "failed"
        record.current_stage = "failed"
        record.error = error
        record.updated_at = datetime.now(UTC)
        self.session.commit()
        self.session.refresh(record)
        return job_schema(_get_generation_record(self.session, workflow_id, account_id=account_id, user_id=user_id))

    # ------------------------------------------------------------------
    # account report records
    # ------------------------------------------------------------------

    def create_account_report_job(
        self,
        user_id: str,
        account_id: str,
        reference_comments: bool = False,
        section_key: str | None = None,
    ) -> tuple[WorkflowSchema, bool]:
        """创建整份报告任务；section_key 仅供旧客户端兼容。"""
        if section_key:
            return self.create_account_report_section_job(
                user_id,
                account_id,
                section_key,
                reference_comments=reference_comments,
            )
        return self._create_account_report_job(
            user_id,
            account_id,
            workflow_type=ACCOUNT_REPORT_WORKFLOW_TYPE,
            reference_comments=reference_comments,
        )

    def create_account_report_section_job(
        self,
        user_id: str,
        account_id: str,
        section_key: str,
        reference_comments: bool = False,
    ) -> tuple[WorkflowSchema, bool]:
        """按板块创建类型独立的报告任务。"""
        return self._create_account_report_job(
            user_id,
            account_id,
            workflow_type=section_workflow_type(section_key),
            reference_comments=reference_comments,
            section_key=section_key,
        )

    def _create_account_report_job(
        self,
        user_id: str,
        account_id: str,
        *,
        workflow_type: str,
        reference_comments: bool,
        section_key: str | None = None,
    ) -> tuple[WorkflowSchema, bool]:
        """创建报告任务，或返回与当前请求写入范围冲突的任务。

        Locking the owning account serializes refresh requests on databases that
        support ``FOR UPDATE``.  This keeps the de-duplication decision and
        insert in one transaction without persisting crawler credentials.

        不同板块只写各自字段，因此允许并发；整份报告会写全部板块，仍与
        任一板块任务互斥。同一板块重复提交继续复用已有任务。
        """

        try:
            account = self.session.scalar(
                select(AccountRecord)
                .where(
                    AccountRecord.id == account_id,
                    AccountRecord.user_id == user_id,
                    AccountRecord.status == "active",
                )
                .with_for_update()
            )
            if account is None:
                raise StopIteration(f"account {account_id} is not available for user {user_id}")

            conflicting_types = (
                ACCOUNT_REPORT_WORKFLOW_TYPES
                if workflow_type == ACCOUNT_REPORT_WORKFLOW_TYPE
                else (ACCOUNT_REPORT_WORKFLOW_TYPE, workflow_type)
            )
            existing = self.session.scalar(
                select(WorkflowRecord)
                .where(
                    WorkflowRecord.user_id == user_id,
                    WorkflowRecord.account_id == account_id,
                    WorkflowRecord.type.in_(conflicting_types),
                    WorkflowRecord.status.in_(["pending", "running"]),
                )
                .order_by(WorkflowRecord.created_at.desc(), WorkflowRecord.id.desc())
                .limit(1)
            )
            if existing is not None:
                existing_id = existing.id
                self.session.commit()
                return self.get_account_report_job(user_id, account_id, existing_id), False

            platforms = list(account.platforms or [account.platform])
            now = datetime.now(UTC)
            record = WorkflowRecord(
                id=_new_workflow_id(),
                account_id=account.id,
                user_id=user_id,
                type=workflow_type,
                status="pending",
                progress=0,
                current_stage="pending",
                target_platform=account.platform,
                topic_title=None,
                copy_text="",
                prompt="",
                ratio=None,
                requested_count=len(platforms),
                error="",
                input_payload={
                    "accountId": account.id,
                    "platforms": platforms,
                    "referenceComments": bool(reference_comments),
                    **({"sectionKey": section_key} if section_key else {}),
                },
                result_payload={},
                created_at=now,
                updated_at=now,
            )
            self.session.add(record)
            self.session.commit()
            return self.get_account_report_job(user_id, account_id, record.id), True
        except Exception:
            self.session.rollback()
            raise

    def get_active_account_report_jobs(
        self, user_id: str, account_id: str
    ) -> list[WorkflowSchema]:
        self._require_account(user_id, account_id)
        records = self.session.scalars(
            select(WorkflowRecord)
            .where(
                WorkflowRecord.user_id == user_id,
                WorkflowRecord.account_id == account_id,
                WorkflowRecord.type.in_(ACCOUNT_REPORT_WORKFLOW_TYPES),
                WorkflowRecord.status.in_(["pending", "running"]),
            )
            .order_by(WorkflowRecord.created_at.asc(), WorkflowRecord.id.asc())
        ).all()
        return [
            job_schema(
                _get_generation_record(
                    self.session,
                    record.id,
                    account_id=account_id,
                    user_id=user_id,
                )
            )
            for record in records
        ]

    def get_latest_account_report_job(self, user_id: str, account_id: str) -> WorkflowSchema:
        self._require_account(user_id, account_id)
        record = self.session.scalar(
            select(WorkflowRecord)
            .where(
                WorkflowRecord.user_id == user_id,
                WorkflowRecord.account_id == account_id,
                WorkflowRecord.type.in_(ACCOUNT_REPORT_WORKFLOW_TYPES),
            )
            .order_by(WorkflowRecord.created_at.desc(), WorkflowRecord.id.desc())
            .limit(1)
        )
        if record is None:
            raise StopIteration(f"account report workflow for account {account_id} was not found")
        return job_schema(_get_generation_record(self.session, record.id, account_id=account_id, user_id=user_id))

    def get_account_report_job(self, user_id: str, account_id: str, workflow_id: str) -> WorkflowSchema:
        self._require_account(user_id, account_id)
        record = self.session.scalar(
            select(WorkflowRecord).where(
                WorkflowRecord.id == workflow_id,
                WorkflowRecord.user_id == user_id,
                WorkflowRecord.account_id == account_id,
                WorkflowRecord.type.in_(ACCOUNT_REPORT_WORKFLOW_TYPES),
            )
        )
        if record is None:
            raise StopIteration(f"account report workflow {workflow_id} was not found")
        return job_schema(_get_generation_record(self.session, workflow_id, account_id=account_id, user_id=user_id))

    def mark_account_report_job_failed(
        self,
        user_id: str,
        account_id: str,
        workflow_id: str,
        error: str,
    ) -> WorkflowSchema:
        try:
            record = self.session.scalar(
                select(WorkflowRecord).where(
                    WorkflowRecord.id == workflow_id,
                    WorkflowRecord.user_id == user_id,
                    WorkflowRecord.account_id == account_id,
                    WorkflowRecord.type.in_(ACCOUNT_REPORT_WORKFLOW_TYPES),
                )
            )
            if record is None:
                raise StopIteration(f"account report workflow {workflow_id} was not found")
            record.status = "failed"
            record.current_stage = "failed"
            record.error = error
            record.updated_at = datetime.now(UTC)
            self.session.commit()
            return self.get_account_report_job(user_id, account_id, workflow_id)
        except Exception:
            self.session.rollback()
            raise

    # ------------------------------------------------------------------
    # execution helpers
    # ------------------------------------------------------------------

    def run_job(
        self,
        job_type: str,
        job_id: str,
        *,
        session_factory: Callable[[], Any] | None = None,
    ) -> Any:
        workflow_class = WorkflowRegister.get(job_type)
        scheduler = WorkflowScheduler(
            ai_service=self.ai_service,
            storage=self.storage,
            store=WorkflowStore(session_factory=session_factory or _existing_session_factory(self.session)),
            use_default_concurrency=False,
        )
        _run_coroutine_sync(scheduler._execute(workflow_class, job_type, job_id, _workflow_context(self.session, job_id)))
        self.session.expire_all()
        record = self.session.get(WorkflowRecord, job_id)
        if record is None:
            raise StopIteration(f"workflow {job_id} was not found")
        if job_type == "video_analysis":
            return video_analysis_to_schema(record)
        return job_schema(_get_generation_record(self.session, job_id))

    @staticmethod
    def run_in_new_session(
        job_type: str,
        job_id: str,
        session_factory: Callable[[], Any],
        ai_service: Any = default_ai_service,
        storage: Any = default_object_storage,
    ) -> Any:
        with session_factory() as session:
            return WorkflowService(session, ai_service=ai_service, storage=storage).run_job(
                job_type,
                job_id,
                session_factory=session_factory,
            )

    # ------------------------------------------------------------------
    # video analysis compatibility facade
    # ------------------------------------------------------------------

    def create_video_analysis_job(
        self,
        user_id: str,
        payload: CreateVideoAnalysisWorkflowRequest,
    ) -> VideoAnalysisWorkflowSchema:
        account_id = _clean(payload.accountId)
        if account_id:
            account = self.session.scalar(
                select(AccountRecord).where(AccountRecord.id == account_id, AccountRecord.user_id == user_id)
            )
            if account is None:
                raise StopIteration(f"account {account_id} is not available for user {user_id}")

        video_url = _resolve_video_url(payload)
        if not video_url:
            raise ValueError("请先解析包含视频的链接")

        now = datetime.now(UTC)
        record = WorkflowRecord(
            id=_new_workflow_id(),
            type="video_analysis",
            user_id=user_id,
            account_id=account_id or None,
            creation_id=_clean(payload.creationId) or None,
            status="pending",
            progress=0,
            current_stage="pending",
            source_url=_clean(payload.sourceUrl),
            video_url=video_url,
            cover_url=_clean(payload.coverUrl),
            platform=_clean(payload.platform),
            # Extractors may return the full post copy as the title. Keep the
            # complete copy in description, but respect workflows.title's
            # VARCHAR(255) database contract.
            title=_clean(payload.title)[:WORKFLOW_TITLE_MAX_LENGTH],
            description=_clean(payload.description),
            input_payload={
                "hashtags": list(payload.hashtags or []),
                "images": [item.model_dump() for item in payload.images],
                "videos": [item.model_dump() for item in payload.videos],
            },
            result_payload=normalize_video_analysis_result({}),
            error="",
            created_at=now,
            updated_at=now,
        )
        self.session.add(record)
        self.session.commit()
        self.session.refresh(record)
        return video_analysis_to_schema(record)

    def list_video_analysis_jobs(
        self,
        user_id: str,
        *,
        account_id: str | None = None,
        creation_id: str | None = None,
        limit: int = 20,
    ) -> list[VideoAnalysisWorkflowSchema]:
        bounded_limit = min(max(limit, 1), 100)
        statement = select(WorkflowRecord).where(
            WorkflowRecord.user_id == user_id,
            WorkflowRecord.type == "video_analysis",
        )
        if account_id:
            statement = statement.where(WorkflowRecord.account_id == account_id)
        if creation_id:
            statement = statement.where(WorkflowRecord.creation_id == creation_id)
        records = self.session.scalars(
            statement.order_by(WorkflowRecord.created_at.desc()).limit(bounded_limit)
        ).all()
        return [video_analysis_to_schema(record) for record in records]

    def get_video_analysis_job(self, user_id: str, job_id: str) -> VideoAnalysisWorkflowSchema:
        record = self.session.scalar(
            select(WorkflowRecord).where(
                WorkflowRecord.id == job_id,
                WorkflowRecord.user_id == user_id,
                WorkflowRecord.type == "video_analysis",
            )
        )
        if record is None:
            raise StopIteration(f"video analysis job {job_id} was not found")
        return video_analysis_to_schema(record)


def job_schema(record: WorkflowRecord) -> WorkflowSchema:
    assets = sorted(getattr(record, "assets", []) or [], key=lambda item: item.created_at)
    steps = sorted(getattr(record, "steps", []) or [], key=lambda item: (item.sort_order, item.created_at))
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
                id=asset.id,
                assetType=asset.asset_type,
                fileName=asset.file_name,
                mimeType=asset.mime_type,
                url=asset.url,
                status=asset.status,
                analysis=asset.analysis,
                error=asset.error,
                meta=asset.meta or {},
            )
            for asset in assets
        ],
        steps=[
            WorkflowStepSchema(
                id=step.id,
                type=step.type,
                status=step.status,
                progress=step.progress,
                sortOrder=step.sort_order,
                groupKey=step.group_key,
                assetId=step.asset_id,
                inputPayload=step.input_payload or {},
                resultPayload=step.result_payload or {},
                error=step.error,
                createdAt=step.created_at,
                updatedAt=step.updated_at,
            )
            for step in steps
        ],
        createdAt=record.created_at,
        updatedAt=record.updated_at,
    )


def job_summary_schema(record: WorkflowRecord) -> WorkflowSchema:
    assets = sorted(getattr(record, "assets", []) or [], key=lambda item: item.created_at)
    return WorkflowSchema(
        id=record.id,
        type=record.type,
        status=record.status,
        progress=record.progress,
        currentStage=record.current_stage,
        targetPlatform=record.target_platform,
        topicTitle=record.topic_title,
        copyText="",
        prompt="",
        ratio=record.ratio,
        requestedCount=record.requested_count,
        error=record.error,
        inputPayload={},
        resultPayload={},
        assets=[
            GenerationAssetSchema(
                id=asset.id,
                assetType=asset.asset_type,
                fileName=asset.file_name,
                mimeType=asset.mime_type,
                url=asset.url,
                status=asset.status,
                analysis="",
                error=asset.error,
                meta={},
            )
            for asset in assets
        ],
        steps=[],
        createdAt=record.created_at,
        updatedAt=record.updated_at,
    )


def _get_generation_record(
    session: Session,
    job_id: str,
    *,
    account_id: str | None = None,
    user_id: str | None = None,
) -> WorkflowRecord:
    query = session.query(WorkflowRecord).options(selectinload(WorkflowRecord.assets), selectinload(WorkflowRecord.steps))
    query = query.filter(WorkflowRecord.id == job_id)
    if account_id is not None:
        query = query.filter(WorkflowRecord.account_id == account_id)
    if user_id is not None:
        query = query.filter(WorkflowRecord.user_id == user_id)
    record = query.one_or_none()
    if record is None:
        raise StopIteration(f"generation job {job_id} was not found")
    return record


def _new_workflow_id() -> str:
    return f"wf_{uuid4().hex}"


def _normalize_image_slots(slots: list[dict[str, object]] | None, count: int) -> list[dict[str, str]]:
    normalized: list[dict[str, str]] = []
    for index, slot in enumerate(slots or []):
        slot_id = _clean(slot.get("slotId") if isinstance(slot, dict) else "") or f"slot_{index + 1}"
        normalized.append(
            {
                "slotId": slot_id,
                "sourceType": _clean(slot.get("sourceType") if isinstance(slot, dict) else "") or "manual",
                "sourceUrl": _clean(slot.get("sourceUrl") if isinstance(slot, dict) else ""),
                "sourcePrompt": _clean(slot.get("sourcePrompt") if isinstance(slot, dict) else ""),
            }
        )
    if normalized:
        return normalized
    return [
        {"slotId": f"slot_{index + 1}", "sourceType": "manual", "sourceUrl": "", "sourcePrompt": ""}
        for index in range(count)
    ]


def _prompt_template_schema(record: GenerationPromptTemplateRecord) -> PromptTemplateSchema:
    return PromptTemplateSchema(
        id=record.id,
        name=record.name,
        description=record.description,
        prompt=record.prompt,
        selectedTagIds=list(record.selected_tag_ids or []),
        negativePrompt=record.negative_prompt,
        params={str(key): str(value) for key, value in (record.params or {}).items()},
        previewPrompt=record.preview_prompt,
        createdAt=record.created_at,
        updatedAt=record.updated_at,
    )


def _prompt_tag_category_schema(category: dict[str, object]) -> PromptTagCategorySchema:
    return PromptTagCategorySchema(
        id=str(category.get("id") or ""),
        label=str(category.get("label") or ""),
        source=str(category.get("source") or "system"),
        sortOrder=int(category.get("sortOrder") or 0),
        tags=[
            PromptTagSchema(
                id=str(tag.get("id") or ""),
                categoryId=str(tag.get("categoryId") or category.get("id") or ""),
                label=str(tag.get("label") or ""),
                prompt=str(tag.get("prompt") or ""),
                source=str(tag.get("source") or category.get("source") or "system"),
                sortOrder=int(tag.get("sortOrder") or 0),
            )
            for tag in category.get("tags") or []
            if isinstance(tag, dict)
        ],
    )


def _custom_prompt_tag_category_dict(record: GenerationPromptTagCategoryRecord) -> dict[str, object]:
    return {
        "id": record.id,
        "label": record.label,
        "source": "custom",
        "sortOrder": record.sort_order,
        "tags": [
            {
                "id": tag.id,
                "categoryId": record.id,
                "label": tag.label,
                "prompt": tag.prompt,
                "source": "custom",
                "sortOrder": tag.sort_order,
            }
            for tag in sorted(record.tags, key=lambda item: (item.sort_order, item.created_at))
        ],
    }


def _custom_prompt_tag_category_schema(record: GenerationPromptTagCategoryRecord) -> PromptTagCategorySchema:
    return _prompt_tag_category_schema(_custom_prompt_tag_category_dict(record))


def _custom_prompt_tag_schema(record: GenerationPromptTagRecord) -> PromptTagSchema:
    return PromptTagSchema(
        id=record.id,
        categoryId=record.category_id,
        label=record.label,
        prompt=record.prompt,
        source="custom",
        sortOrder=record.sort_order,
    )


def _upload_file_name(image: Any) -> str:
    return str(getattr(image, "filename", None) or getattr(image, "file_name", None) or "upload.png")


def _upload_content_type(image: Any) -> str:
    return str(getattr(image, "content_type", None) or "application/octet-stream")


def _upload_bytes(image: Any) -> bytes:
    return read_upload_file_limited(image, limit=settings.max_upload_image_bytes, label="image upload")


def _validated_upload(image: Any) -> tuple[str, str, bytes]:
    file_name = _upload_file_name(image)
    content_type = _upload_content_type(image)
    if content_type not in ALLOWED_IMAGE_CONTENT_TYPES:
        raise ValueError(f"unsupported image content type: {content_type}")
    return file_name, content_type, _upload_bytes(image)


def _parse_reference_urls(value: str | list[str] | None) -> list[str]:
    if value is None:
        return []
    raw_items = value if isinstance(value, list) else str(value).splitlines()
    urls: list[str] = []
    seen = set()
    for item in raw_items:
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
    return {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
    }.get(suffix, "image/png")


def _extension_for(content_type: str) -> str:
    return IMAGE_EXTENSION_BY_CONTENT_TYPE.get(content_type, ".png")


def _resolve_video_url(payload: CreateVideoAnalysisWorkflowRequest) -> str:
    direct_url = _clean(payload.videoUrl)
    if direct_url:
        return direct_url
    for item in payload.videos or []:
        url = _clean(item.url)
        if url:
            return url
    return ""


def _clean(value: Any) -> str:
    return str(value or "").strip()


@contextmanager
def _existing_session_scope(session: Session) -> Iterator[Session]:
    yield session


def _existing_session_factory(session: Session) -> Callable[[], Any]:
    return lambda: _existing_session_scope(session)


def _workflow_context(session: Session, workflow_id: str) -> dict[str, Any]:
    record = session.get(WorkflowRecord, workflow_id)
    if record is None:
        return {}
    return {
        "video_url": getattr(record, "video_url", "") or "",
        "user_id": getattr(record, "user_id", "") or "",
        "account_id": getattr(record, "account_id", None),
    }


def _run_coroutine_sync(coro: Any) -> Any:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    result: list[Any] = []
    error: list[BaseException] = []

    def _runner() -> None:
        try:
            result.append(asyncio.run(coro))
        except BaseException as exc:
            error.append(exc)

    thread = threading.Thread(target=_runner, daemon=True)
    thread.start()
    thread.join()
    if error:
        raise error[0]
    return result[0] if result else None
