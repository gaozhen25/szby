"""WorkflowStore — persistence layer for workflows.

Every public method opens a short-lived SQLAlchemy session, performs its
work, and closes the session immediately.  This guarantees that database
connections are never held idle during AI calls.
"""

from datetime import UTC, datetime
from typing import Any, Callable
from uuid import uuid4

from sqlalchemy import delete, select, update
from sqlalchemy.orm import selectinload

from app.core.database import SessionLocal
from app.core.logging import get_logger
from app.db.models import (
    AccountRecord,
    ContentCreationRecord,
    ExtractHistoryRecord,
    FavoriteTopicRecord,
    GenerationAssetRecord,
    KnowledgeBaseRecord,
    MaterialRecord,
    ReportRecord,
    TopicRecord,
    WorkflowRecord,
    WorkflowStepRecord,
)
from app.services.extract_service.asset_persistence import (
    AssetPersistenceResult,
    ExtractHistorySnapshot,
)
from app.services.db_service import DBService
from app.services.account_report.workflows.types import ACCOUNT_REPORT_WORKFLOW_TYPES
from app.services.workflow.topic_report_context import build_topic_report_context
from app.services.topic_repository import find_topic_snapshot

logger = get_logger(__name__)

def replace_exact_urls(value: Any, url_map: dict[str, str]) -> Any:
    if isinstance(value, str):
        return url_map.get(value, value)
    if isinstance(value, list):
        return [replace_exact_urls(item, url_map) for item in value]
    if isinstance(value, dict):
        return {key: replace_exact_urls(item, url_map) for key, item in value.items()}
    return value


def merge_persisted_assets(
    existing: list[dict[str, Any]],
    persisted: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    by_source = {
        str(item.get("sourceUrl") or ""): dict(item)
        for item in persisted
        if str(item.get("sourceUrl") or "")
    }
    merged: list[dict[str, Any]] = []
    used_sources: set[str] = set()
    for item in existing:
        current = dict(item)
        source_url = str(current.get("sourceUrl") or "")
        replacement = by_source.get(source_url)
        if replacement is None:
            merged.append(current)
            continue
        current.update(replacement)
        merged.append(current)
        used_sources.add(source_url)
    for item in persisted:
        source_url = str(item.get("sourceUrl") or "")
        if source_url not in used_sources:
            merged.append(dict(item))
    return merged


def _account_context(account: AccountRecord) -> dict[str, Any]:
    return {
        "id": account.id,
        "userId": account.user_id,
        "name": account.name,
        "description": account.description,
        "purpose": account.purpose,
        "type": account.account_type,
        "industry": account.industry,
        "productService": account.product_service,
        "targetCity": account.target_city,
        "targetAudience": account.target_audience,
        "conversionGoal": account.conversion_goal,
        "platform": account.platform,
        "platforms": list(account.platforms or [account.platform]),
    }


def _enabled_knowledge_context(knowledge: KnowledgeBaseRecord | None) -> tuple[bool, str]:
    if knowledge is None:
        return False, ""

    enabled = dict(knowledge.enabled_fields or {})
    field_map = [
        ("productName", "产品", knowledge.product_name, True),
        ("productIntro", "产品介绍", knowledge.product_intro, enabled.get("productIntro", True)),
        ("brandStory", "品牌故事", knowledge.brand_story, enabled.get("brandStory", True)),
        ("price", "价格", knowledge.price, enabled.get("price", True)),
        ("logoUrl", "Logo", knowledge.logo_url, enabled.get("logoUrl", True)),
        (
            "imageMaterials",
            "图片素材",
            "、".join(str(item).strip() for item in (knowledge.image_materials or []) if str(item).strip()),
            enabled.get("imageMaterials", True),
        ),
        ("websiteUrl", "官网", knowledge.website_url, enabled.get("websiteUrl", True)),
        ("contactInfo", "联系方式", knowledge.contact_info, enabled.get("contactInfo", True)),
    ]
    parts = [
        (label, str(value or "").strip())
        for _key, label, value, is_enabled in field_map
        if is_enabled and str(value or "").strip()
    ]
    return bool(parts), "\n".join(f"{label}: {value}" for label, value in parts)


def _account_report_knowledge_context(
    knowledge: KnowledgeBaseRecord | None,
) -> tuple[bool, str]:
    """只返回账号策略分析需要的知识库文本，不包含联系方式或素材 URL。"""

    if knowledge is None:
        return False, ""

    enabled = dict(knowledge.enabled_fields or {})
    field_map = [
        ("产品", knowledge.product_name, True),
        ("产品介绍", knowledge.product_intro, enabled.get("productIntro", True)),
        ("品牌故事", knowledge.brand_story, enabled.get("brandStory", True)),
        ("价格", knowledge.price, enabled.get("price", True)),
    ]
    parts = [
        (label, str(value or "").strip())
        for label, value, is_enabled in field_map
        if is_enabled and str(value or "").strip()
    ]
    return bool(parts), "\n".join(f"{label}: {value}" for label, value in parts)


class WorkflowStore:
    """Stateless persistence helper.

    Does NOT hold a session.  Each call opens a fresh session via
    ``SessionLocal``, commits, and closes.
    """

    def __init__(self, session_factory: Callable[[], Any] = SessionLocal) -> None:
        self.session_factory = session_factory

    def replace_account_report(self, user_id: str, account_id: str, payload: dict[str, Any]) -> Any:
        """在短生命周期 session 中委托统一的报告替换契约。"""
        with self.session_factory() as session:
            return DBService(session).replace_structured_report(user_id, account_id, payload)

    def update_account_report_sections(
        self,
        user_id: str,
        account_id: str,
        payload: dict[str, Any],
    ) -> Any:
        """只合并本次生成的板块，保留报告中的其他已发布板块。"""
        with self.session_factory() as session:
            return DBService(session).update_structured_report_sections(
                user_id,
                account_id,
                payload,
            )

    def account_report_context(self, workflow_id: str) -> dict[str, Any]:
        """读取账号报告所需的非敏感上下文，不返回任何运行凭证。"""
        with self.session_factory() as session:
            workflow = session.get(WorkflowRecord, workflow_id)
            if (
                workflow is None
                or workflow.type not in ACCOUNT_REPORT_WORKFLOW_TYPES
                or not workflow.account_id
            ):
                raise ValueError("账号报告 workflow 不存在")
            account = session.get(AccountRecord, workflow.account_id)
            if account is None or account.user_id != workflow.user_id or account.status != "active":
                raise ValueError("账号不可用")
            knowledge = None
            if account.knowledge_base_id:
                candidate = session.get(KnowledgeBaseRecord, account.knowledge_base_id)
                if candidate is not None and candidate.user_id == workflow.user_id and candidate.status == "active":
                    knowledge = candidate
            knowledge_enabled, knowledge_context = _account_report_knowledge_context(
                knowledge
            )
            report = session.get(ReportRecord, workflow.account_id)
            source_meta = (
                dict(getattr(report, "source_meta", None) or {})
                if report is not None
                else {}
            )
            similar_target_fans_wan = source_meta.get("similarTargetFansWan")
            report_keywords = [
                str(item or "").strip()
                for item in list(source_meta.get("keywords") or [])
                if str(item or "").strip()
            ]
            previous_hot_contents = []
            if report is not None:
                for item in list(getattr(report, "hot_contents", None) or []):
                    if not isinstance(item, dict):
                        continue
                    platform = str(item.get("platform") or "").strip()
                    content_id = str(
                        item.get("contentId") or item.get("content_id") or ""
                    ).strip()
                    if platform and content_id:
                        previous_hot_contents.append(
                            {"platform": platform, "contentId": content_id}
                        )
                for item in list(source_meta.get("hotContentsShownKeys") or []):
                    if not isinstance(item, dict):
                        continue
                    platform = str(item.get("platform") or "").strip()
                    content_id = str(
                        item.get("contentId") or item.get("content_id") or ""
                    ).strip()
                    if platform and content_id:
                        previous_hot_contents.append(
                            {"platform": platform, "contentId": content_id}
                        )
            # 换一批爆款时，同时避开选题中心已绑定的原文，避免两边内容撞车
            if report is not None and workflow.account_id:
                try:
                    topic_rows = list(
                        session.scalars(
                            select(TopicRecord)
                            .where(TopicRecord.account_id == workflow.account_id)
                            .order_by(TopicRecord.sort_order, TopicRecord.id)
                        ).all()
                    )
                except AttributeError:
                    topic_rows = []
                for topic in topic_rows:
                    note = dict(getattr(topic, "reference_note", None) or {})
                    platform = str(note.get("platform") or "").strip()
                    content_id = str(
                        note.get("contentId") or note.get("content_id") or ""
                    ).strip()
                    if platform and content_id:
                        previous_hot_contents.append(
                            {"platform": platform, "contentId": content_id}
                        )
            hot_contents_candidate_pool = [
                item
                for item in list(source_meta.get("hotContentsCandidatePool") or [])
                if isinstance(item, dict)
            ]
            try:
                hot_contents_search_page = max(
                    2, int(source_meta.get("hotContentsSearchPage") or 2)
                )
            except (TypeError, ValueError):
                hot_contents_search_page = 2
            return {
                "account": _account_context(account),
                "knowledgeEnabled": knowledge_enabled,
                "knowledgeContext": knowledge_context,
                "accountLinks": dict(account.account_links or {}),
                "similarTargetFansWan": similar_target_fans_wan,
                "benchmarkAccounts": {},
                "reportKeywords": report_keywords,
                "previousHotContents": previous_hot_contents,
                "hotContentsCandidatePool": hot_contents_candidate_pool,
                "hotContentsSearchPage": hot_contents_search_page,
                "referenceComments": (
                    (workflow.input_payload or {}).get("referenceComments") is True
                ),
                "sectionKey": str(
                    (workflow.input_payload or {}).get("sectionKey") or ""
                ).strip(),
            }

    # ------------------------------------------------------------------
    # workflow record status transitions
    # ------------------------------------------------------------------

    def create_workflow(self, record: WorkflowRecord) -> None:
        """Persist a new workflow record (called by the route layer before submit)."""
        with self.session_factory() as s:
            s.add(record)
            s.commit()

    def mark_running(self, workflow_id: str, record_class: type[WorkflowRecord] = WorkflowRecord) -> None:
        with self.session_factory() as s:
            rec = s.get(record_class, workflow_id)
            if rec is None:
                logger.warning("mark_running: record not found workflow_id=%s", workflow_id)
                return
            rec.status = "running"
            rec.error = ""
            rec.progress = max(int(getattr(rec, "progress", 0) or 0), 0)
            if not getattr(rec, "current_stage", ""):
                rec.current_stage = "running"
            rec.updated_at = datetime.now(UTC)
            s.commit()

    def mark_completed(
        self,
        workflow_id: str,
        *,
        result: dict[str, Any] | None = None,
        record_class: type[WorkflowRecord] = WorkflowRecord,
    ) -> None:
        with self.session_factory() as s:
            rec = s.get(record_class, workflow_id)
            if rec is None:
                logger.warning("mark_completed: record not found workflow_id=%s", workflow_id)
                return
            rec.status = "completed"
            rec.progress = 100
            rec.current_stage = "completed"
            rec.error = ""
            if result is not None:
                existing = dict(getattr(rec, "result_payload", {}) or {})
                existing.update(result)
                rec.result_payload = existing
            rec.updated_at = datetime.now(UTC)
            s.commit()

    def mark_failed(
        self,
        workflow_id: str,
        error: str,
        *,
        record_class: type[WorkflowRecord] = WorkflowRecord,
    ) -> None:
        with self.session_factory() as s:
            rec = s.get(record_class, workflow_id)
            if rec is None:
                logger.warning("mark_failed: record not found workflow_id=%s", workflow_id)
                return
            rec.status = "failed"
            rec.error = error
            rec.current_stage = getattr(rec, "current_stage", "") or "failed"
            rec.updated_at = datetime.now(UTC)
            s.commit()

    def mark_cancelled(
        self,
        workflow_id: str,
        *,
        record_class: type[WorkflowRecord] = WorkflowRecord,
    ) -> None:
        with self.session_factory() as s:
            rec = s.get(record_class, workflow_id)
            if rec is None:
                return
            rec.status = "cancelled"
            rec.current_stage = "cancelled"
            rec.updated_at = datetime.now(UTC)
            s.commit()

    def update_progress(
        self,
        workflow_id: str,
        *,
        progress: int,
        current_stage: str | None = None,
        prompt: str | None = None,
        result_payload: dict[str, Any] | None = None,
        record_class: type[WorkflowRecord] = WorkflowRecord,
    ) -> None:
        with self.session_factory() as s:
            rec = s.get(record_class, workflow_id)
            if rec is None:
                return
            current = int(getattr(rec, "progress", 0) or 0)
            rec.progress = min(max(max(current, int(progress)), 0), 100)
            if current_stage is not None:
                rec.current_stage = current_stage
            if prompt is not None:
                rec.prompt = prompt
            if result_payload is not None:
                existing = dict(getattr(rec, "result_payload", {}) or {})
                existing.update(result_payload)
                rec.result_payload = existing
            rec.updated_at = datetime.now(UTC)
            s.commit()

    def update_video_url(self, workflow_id: str, video_url: str) -> None:
        with self.session_factory() as session:
            workflow = session.get(WorkflowRecord, workflow_id)
            if workflow is None or workflow.type != "video_analysis":
                raise ValueError("视频解析 workflow 不存在")
            workflow.video_url = str(video_url or "").strip()
            workflow.updated_at = datetime.now(UTC)
            session.commit()

    def get_workflow(
        self,
        workflow_id: str,
        *,
        record_class: type[WorkflowRecord] = WorkflowRecord,
    ) -> Any:
        """Load a workflow record with assets and steps eager-loaded.

        The session is closed after this call returns, so all relationships
        must be populated eagerly — lazy-loading after detach will fail.
        """
        with self.session_factory() as s:
            return s.get(
                record_class,
                workflow_id,
                options=[selectinload(WorkflowRecord.assets), selectinload(WorkflowRecord.steps)],
            )

    def load_asset_persistence_context(self, workflow_id: str) -> ExtractHistorySnapshot:
        with self.session_factory() as session:
            workflow = session.get(WorkflowRecord, workflow_id)
            if workflow is None or workflow.type != "asset_persistence":
                raise ValueError("asset persistence workflow was not found")
            history_id = str((workflow.input_payload or {}).get("historyId") or "").strip()
            history = session.scalar(
                select(ExtractHistoryRecord).where(
                    ExtractHistoryRecord.id == history_id,
                    ExtractHistoryRecord.user_id == workflow.user_id,
                    ExtractHistoryRecord.account_id == workflow.account_id,
                )
            )
            if history is None:
                raise ValueError("extract history is not available")
            return ExtractHistorySnapshot(
                id=history.id,
                account_id=str(history.account_id or ""),
                source_url=history.url,
                platform=history.platform,
                images=list(history.images or []),
                videos=list(history.videos or []),
                existing_url_map=dict(history.media_url_map or {}),
            )

    def apply_asset_persistence_result(
        self,
        workflow_id: str,
        result: AssetPersistenceResult,
    ) -> None:
        now = datetime.now(UTC)
        with self.session_factory() as session:
            try:
                workflow = session.get(WorkflowRecord, workflow_id)
                if workflow is None or workflow.type != "asset_persistence":
                    raise ValueError("asset persistence workflow was not found")
                input_payload = dict(workflow.input_payload or {})
                history_id = str(input_payload.get("historyId") or "").strip()
                history = session.scalar(
                    select(ExtractHistoryRecord).where(
                        ExtractHistoryRecord.id == history_id,
                        ExtractHistoryRecord.user_id == workflow.user_id,
                        ExtractHistoryRecord.account_id == workflow.account_id,
                        ExtractHistoryRecord.persistence_job_id == workflow.id,
                    )
                )
                if history is None:
                    raise ValueError("extract history is not available")

                images = [dict(item) for item in result.assets if item.get("kind") == "image"]
                videos = [dict(item) for item in result.assets if item.get("kind") == "video"]
                history.images = images
                history.videos = videos
                history.cover = str(images[0].get("url") or "") if images else ""
                history.persistence_status = result.status
                history.persistence_error = result.error
                history.media_url_map = dict(result.url_map)
                history.persisted_at = now

                creation = session.scalar(
                    select(ContentCreationRecord).where(
                        ContentCreationRecord.id == workflow.creation_id,
                        ContentCreationRecord.user_id == workflow.user_id,
                        ContentCreationRecord.account_id == workflow.account_id,
                    )
                )
                if creation is not None:
                    creation.assets = merge_persisted_assets(
                        list(creation.assets or []),
                        [dict(item) for item in result.assets],
                    )
                    creation.cover = replace_exact_urls(dict(creation.cover or {}), result.url_map)
                    creation_state = replace_exact_urls(dict(creation.creation_state or {}), result.url_map)
                    link_reference = dict(creation_state.get("linkReference") or {})
                    link_reference["images"] = images
                    link_reference["videos"] = videos
                    link_reference["cover"] = history.cover
                    creation_state["linkReference"] = link_reference
                    creation_state["assetPersistence"] = {
                        "jobId": workflow.id,
                        "historyId": history.id,
                        "status": result.status,
                        "error": result.error,
                        "updatedAt": now.isoformat(),
                    }
                    creation.creation_state = creation_state
                    creation.updated_at = now

                material_ids = [str(item) for item in input_payload.get("materialIds") or [] if str(item)]
                if material_ids:
                    materials = session.scalars(
                        select(MaterialRecord).where(
                            MaterialRecord.id.in_(material_ids),
                            MaterialRecord.account_id == workflow.account_id,
                        )
                    ).all()
                    for material in materials:
                        material.assets = [dict(item) for item in result.assets]

                video_workflows = session.scalars(
                    select(WorkflowRecord).where(
                        WorkflowRecord.creation_id == workflow.creation_id,
                        WorkflowRecord.user_id == workflow.user_id,
                        WorkflowRecord.account_id == workflow.account_id,
                        WorkflowRecord.type == "video_analysis",
                    )
                ).all()
                for video_workflow in video_workflows:
                    video_workflow.video_url = result.url_map.get(video_workflow.video_url, video_workflow.video_url)
                    video_workflow.cover_url = result.url_map.get(video_workflow.cover_url, video_workflow.cover_url)
                    video_workflow.input_payload = replace_exact_urls(
                        dict(video_workflow.input_payload or {}),
                        result.url_map,
                    )
                    video_workflow.updated_at = now
                session.commit()
            except Exception:
                session.rollback()
                raise

    # ------------------------------------------------------------------
    # workflow step records
    # ------------------------------------------------------------------

    def create_step(
        self,
        *,
        workflow_id: str,
        user_id: str,
        account_id: str | None,
        step_type: str,
        input_payload: dict[str, Any],
        sort_order: int = 0,
        group_key: str = "",
        asset_id: str | None = None,
    ) -> str:
        """Create a pending step record.  Returns the step id."""
        now = datetime.now(UTC)
        step_id = f"wfs_{uuid4().hex}"
        with self.session_factory() as s:
            rec = WorkflowStepRecord(
                id=step_id,
                workflow_id=workflow_id,
                user_id=user_id,
                account_id=account_id,
                asset_id=asset_id,
                type=step_type,
                status="pending",
                progress=0,
                sort_order=sort_order,
                group_key=group_key or step_type,
                input_payload=input_payload,
                result_payload={},
                error="",
                created_at=now,
                updated_at=now,
            )
            s.add(rec)
            s.commit()
        return step_id

    def mark_step_running(self, step_id: str) -> None:
        with self.session_factory() as s:
            s.execute(
                update(WorkflowStepRecord)
                .where(WorkflowStepRecord.id == step_id)
                .values(status="running", started_at=datetime.now(UTC), updated_at=datetime.now(UTC))
            )
            s.commit()

    def mark_step_completed(self, step_id: str, result_payload: dict[str, Any]) -> None:
        with self.session_factory() as s:
            s.execute(
                update(WorkflowStepRecord)
                .where(WorkflowStepRecord.id == step_id)
                .values(
                    status="completed",
                    progress=100,
                    error="",
                    result_payload=result_payload,
                    completed_at=datetime.now(UTC),
                    updated_at=datetime.now(UTC),
                )
            )
            s.commit()

    def mark_step_failed(self, step_id: str, error: str) -> None:
        with self.session_factory() as s:
            step = s.get(WorkflowStepRecord, step_id)
            if step is not None:
                logger.error(
                    "workflow step failed workflow_id=%s step_id=%s step_type=%s error=%s",
                    step.workflow_id,
                    step_id,
                    step.type,
                    error,
                )
            s.execute(
                update(WorkflowStepRecord)
                .where(WorkflowStepRecord.id == step_id)
                .values(
                    status="failed",
                    progress=100,
                    error=error,
                    result_payload={},
                    completed_at=datetime.now(UTC),
                    updated_at=datetime.now(UTC),
                )
            )
            s.commit()

    def failed_step_asset_ids(self, workflow_id: str, step_type: str) -> set[str | None]:
        with self.session_factory() as s:
            rows = (
                s.query(WorkflowStepRecord)
                .filter(
                    WorkflowStepRecord.workflow_id == workflow_id,
                    WorkflowStepRecord.type == step_type,
                    WorkflowStepRecord.status == "failed",
                )
                .all()
            )
            return {row.asset_id for row in rows}

    # ------------------------------------------------------------------
    # asset helpers (for generation workflows)
    # ------------------------------------------------------------------

    def add_asset(self, record: GenerationAssetRecord) -> None:
        """Persist a new asset.  The record is detached after this returns —
        callers must not access relationship-lazy attributes afterwards."""
        with self.session_factory() as s:
            try:
                s.add(record)
                s.commit()
            except Exception:
                s.rollback()
                raise

    def delete_assets(self, asset_ids: list[str]) -> None:
        if not asset_ids:
            return
        with self.session_factory() as s:
            (
                s.query(GenerationAssetRecord)
                .filter(GenerationAssetRecord.id.in_(asset_ids))
                .delete(synchronize_session=False)
            )
            s.commit()

    def mark_asset_completed(self, asset_id: str, analysis: str, *, prompt: str = "") -> None:
        with self.session_factory() as s:
            try:
                asset = s.get(GenerationAssetRecord, asset_id)
                if asset is None:
                    return
                asset.analysis = analysis
                asset.status = "completed"
                asset.error = ""
                meta = dict(asset.meta or {})
                if prompt:
                    meta["prompt"] = prompt
                asset.meta = meta
                s.commit()
            except Exception:
                s.rollback()
                raise

    def mark_asset_failed(self, asset_id: str, error: str) -> None:
        with self.session_factory() as s:
            try:
                asset = s.get(GenerationAssetRecord, asset_id)
                if asset is None:
                    return
                asset.status = "failed"
                asset.error = error
                s.commit()
            except Exception:
                s.rollback()
                raise

    # ------------------------------------------------------------------
    # cross-record queries
    # ------------------------------------------------------------------

    def account_knowledge_context(self, account_id: str | None) -> str:
        if not account_id:
            return ""
        with self.session_factory() as s:
            account = s.get(AccountRecord, account_id)
            if account is None or not account.knowledge_base_id:
                return ""
            knowledge = s.get(KnowledgeBaseRecord, account.knowledge_base_id)
            if knowledge is None:
                return ""
            parts = [
                ("产品", knowledge.product_name),
                ("产品介绍", knowledge.product_intro),
                ("品牌故事", knowledge.brand_story),
                ("价格", knowledge.price),
                ("官网", knowledge.website_url),
            ]
            return "\n".join(f"{label}: {value}" for label, value in parts if str(value or "").strip())

    def topic_recommendation_context(self, account_id: str | None) -> dict[str, Any]:
        if not account_id:
            return {}
        with self.session_factory() as s:
            account = s.get(AccountRecord, account_id)
            if account is None:
                return {}
            knowledge = s.get(KnowledgeBaseRecord, account.knowledge_base_id) if account.knowledge_base_id else None
            knowledge_base_used, knowledge_context = _enabled_knowledge_context(knowledge)
            existing_topics = s.scalars(
                select(TopicRecord)
                .where(TopicRecord.account_id == account_id)
                .order_by(TopicRecord.sort_order, TopicRecord.id)
            ).all()
            favorite_titles = s.scalars(
                select(FavoriteTopicRecord.title)
                .where(FavoriteTopicRecord.account_id == account_id)
                .order_by(FavoriteTopicRecord.created_at.desc())
                .limit(100)
            ).all()
            report = s.scalar(
                select(ReportRecord)
                .where(
                    ReportRecord.account_id == account.id,
                    ReportRecord.report_version > 0,
                    ReportRecord.generated_at.is_not(None),
                )
                .order_by(ReportRecord.generated_at.desc())
            )
            return {
                "account": _account_context(account),
                "knowledgeBaseUsed": knowledge_base_used,
                "knowledgeContext": knowledge_context,
                "existingTopicTitles": list(dict.fromkeys(
                    [topic.title for topic in existing_topics] + list(favorite_titles)
                )),
                "accountReport": build_topic_report_context(report),
            }

    def video_script_context(self, user_id: str, account_id: str, topic_id: str) -> dict[str, Any]:
        with self.session_factory() as session:
            account = session.scalar(
                select(AccountRecord).where(
                    AccountRecord.id == account_id,
                    AccountRecord.user_id == user_id,
                    AccountRecord.status == "active",
                )
            )
            topic = find_topic_snapshot(
                session,
                account_id=account_id,
                topic_id=topic_id,
                content_type="video",
            )
            if account is None or topic is None:
                raise ValueError("video topic is not available")
            knowledge = (
                session.get(KnowledgeBaseRecord, account.knowledge_base_id)
                if account.knowledge_base_id
                else None
            )
            knowledge_base_used, knowledge_context = _enabled_knowledge_context(knowledge)
            return {
                "account": _account_context(account),
                "knowledgeContext": knowledge_context,
                "knowledgeBaseUsed": knowledge_base_used,
                "topic": {
                    "id": topic_id,
                    "title": topic.title,
                    "category": topic.category,
                    "reason": topic.reason,
                    "platforms": list(topic.platforms or []),
                },
            }

    def image_prompt_plan_context(self, user_id: str, account_id: str, topic_id: str) -> dict[str, Any]:
        """Load authoritative image-topic context in one short-lived session."""

        with self.session_factory() as session:
            account = session.scalar(
                select(AccountRecord).where(
                    AccountRecord.id == account_id,
                    AccountRecord.user_id == user_id,
                    AccountRecord.status == "active",
                )
            )
            topic = find_topic_snapshot(
                session,
                account_id=account_id,
                topic_id=topic_id,
                content_type="image",
            )
            if account is None or topic is None:
                raise ValueError("image topic is not available")

            knowledge = (
                session.get(KnowledgeBaseRecord, account.knowledge_base_id)
                if account.knowledge_base_id
                else None
            )
            knowledge_base_used, knowledge_context = _enabled_knowledge_context(knowledge)
            return {
                "account": _account_context(account),
                "knowledgeContext": knowledge_context,
                "knowledgeBaseUsed": knowledge_base_used,
                "topic": {
                    "id": topic_id,
                    "title": topic.title,
                    "category": topic.category,
                    "reason": topic.reason,
                    "platforms": list(topic.platforms or []),
                    "referenceNote": dict(topic.reference_note or {}),
                },
            }

    def update_report_topic_reference_pool(
        self,
        account_id: str,
        pool: list[dict[str, Any]],
    ) -> None:
        """换一批选题后，把新搜到的原文池写回报告 source_meta。"""

        with self.session_factory() as s:
            try:
                report = s.get(ReportRecord, account_id)
                if report is None:
                    return
                if int(getattr(report, "report_version", 0) or 0) <= 0:
                    return
                if getattr(report, "generated_at", None) is None:
                    return
                source_meta = dict(report.source_meta or {})
                source_meta["topicReferencePool"] = list(pool or [])
                report.source_meta = source_meta
                s.add(report)
                s.commit()
            except Exception:
                s.rollback()
                raise

    def replace_account_topics(
        self,
        *,
        workflow_id: str,
        user_id: str,
        account_id: str,
        topics: list[dict[str, Any]],
    ) -> None:
        now = datetime.now(UTC)
        with self.session_factory() as s:
            try:
                account = s.scalar(
                    select(AccountRecord).where(
                        AccountRecord.id == account_id,
                        AccountRecord.user_id == user_id,
                        AccountRecord.status == "active",
                    )
                )
                if account is None:
                    raise ValueError(f"account {account_id} is not available for user {user_id}")
                s.execute(delete(TopicRecord).where(TopicRecord.account_id == account_id))
                for index, topic in enumerate(topics, start=1):
                    s.add(
                        TopicRecord(
                            id=f"{account_id}_t{index}",
                            account_id=account_id,
                            title=str(topic.get("title") or "").strip(),
                            source=str(topic.get("source") or "AI推荐").strip(),
                            category=str(topic.get("category") or "内容种草").strip(),
                            content_type=str(topic.get("contentType") or topic.get("type") or "image").strip(),
                            reason=str(topic.get("reason") or "").strip(),
                            platforms=list(topic.get("platforms") or []),
                            reference_note=dict(topic.get("referenceNote") or {}),
                            sort_order=index,
                            batch_id=workflow_id,
                            created_at=now,
                            updated_at=now,
                        )
                    )
                s.commit()
            except Exception:
                s.rollback()
                raise

    def image_prompts_for_generation_job(
        self,
        record: Any,
        requested_count: int,
        fallback_prompt: str,
    ) -> list[str]:
        source_id = str((record.input_payload or {}).get("sourcePromptWorkflowId") or "").strip()
        if source_id:
            with self.session_factory() as s:
                parent = (
                    s.query(WorkflowRecord)
                    .filter(
                        WorkflowRecord.id == source_id,
                        WorkflowRecord.account_id == record.account_id,
                        WorkflowRecord.user_id == record.user_id,
                        WorkflowRecord.type == "prompt",
                    )
                    .one_or_none()
                )
                if parent is not None and isinstance(parent.result_payload, dict):
                    image_prompts = parent.result_payload.get("imagePrompts")
                    if isinstance(image_prompts, list):
                        prompts = [
                            str(item.get("prompt") if isinstance(item, dict) else item).strip()
                            for item in image_prompts
                        ]
                        prompts = [p for p in prompts if p]
                        if prompts:
                            return prompts[:requested_count]
        return [fallback_prompt for _ in range(requested_count)]

    def fail_unfinished(self) -> dict[str, int]:
        """Mark all pending/running workflows and steps as failed (shutdown hook)."""
        now = datetime.now(UTC)
        counts: dict[str, int] = {}
        with self.session_factory() as s:
            counts["workflows"] = (
                s.query(WorkflowRecord)
                .filter(
                    WorkflowRecord.status.in_(("pending", "running")),
                    WorkflowRecord.type != "digital_human_video",
                )
                .update(
                    {"status": "failed", "error": "backend service stopped before the job completed", "updated_at": now},
                    synchronize_session=False,
                )
            )
            counts["workflow_steps"] = (
                s.query(WorkflowStepRecord)
                .filter(WorkflowStepRecord.status.in_(("pending", "running")))
                .update(
                    {"status": "failed", "error": "backend service stopped before the job completed", "updated_at": now},
                    synchronize_session=False,
                )
            )
            s.commit()
        logger.error("shutdown: marked unfinished workflows as failed counts=%s", counts)
        return counts
