"""账号报告采集进度的有界聚合与 best-effort 持久化。"""

from __future__ import annotations

import hashlib
import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from app.services.mediaspider.failure_catalog import normalize_public_failure
from app.services.mediaspider.models import (
    CrawlerFailure,
    CrawlerProgressEvent,
    ProgressCallback,
)
from app.services.mediaspider.progress_safety import (
    public_action_message,
    sanitize_event_subject,
    sanitize_public_text,
)

from .crawl_notice_catalog import public_account_report_notice
from .crawl_progress_models import (
    CrawlActivity,
    CrawlTarget,
    PlatformState,
    snapshot_dict,
)

if TYPE_CHECKING:
    from app.services.workflow.workflow_store import WorkflowStore


logger = logging.getLogger(__name__)
_MAX_ACTIVITIES = 30


def _occurred_at() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _merge_fingerprint(value: Any) -> str:
    return hashlib.sha256(str(value or "").encode()).hexdigest()


def _stage_for(event: CrawlerProgressEvent, mode: str) -> str:
    if event.action == "content_discovered":
        return "content"
    if event.action == "comments_updated":
        return "comments"
    if event.action == "creator_discovered":
        return "creator"
    return "creator" if mode == "creator" else "keyword"


def _account_report_action_message(mode: str, action: str) -> str:
    overrides = {
        ("creator", "creator_started"): "开始采集当前账号主页公开信息",
        ("creator", "creator_discovered"): "读取账号公开资料",
        ("keyword", "keyword_started"): "开始采集行业关键词内容",
        ("keyword", "creator_discovered"): "发现行业公开账号",
    }
    return overrides.get((mode, action), public_action_message(action))


class AccountReportCrawlProgressTracker:
    """聚合白名单事件；持久化失败不影响采集 workflow。"""

    def __init__(
        self,
        workflow_id: str,
        store: WorkflowStore,
        targets: list[CrawlTarget],
        *,
        track_comments: bool = True,
    ) -> None:
        self.workflow_id = workflow_id
        self.store = store
        self.progress = 10
        self.current_stage = "keyword_planning"
        self._track_comments = track_comments
        self._sequence = 0
        self._activities: list[CrawlActivity] = []
        self._last_merge_key: tuple[str, ...] | None = None
        self._states = {
            target.platform_code: PlatformState(target=target) for target in targets
        }
        self._persist()

    def callback(self, platform_name: str, mode: str) -> ProgressCallback:
        safe_platform_name = sanitize_public_text(platform_name, limit=20)

        async def on_progress(event: CrawlerProgressEvent) -> None:
            await self.record(
                event,
                platform_name=safe_platform_name,
                mode=mode,
            )

        return on_progress

    async def record(
        self,
        event: CrawlerProgressEvent,
        *,
        platform_name: str | None = None,
        mode: str | None = None,
    ) -> None:
        if not self._track_comments and event.action == "comments_updated":
            return
        state = self._states.get(event.platform)
        if state is None:
            return
        effective_mode = mode or (
            "creator" if event.crawl_type == "creator" else "keyword"
        )
        self.current_stage = (
            "creator_crawling"
            if effective_mode == "creator"
            else "keyword_crawling"
        )
        self.progress = max(
            self.progress, 15 if effective_mode == "creator" else 40
        )
        state.active = event.status not in {"completed", "failed", "skipped"}
        state.current_content_count = max(
            state.current_content_count, event.content_count
        )
        state.current_creator_count = max(
            state.current_creator_count, event.creator_count
        )
        state.current_comment_count = max(
            state.current_comment_count,
            event.comment_count if self._track_comments else 0,
        )

        self._sequence += 1
        safe_platform_name = platform_name or state.target.platform_name
        activity = CrawlActivity(
            sequence=self._sequence,
            stage=_stage_for(event, effective_mode),
            status=event.status,
            platform=sanitize_public_text(event.platform, limit=20),
            platformName=sanitize_public_text(safe_platform_name, limit=20),
            action=event.action,
            message=_account_report_action_message(effective_mode, event.action),
            subject=sanitize_event_subject(
                event.action,
                event.subject,
                platform=event.platform,
                platform_name=safe_platform_name,
            ),
            contentTitle=sanitize_public_text(event.content_title, limit=60),
            contentCount=(
                state.observed_content_count + state.current_content_count
            ),
            creatorCount=(
                state.observed_creator_count + state.current_creator_count
            ),
            commentCount=(
                state.observed_comment_count + state.current_comment_count
            ),
            occurredAt=_occurred_at(),
        )
        merge_key = (
            event.platform,
            event.action,
            event.status,
            _merge_fingerprint(event.subject),
            _merge_fingerprint(event.content_title),
        )
        if self._activities and self._last_merge_key == merge_key:
            self._activities[-1] = activity
        else:
            self._activities.append(activity)
            self._activities = self._activities[-_MAX_ACTIVITIES:]
        self._last_merge_key = merge_key
        self._persist()

    def notice(
        self,
        platform_code: str,
        *,
        mode: str,
        code: str,
    ) -> None:
        state = self._states.get(platform_code)
        if state is None:
            return
        safe_notice = public_account_report_notice(code)
        safe_mode = mode if mode == "creator" else "workflow"
        state.notices[safe_mode] = safe_notice
        state.active = False
        state.settle_current_counts()
        self.current_stage = "creator_crawling"
        self.progress = max(self.progress, 15)
        self._append_lifecycle_activity(
            state,
            stage="creator",
            action="creator_skipped",
            status="skipped",
            message=safe_notice.message,
        )
        self._persist()

    def fail(
        self,
        platform_code: str,
        *,
        mode: str,
        failure: CrawlerFailure,
    ) -> None:
        state = self._states.get(platform_code)
        if state is None:
            return
        safe_failure = normalize_public_failure(failure)
        safe_mode = (
            mode if mode in {"creator", "keyword", "configuration"} else "workflow"
        )
        state.failures[safe_mode] = safe_failure
        state.active = False
        state.settle_current_counts()
        is_skipped = safe_failure.code == "credentials_missing"
        self.current_stage = (
            "creator_crawling"
            if safe_mode in {"creator", "configuration"}
            else "keyword_crawling"
        )
        self.progress = max(
            self.progress,
            15 if safe_mode in {"creator", "configuration"} else 40,
        )
        self._append_lifecycle_activity(
            state,
            stage=(
                "creator"
                if safe_mode in {"creator", "configuration"}
                else "keyword"
            ),
            action=f"{safe_mode}_{'skipped' if is_skipped else 'failed'}",
            status="skipped" if is_skipped else "failed",
            message=safe_failure.message,
        )
        self._persist()

    def complete(
        self,
        platform_code: str,
        *,
        content_count: int,
        creator_count: int,
        comment_count: int,
    ) -> None:
        state = self._states.get(platform_code)
        if state is None:
            return
        state.settle_current_counts(
            content_count=content_count,
            creator_count=creator_count,
            comment_count=(comment_count if self._track_comments else 0),
        )
        state.successful_runs += 1
        state.active = False
        self._persist()

    def failure_summary(self) -> str:
        reasons = []
        for state in self._states.values():
            failure = state.latest_failure
            if failure is None:
                continue
            reasons.append(
                f"{sanitize_public_text(state.target.platform_name, limit=20)}："
                f"{sanitize_public_text(failure.message, limit=120)}"
            )
        suffix = f"。{'；'.join(reasons)}" if reasons else ""
        return f"所有支持平台采集失败，旧报告已保留{suffix}"

    def snapshot(self) -> dict[str, Any]:
        return snapshot_dict(self._activities, self._states)

    def set_stage(self, *, progress: int, current_stage: str) -> None:
        self.progress = max(self.progress, progress)
        self.current_stage = current_stage
        self._persist()

    def _append_lifecycle_activity(
        self,
        state: PlatformState,
        *,
        stage: str,
        action: str,
        status: str,
        message: str,
    ) -> None:
        self._sequence += 1
        self._activities.append(
            CrawlActivity(
                sequence=self._sequence,
                stage=stage,
                status=status,
                platform=sanitize_public_text(
                    state.target.platform_code, limit=20
                ),
                platformName=sanitize_public_text(
                    state.target.platform_name, limit=20
                ),
                action=action,
                message=sanitize_public_text(message, limit=160),
                contentCount=state.observed_content_count,
                creatorCount=state.observed_creator_count,
                commentCount=state.observed_comment_count,
                occurredAt=_occurred_at(),
            )
        )
        self._activities = self._activities[-_MAX_ACTIVITIES:]
        self._last_merge_key = (
            state.target.platform_code,
            action,
            status,
            _merge_fingerprint(""),
            _merge_fingerprint(""),
        )

    def _persist(self) -> None:
        try:
            self.store.update_progress(
                self.workflow_id,
                progress=self.progress,
                current_stage=self.current_stage,
                result_payload={"crawlProgress": self.snapshot()},
            )
        except Exception:
            logger.warning("账号报告采集进度暂时无法持久化")
