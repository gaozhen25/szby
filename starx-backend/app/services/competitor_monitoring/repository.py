"""竞品监控事务与持久化。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, Callable
from uuid import uuid4

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError

from app.db.models import (
    AccountRecord,
    CompetitorAccountRecord,
    CompetitorSnapshotRecord,
    CompetitorVideoRecord,
    WorkflowRecord,
)

from .models import NormalizedCompetitor, TargetType
from .normalizers import metric_delta, recent_account_videos, serialize_account_video


class CompetitorTargetNotFound(Exception):
    pass


class DuplicateCompetitorTarget(Exception):
    pass


class StaleCompetitorWorkflow(Exception):
    pass


TARGET_CLASSES = {
    "account": CompetitorAccountRecord,
    "video": CompetitorVideoRecord,
}

DUPLICATE_TARGET_CONSTRAINTS = frozenset(
    {
        "uq_competitor_accounts_account_url",
        "uq_competitor_videos_account_url",
    }
)


def _is_duplicate_target_error(exc: IntegrityError) -> bool:
    diagnostic = getattr(exc.orig, "diag", None)
    constraint_name = getattr(diagnostic, "constraint_name", None)
    return constraint_name in DUPLICATE_TARGET_CONSTRAINTS


def _workflow_id() -> str:
    return f"wf_{uuid4().hex}"


def _target_id(target_type: TargetType) -> str:
    return f"{'ca' if target_type == 'account' else 'cv'}_{uuid4().hex}"


def _detached(session, record):
    session.refresh(record)
    if isinstance(record, WorkflowRecord):
        list(record.assets)
        list(record.steps)
    session.expunge(record)
    return record


class CompetitorRepository:
    def __init__(
        self,
        session_factory: Callable[[], Any],
        *,
        next_refresh_at: Callable[[datetime], datetime],
    ) -> None:
        self.session_factory = session_factory
        self._next_refresh_at = next_refresh_at

    @staticmethod
    def _persist_workflow_before_target_reference(session, workflow: WorkflowRecord) -> None:
        """先落库刷新任务，再让监控对象通过外键引用它。"""

        session.add(workflow)
        session.flush()

    @staticmethod
    def _require_account(session, user_id: str, account_id: str) -> AccountRecord:
        account = session.scalar(
            select(AccountRecord).where(
                AccountRecord.id == account_id,
                AccountRecord.user_id == user_id,
                AccountRecord.status == "active",
            )
        )
        if account is None:
            raise CompetitorTargetNotFound("运营账号不存在")
        return account

    def list_targets(self, user_id: str, account_id: str, target_type: TargetType):
        target_class = TARGET_CLASSES[target_type]
        with self.session_factory() as session:
            self._require_account(session, user_id, account_id)
            records = list(
                session.scalars(
                    select(target_class)
                    .where(
                        target_class.user_id == user_id,
                        target_class.account_id == account_id,
                    )
                    .order_by(target_class.created_at.desc(), target_class.id.desc())
                )
            )
            for record in records:
                session.expunge(record)
            return records

    def list_account_content_trends(
        self,
        user_id: str,
        account_id: str,
        target_id: str,
        *,
        days: int,
    ) -> list[dict[str, Any]]:
        cutoff = datetime.now(UTC) - timedelta(days=days)
        with self.session_factory() as session:
            self._require_account(session, user_id, account_id)
            target = session.scalar(
                select(CompetitorAccountRecord).where(
                    CompetitorAccountRecord.id == target_id,
                    CompetitorAccountRecord.user_id == user_id,
                    CompetitorAccountRecord.account_id == account_id,
                )
            )
            if target is None:
                raise CompetitorTargetNotFound("监控账号不存在")
            snapshots = list(
                session.scalars(
                    select(CompetitorSnapshotRecord)
                    .where(
                        CompetitorSnapshotRecord.target_type == "account",
                        CompetitorSnapshotRecord.target_id == target_id,
                        CompetitorSnapshotRecord.captured_at >= cutoff,
                    )
                    .order_by(
                        CompetitorSnapshotRecord.captured_at.asc(),
                        CompetitorSnapshotRecord.id.asc(),
                    )
                )
            )

        trends: dict[str, dict[str, Any]] = {}
        for snapshot in snapshots:
            for item in snapshot.items:
                if not isinstance(item, dict):
                    continue
                identity = str(
                    item.get("platformContentId") or item.get("contentUrl") or ""
                ).strip()
                if not identity:
                    continue
                trend = trends.setdefault(
                    identity,
                    {
                        "platformContentId": str(item.get("platformContentId") or ""),
                        "title": str(item.get("title") or ""),
                        "contentUrl": str(item.get("contentUrl") or ""),
                        "publishedAt": item.get("publishedAt"),
                        "points": [],
                    },
                )
                trend["points"].append(
                    {
                        "capturedAt": snapshot.captured_at,
                        "metrics": dict(item.get("metrics") or {}),
                    }
                )
        return list(trends.values())

    def list_account_metric_trends(
        self,
        user_id: str,
        account_id: str,
        target_id: str,
        *,
        days: int,
    ) -> list[dict[str, Any]]:
        cutoff = datetime.now(UTC) - timedelta(days=days)
        with self.session_factory() as session:
            self._require_account(session, user_id, account_id)
            target_exists = session.scalar(
                select(CompetitorAccountRecord.id).where(
                    CompetitorAccountRecord.id == target_id,
                    CompetitorAccountRecord.user_id == user_id,
                    CompetitorAccountRecord.account_id == account_id,
                )
            )
            if target_exists is None:
                raise CompetitorTargetNotFound("监控账号不存在")
            snapshots = list(
                session.scalars(
                    select(CompetitorSnapshotRecord)
                    .where(
                        CompetitorSnapshotRecord.target_type == "account",
                        CompetitorSnapshotRecord.target_id == target_id,
                        CompetitorSnapshotRecord.captured_at >= cutoff,
                    )
                    .order_by(
                        CompetitorSnapshotRecord.captured_at.asc(),
                        CompetitorSnapshotRecord.id.asc(),
                    )
                )
            )
        return [
            {
                "capturedAt": snapshot.captured_at,
                "metrics": dict(snapshot.metrics),
            }
            for snapshot in snapshots
        ]

    def get_target(
        self, user_id: str, account_id: str, target_type: TargetType, target_id: str
    ):
        target_class = TARGET_CLASSES[target_type]
        with self.session_factory() as session:
            record = session.scalar(
                select(target_class).where(
                    target_class.id == target_id,
                    target_class.user_id == user_id,
                    target_class.account_id == account_id,
                )
            )
            if record is None:
                raise CompetitorTargetNotFound("监控对象不存在")
            session.expunge(record)
            return record

    def add_target(
        self,
        user_id: str,
        account_id: str,
        target_type: TargetType,
        platform: str,
        url: str,
        *,
        sec_user_id: str = "",
    ):
        target_class = TARGET_CLASSES[target_type]
        url_field = "profile_url" if target_type == "account" else "content_url"
        now = datetime.now(UTC)
        identity_fields = (
            {"sec_user_id": sec_user_id} if target_type == "account" else {}
        )
        target = target_class(
            id=_target_id(target_type),
            account_id=account_id,
            user_id=user_id,
            platform=platform,
            **{url_field: url},
            **identity_fields,
            refresh_status="pending",
            next_refresh_at=self._next_refresh_at(now),
            created_at=now,
            updated_at=now,
        )
        workflow = self._new_workflow(target, target_type, "initial", now)
        target.active_workflow_id = workflow.id
        try:
            with self.session_factory() as session:
                self._require_account(session, user_id, account_id)
                duplicate = session.scalar(
                    select(target_class.id).where(
                        target_class.account_id == account_id,
                        getattr(target_class, url_field) == url,
                    )
                )
                if duplicate is not None:
                    raise DuplicateCompetitorTarget("该链接已在监控中")
                self._persist_workflow_before_target_reference(session, workflow)
                session.add(target)
                session.commit()
                return _detached(session, target), _detached(session, workflow)
        except IntegrityError as exc:
            if _is_duplicate_target_error(exc):
                raise DuplicateCompetitorTarget("该链接已在监控中") from None
            raise

    def delete_target(
        self, user_id: str, account_id: str, target_type: TargetType, target_id: str
    ) -> None:
        target_class = TARGET_CLASSES[target_type]
        with self.session_factory() as session:
            target = session.scalar(
                select(target_class).where(
                    target_class.id == target_id,
                    target_class.user_id == user_id,
                    target_class.account_id == account_id,
                )
            )
            if target is None:
                raise CompetitorTargetNotFound("监控对象不存在")
            session.delete(target)
            session.commit()

    def create_refresh(
        self,
        user_id: str,
        account_id: str,
        target_type: TargetType,
        target_id: str,
        trigger: str,
    ) -> tuple[WorkflowRecord, bool]:
        target_class = TARGET_CLASSES[target_type]
        with self.session_factory() as session:
            target = session.scalar(
                select(target_class)
                .where(
                    target_class.id == target_id,
                    target_class.user_id == user_id,
                    target_class.account_id == account_id,
                )
                .with_for_update()
            )
            if target is None:
                raise CompetitorTargetNotFound("监控对象不存在")
            if target.active_workflow_id:
                active = session.get(WorkflowRecord, target.active_workflow_id)
                if active is not None and active.status in {"pending", "running"}:
                    return _detached(session, active), False
                target.active_workflow_id = None

            now = datetime.now(UTC)
            workflow = self._new_workflow(target, target_type, trigger, now)
            self._persist_workflow_before_target_reference(session, workflow)
            target.active_workflow_id = workflow.id
            target.refresh_status = "pending"
            target.refresh_error_code = ""
            target.refresh_error_message = ""
            target.updated_at = now
            session.commit()
            return _detached(session, workflow), True

    @staticmethod
    def _new_workflow(target, target_type: TargetType, trigger: str, now: datetime):
        return WorkflowRecord(
            id=_workflow_id(),
            type="competitor_refresh",
            user_id=target.user_id,
            account_id=target.account_id,
            status="pending",
            progress=0,
            current_stage="pending",
            platform=target.platform,
            source_url=(
                target.profile_url if target_type == "account" else target.content_url
            ),
            input_payload={
                "targetType": target_type,
                "targetId": target.id,
                "trigger": trigger,
            },
            result_payload={},
            created_at=now,
            updated_at=now,
        )

    def complete_refresh(
        self, workflow_id: str, normalized: NormalizedCompetitor
    ):
        now = datetime.now(UTC)
        with self.session_factory() as session:
            workflow = session.get(WorkflowRecord, workflow_id)
            if workflow is None or workflow.type != "competitor_refresh":
                raise StaleCompetitorWorkflow("刷新任务不存在")
            target_type = workflow.input_payload.get("targetType")
            target_id = workflow.input_payload.get("targetId")
            if target_type not in TARGET_CLASSES or not isinstance(target_id, str):
                raise StaleCompetitorWorkflow("刷新任务目标无效")
            target_class = TARGET_CLASSES[target_type]
            target = session.scalar(
                select(target_class).where(target_class.id == target_id).with_for_update()
            )
            if target is None or target.active_workflow_id != workflow_id:
                raise StaleCompetitorWorkflow("刷新任务已过期")

            latest = session.scalar(
                select(CompetitorSnapshotRecord)
                .where(
                    CompetitorSnapshotRecord.target_type == target_type,
                    CompetitorSnapshotRecord.target_id == target_id,
                )
                .order_by(CompetitorSnapshotRecord.captured_at.desc(), CompetitorSnapshotRecord.id.desc())
                .limit(1)
            )
            metrics = dict(normalized.metrics)
            target.delta_metrics = metric_delta(metrics, dict(latest.metrics)) if latest else {}
            if target_type == "account":
                videos = [serialize_account_video(video) for video in normalized.videos]
                recent_videos = [
                    serialize_account_video(video)
                    for video in recent_account_videos(
                        normalized.videos, now - timedelta(days=7)
                    )
                ]
                target.name = normalized.name
                target.bio = normalized.description
                target.avatar_url = normalized.avatar_url
                target.followers = metrics.get("followers")
                target.following = metrics.get("following")
                target.works = metrics.get("works")
                target.liked = metrics.get("liked")
                target.latest_videos = videos
                # 兼容既有 API 字段名；语义改为按作品发布时间筛选的近 7 天作品。
                target.new_videos = recent_videos
                target.video_snapshot_ready = True
            else:
                videos = []
                target.platform_content_id = normalized.platform_content_id
                target.title = normalized.title
                target.description = normalized.description
                target.cover_url = normalized.cover_url
                target.author_name = normalized.author_name
                target.author_profile_url = normalized.author_profile_url
                target.published_at = normalized.published_at
                for field in ("likes", "comments", "shares", "plays", "collects"):
                    setattr(target, field, metrics.get(field))

            target.refresh_status = "succeeded"
            target.refresh_error_code = ""
            target.refresh_error_message = ""
            target.active_workflow_id = None
            target.last_attempted_at = now
            target.last_refreshed_at = now
            target.next_refresh_at = self._next_refresh_at(now)
            target.updated_at = now
            session.add(
                CompetitorSnapshotRecord(
                    target_type=target_type,
                    target_id=target_id,
                    competitor_account_id=target_id if target_type == "account" else None,
                    competitor_video_id=target_id if target_type == "video" else None,
                    workflow_id=workflow_id,
                    metrics=metrics,
                    items=videos,
                    captured_at=now,
                )
            )
            session.commit()
            return _detached(session, target)

    def update_account_profile(
        self, workflow_id: str, normalized: NormalizedCompetitor
    ):
        """先保存账号资料，作品采集仍在后台继续。

        这里不结束 workflow、不清空 active_workflow_id，也不写快照。最终快照仍由
        complete_refresh 原子写入，避免半成品进入趋势统计。
        """

        now = datetime.now(UTC)
        with self.session_factory() as session:
            workflow = session.get(WorkflowRecord, workflow_id)
            if workflow is None or workflow.type != "competitor_refresh":
                raise StaleCompetitorWorkflow("刷新任务不存在")
            if workflow.input_payload.get("targetType") != "account":
                raise StaleCompetitorWorkflow("刷新任务目标无效")
            target_id = workflow.input_payload.get("targetId")
            if not isinstance(target_id, str):
                raise StaleCompetitorWorkflow("刷新任务目标无效")
            target = session.scalar(
                select(CompetitorAccountRecord)
                .where(CompetitorAccountRecord.id == target_id)
                .with_for_update()
            )
            if target is None or target.active_workflow_id != workflow_id:
                raise StaleCompetitorWorkflow("刷新任务已过期")

            latest = session.scalar(
                select(CompetitorSnapshotRecord)
                .where(
                    CompetitorSnapshotRecord.target_type == "account",
                    CompetitorSnapshotRecord.target_id == target_id,
                )
                .order_by(
                    CompetitorSnapshotRecord.captured_at.desc(),
                    CompetitorSnapshotRecord.id.desc(),
                )
                .limit(1)
            )
            metrics = dict(normalized.metrics)
            target.name = normalized.name
            target.bio = normalized.description
            target.avatar_url = normalized.avatar_url
            target.followers = metrics.get("followers")
            target.following = metrics.get("following")
            target.works = metrics.get("works")
            target.liked = metrics.get("liked")
            target.delta_metrics = (
                metric_delta(metrics, dict(latest.metrics)) if latest else {}
            )
            target.refresh_status = "running"
            target.refresh_error_code = ""
            target.refresh_error_message = ""
            target.updated_at = now
            session.commit()
            return _detached(session, target)

    def refresh_context(self, workflow_id: str) -> dict[str, str]:
        now = datetime.now(UTC)
        with self.session_factory() as session:
            workflow = session.get(WorkflowRecord, workflow_id)
            if workflow is None or workflow.type != "competitor_refresh":
                raise StaleCompetitorWorkflow("刷新任务不存在")
            target_type = workflow.input_payload.get("targetType")
            target_id = workflow.input_payload.get("targetId")
            target_class = TARGET_CLASSES.get(target_type)
            if target_class is None or not isinstance(target_id, str):
                raise StaleCompetitorWorkflow("刷新任务目标无效")
            target = session.get(target_class, target_id)
            if target is None or target.active_workflow_id != workflow_id:
                raise StaleCompetitorWorkflow("刷新任务已过期")
            target.refresh_status = "running"
            target.last_attempted_at = now
            target.updated_at = now
            session.commit()
            return {
                "targetType": target_type,
                "targetId": target_id,
                "platform": target.platform,
                "secUserId": (
                    target.sec_user_id if target_type == "account" else ""
                ),
                "url": (
                    target.profile_url
                    if target_type == "account"
                    else target.content_url
                ),
            }

    def fail_refresh(self, workflow_id: str, code: str, message: str) -> None:
        now = datetime.now(UTC)
        with self.session_factory() as session:
            workflow = session.get(WorkflowRecord, workflow_id)
            if workflow is None or workflow.type != "competitor_refresh":
                return
            target_type = workflow.input_payload.get("targetType")
            target_id = workflow.input_payload.get("targetId")
            target_class = TARGET_CLASSES.get(target_type)
            if target_class is None or not isinstance(target_id, str):
                return
            target = session.get(target_class, target_id)
            if target is None or target.active_workflow_id != workflow_id:
                return
            target.refresh_status = "failed"
            target.refresh_error_code = code[:64]
            target.refresh_error_message = message
            target.active_workflow_id = None
            target.last_attempted_at = now
            target.next_refresh_at = self._next_refresh_at(now)
            target.updated_at = now
            session.commit()

    def get_workflow(
        self, user_id: str, account_id: str, workflow_id: str
    ) -> WorkflowRecord:
        with self.session_factory() as session:
            workflow = session.scalar(
                select(WorkflowRecord).where(
                    WorkflowRecord.id == workflow_id,
                    WorkflowRecord.user_id == user_id,
                    WorkflowRecord.account_id == account_id,
                    WorkflowRecord.type == "competitor_refresh",
                )
            )
            if workflow is None:
                raise CompetitorTargetNotFound("刷新任务不存在")
            return _detached(session, workflow)

    def mark_submission_failed(self, workflow_id: str) -> None:
        public_message = "竞品刷新任务提交失败，请稍后重试"
        now = datetime.now(UTC)
        with self.session_factory() as session:
            workflow = session.get(WorkflowRecord, workflow_id)
            if workflow is None or workflow.type != "competitor_refresh":
                return
            workflow.status = "failed"
            workflow.current_stage = "failed"
            workflow.error = public_message
            workflow.updated_at = now
            target_type = workflow.input_payload.get("targetType")
            target_id = workflow.input_payload.get("targetId")
            target_class = TARGET_CLASSES.get(target_type)
            target = (
                session.get(target_class, target_id)
                if target_class is not None and isinstance(target_id, str)
                else None
            )
            if target is not None and target.active_workflow_id == workflow_id:
                target.refresh_status = "failed"
                target.refresh_error_code = "submission_failed"
                target.refresh_error_message = public_message
                target.active_workflow_id = None
                target.last_attempted_at = now
                target.updated_at = now
            session.commit()

    def claim_due_targets(
        self, now: datetime, limit: int
    ) -> list[WorkflowRecord]:
        claimed: list[WorkflowRecord] = []
        with self.session_factory() as session:
            for target_type, target_class in TARGET_CLASSES.items():
                remaining = limit - len(claimed)
                if remaining <= 0:
                    break
                targets = list(
                    session.scalars(
                        select(target_class)
                        .where(
                            target_class.active_workflow_id.is_(None),
                            or_(
                                target_class.next_refresh_at <= now,
                                target_class.refresh_error_code == "workflow_stale",
                            ),
                        )
                        .order_by(target_class.next_refresh_at, target_class.id)
                        .limit(remaining)
                        .with_for_update(skip_locked=True)
                    )
                )
                for target in targets:
                    workflow = self._new_workflow(
                        target, target_type, "scheduled", now
                    )
                    self._persist_workflow_before_target_reference(session, workflow)
                    target.active_workflow_id = workflow.id
                    target.refresh_status = "pending"
                    target.refresh_error_code = ""
                    target.refresh_error_message = ""
                    target.next_refresh_at = self._next_refresh_at(now)
                    target.updated_at = now
                    claimed.append(workflow)
            session.commit()
            return [_detached(session, workflow) for workflow in claimed]

    def release_terminal_claims(self, now: datetime, stale_seconds: int) -> int:
        released = 0
        stale_before = now - timedelta(seconds=stale_seconds)
        with self.session_factory() as session:
            for target_class in TARGET_CLASSES.values():
                targets = list(
                    session.scalars(
                        select(target_class).where(
                            target_class.active_workflow_id.is_not(None)
                        ).with_for_update(skip_locked=True)
                    )
                )
                for target in targets:
                    workflow = session.get(
                        WorkflowRecord, target.active_workflow_id
                    )
                    if workflow is not None and workflow.status in {"pending", "running"}:
                        updated_at = workflow.updated_at
                        if updated_at.tzinfo is None:
                            updated_at = updated_at.replace(tzinfo=UTC)
                        if updated_at > stale_before:
                            continue
                        workflow.status = "failed"
                        workflow.current_stage = "failed"
                        workflow.error = "竞品刷新任务超时，等待重新调度"
                        workflow.updated_at = now
                    should_retry = workflow is None or workflow.status in {
                        "failed",
                        "cancelled",
                    }
                    target.active_workflow_id = None
                    if should_retry:
                        target.refresh_status = "failed"
                        target.refresh_error_code = "workflow_stale"
                        target.refresh_error_message = "刷新任务超时，系统将自动重试"
                        # 后端重启会终止内存任务；恢复占用时立即到期，让同一轮
                        # 扫描创建新 workflow，无需等待完整刷新周期。
                        target.next_refresh_at = now
                    target.updated_at = now
                    released += 1
            session.commit()
        return released

    def touch_refresh(self, workflow_id: str, now: datetime) -> bool:
        with self.session_factory() as session:
            workflow = session.get(WorkflowRecord, workflow_id)
            if (
                workflow is None
                or workflow.type != "competitor_refresh"
                or workflow.status not in {"pending", "running"}
            ):
                return False
            workflow.updated_at = now
            session.commit()
            return True
