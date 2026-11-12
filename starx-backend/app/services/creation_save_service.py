from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import select

from app.db.models import (
    ContentCreationRecord,
    ExtractHistoryRecord,
    MaterialRecord,
    WorkflowRecord,
)
from app.models.material import Material
from app.models.task import Task
from app.schemas.creations import SubmitCreationTaskRequest
from app.services.db_service import DBService


class CreationSaveError(ValueError):
    pass


@dataclass(frozen=True)
class AssetPersistenceSummary:
    job_id: str
    history_id: str
    status: str
    error: str = ""


@dataclass(frozen=True)
class CreationSaveResult:
    task: Task
    material: Material | None
    asset_persistence: AssetPersistenceSummary | None
    should_dispatch: bool = False


class CreationSaveService:
    def __init__(self, db_service: DBService) -> None:
        self.db_service = db_service
        self.session = db_service.session

    def save(
        self,
        user_id: str,
        account_id: str,
        creation_id: str,
        payload: SubmitCreationTaskRequest,
    ) -> CreationSaveResult:
        try:
            task = self.db_service.submit_creation_task(
                user_id,
                account_id,
                creation_id,
                payload.topicId,
                payload.targetPlatform,
                payload.type,
                payload.content,
                creation_state=payload.creationState,
                assignee=payload.assignee,
                due_date=payload.dueDate,
                priority=payload.priority,
                status=payload.status,
                handoff_note=payload.handoffNote,
                commit=False,
            )
            creation = self.session.scalar(
                select(ContentCreationRecord).where(
                    ContentCreationRecord.id == creation_id,
                    ContentCreationRecord.account_id == account_id,
                    ContentCreationRecord.user_id == user_id,
                )
            )
            if creation is None:
                raise CreationSaveError("creation is not available")

            history: ExtractHistoryRecord | None = None
            extracted_assets: list[dict[str, object]] = []
            if payload.persistExtractAssets:
                history = self._resolve_history(user_id, account_id, creation_id, payload)
                extracted_assets = _history_assets(history)
                creation.assets = _merge_assets(list(creation.assets or []), extracted_assets)

            material_record = self._create_script_material(
                account_id,
                payload,
                extracted_assets,
            ) if payload.saveScriptMaterial else None

            summary: AssetPersistenceSummary | None = None
            should_dispatch = False
            if history is not None:
                summary, should_dispatch = self._prepare_asset_workflow(
                    user_id=user_id,
                    account_id=account_id,
                    creation=creation,
                    history=history,
                    material_record=material_record,
                )

            self.session.commit()
            material = _material_from_record(material_record) if material_record is not None else None
            return CreationSaveResult(
                task=task,
                material=material,
                asset_persistence=summary,
                should_dispatch=should_dispatch,
            )
        except Exception:
            self.session.rollback()
            raise

    def _resolve_history(
        self,
        user_id: str,
        account_id: str,
        creation_id: str,
        payload: SubmitCreationTaskRequest,
    ) -> ExtractHistoryRecord:
        history_id = str(payload.extractHistoryId or "").strip()
        history = None
        if history_id:
            history = self.session.scalar(
                select(ExtractHistoryRecord).where(
                    ExtractHistoryRecord.id == history_id,
                    ExtractHistoryRecord.user_id == user_id,
                    ExtractHistoryRecord.account_id == account_id,
                )
            )
            if history is None:
                raise CreationSaveError("extract history is not available")
        elif payload.linkReference:
            history = _history_from_reference(
                user_id=user_id,
                account_id=account_id,
                creation_id=creation_id,
                reference=payload.linkReference,
            )
            self.session.add(history)
            self.session.flush()
        else:
            raise CreationSaveError("current link reference is required")

        history.creation_id = creation_id
        return history

    def _create_script_material(
        self,
        account_id: str,
        payload: SubmitCreationTaskRequest,
        assets: list[dict[str, object]],
    ) -> MaterialRecord:
        record = MaterialRecord(
            id=f"m{uuid4().hex[:8]}",
            account_id=account_id,
            name=f"{payload.content.title.strip() or '创作内容'}_素材",
            material_type="script",
            tags=["自动保存", payload.targetPlatform],
            material_date=str(date.today()),
            thumb="📝",
            assets=[dict(item) for item in assets],
        )
        self.session.add(record)
        self.session.flush()
        return record

    def _prepare_asset_workflow(
        self,
        *,
        user_id: str,
        account_id: str,
        creation: ContentCreationRecord,
        history: ExtractHistoryRecord,
        material_record: MaterialRecord | None,
    ) -> tuple[AssetPersistenceSummary, bool]:
        existing_workflow = None
        if history.persistence_job_id and history.persistence_status in {"pending", "completed"}:
            existing_workflow = self.session.get(WorkflowRecord, history.persistence_job_id)

        material_ids = [material_record.id] if material_record is not None else []
        if existing_workflow is not None and history.persistence_status == "pending":
            input_payload = dict(existing_workflow.input_payload or {})
            input_payload["materialIds"] = _unique_strings(
                [*(input_payload.get("materialIds") or []), *material_ids]
            )
            existing_workflow.input_payload = input_payload
            summary = AssetPersistenceSummary(
                job_id=existing_workflow.id,
                history_id=history.id,
                status="pending",
            )
            self._set_creation_persistence_state(creation, summary)
            return summary, False

        if existing_workflow is not None and history.persistence_status == "completed":
            creation.assets = _apply_url_map(list(creation.assets or []), history.media_url_map or {})
            if material_record is not None:
                material_record.assets = _apply_url_map(list(material_record.assets or []), history.media_url_map or {})
            summary = AssetPersistenceSummary(
                job_id=existing_workflow.id,
                history_id=history.id,
                status="completed",
            )
            self._set_creation_persistence_state(creation, summary)
            return summary, False

        now = datetime.now(UTC)
        workflow_id = f"wf_{uuid4().hex}"
        workflow = WorkflowRecord(
            id=workflow_id,
            account_id=account_id,
            user_id=user_id,
            type="asset_persistence",
            status="pending",
            progress=0,
            current_stage="pending",
            creation_id=creation.id,
            input_payload={"historyId": history.id, "materialIds": material_ids},
            result_payload={},
            error="",
            created_at=now,
            updated_at=now,
        )
        self.session.add(workflow)
        history.persistence_status = "pending"
        history.persistence_job_id = workflow_id
        history.persistence_error = ""
        summary = AssetPersistenceSummary(
            job_id=workflow_id,
            history_id=history.id,
            status="pending",
        )
        self._set_creation_persistence_state(creation, summary)
        return summary, True

    @staticmethod
    def _set_creation_persistence_state(
        creation: ContentCreationRecord,
        summary: AssetPersistenceSummary,
    ) -> None:
        state = dict(creation.creation_state or {})
        state["assetPersistence"] = {
            "jobId": summary.job_id,
            "historyId": summary.history_id,
            "status": summary.status,
            "error": summary.error,
            "updatedAt": datetime.now(UTC).isoformat(),
        }
        creation.creation_state = state


def _history_assets(history: ExtractHistoryRecord) -> list[dict[str, object]]:
    return [dict(item) for item in [*(history.images or []), *(history.videos or [])]]


def _merge_assets(
    existing: list[dict[str, object]],
    extracted: list[dict[str, object]],
) -> list[dict[str, object]]:
    merged: list[dict[str, object]] = []
    seen: set[str] = set()
    for item in [*existing, *extracted]:
        key = str(item.get("sourceUrl") or item.get("url") or "").strip()
        if key and key in seen:
            continue
        if key:
            seen.add(key)
        merged.append(dict(item))
    return merged


def _apply_url_map(
    assets: list[dict[str, object]],
    url_map: dict[str, str],
) -> list[dict[str, object]]:
    updated: list[dict[str, object]] = []
    for item in assets:
        next_item = dict(item)
        source_url = str(next_item.get("sourceUrl") or "")
        current_url = str(next_item.get("url") or "")
        next_item["url"] = url_map.get(source_url) or url_map.get(current_url) or current_url
        if next_item["url"] != current_url:
            next_item["storageStatus"] = "persisted"
        updated.append(next_item)
    return updated


def _history_from_reference(
    *,
    user_id: str,
    account_id: str,
    creation_id: str,
    reference: dict[str, Any],
) -> ExtractHistoryRecord:
    url = str(reference.get("url") or "").strip()
    if not url:
        raise CreationSaveError("current link reference URL is required")
    return ExtractHistoryRecord(
        id=f"eh_{uuid4().hex}",
        user_id=user_id,
        account_id=account_id,
        creation_id=creation_id,
        url=url,
        resolved_url=str(reference.get("resolvedUrl") or url),
        platform=str(reference.get("platform") or "unknown"),
        content_type=str(reference.get("type") or "unknown"),
        title=str(reference.get("title") or ""),
        description=str(reference.get("description") or ""),
        hashtags=list(reference.get("hashtags") or []),
        images=[dict(item) for item in reference.get("images") or [] if isinstance(item, dict)],
        videos=[dict(item) for item in reference.get("videos") or [] if isinstance(item, dict)],
        cover=str(reference.get("cover") or ""),
        raw=dict(reference.get("raw") or {}),
        persistence_status="external",
        persistence_error="",
        media_url_map={},
        created_at=datetime.now(UTC),
    )


def _material_from_record(record: MaterialRecord) -> Material:
    return Material(
        id=record.id,
        name=record.name,
        type=record.material_type,
        tags=list(record.tags or []),
        date=record.material_date,
        thumb=record.thumb,
        assets=list(record.assets or []),
    )


def _unique_strings(values: list[Any]) -> list[str]:
    result: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if text and text not in result:
            result.append(text)
    return result
