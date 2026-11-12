"""数据库驱动的竞品监控周期扫描器。"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

from app.core.config import settings
from app.core.logging import get_logger
from app.services.workflow import WorkflowScheduler

from .service import CompetitorMonitoringService

logger = get_logger(__name__)


class CompetitorPeriodicScheduler:
    def __init__(
        self,
        *,
        competitor_service: CompetitorMonitoringService | None = None,
        workflow_scheduler: Any = None,
        scan_seconds: int | None = None,
        batch_size: int | None = None,
        stale_workflow_seconds: int | None = None,
    ) -> None:
        self.competitor_service = competitor_service or CompetitorMonitoringService()
        self.workflow_scheduler = workflow_scheduler or WorkflowScheduler.get_instance()
        self.scan_seconds = (
            scan_seconds
            if scan_seconds is not None
            else settings.COMPETITOR_SCHEDULER_SCAN_SECONDS
        )
        self.batch_size = (
            batch_size
            if batch_size is not None
            else settings.COMPETITOR_SCHEDULER_BATCH_SIZE
        )
        self.stale_workflow_seconds = (
            stale_workflow_seconds
            if stale_workflow_seconds is not None
            else settings.COMPETITOR_WORKFLOW_STALE_SECONDS
        )
        self._stop_event: asyncio.Event | None = None
        self._task: asyncio.Task[None] | None = None

    @property
    def is_running(self) -> bool:
        return self._task is not None and not self._task.done()

    def start(self) -> None:
        if self.is_running:
            return
        self._stop_event = asyncio.Event()
        self._task = asyncio.create_task(
            self._run(), name="competitor-periodic-scheduler"
        )

    async def stop(self) -> None:
        task = self._task
        if task is None:
            return
        if self._stop_event is not None:
            self._stop_event.set()
        await task
        self._task = None
        self._stop_event = None

    async def scan_once(self) -> int:
        now = datetime.now(UTC)
        self.competitor_service.release_terminal_claims(
            now, self.stale_workflow_seconds
        )
        workflows = self.competitor_service.claim_due_targets(
            now, self.batch_size
        )
        for workflow in workflows:
            try:
                self.workflow_scheduler.submit("competitor_refresh", workflow.id)
            except Exception:
                self.competitor_service.mark_submission_failed(workflow.id)
                logger.error(
                    "competitor scheduled workflow submission failed workflow_id=%s",
                    workflow.id,
                )
        return len(workflows)

    async def _run(self) -> None:
        stop_event = self._stop_event
        if stop_event is None:
            return
        while not stop_event.is_set():
            try:
                await self.scan_once()
            except Exception:
                logger.exception("competitor periodic scan failed")
            try:
                await asyncio.wait_for(
                    stop_event.wait(), timeout=self.scan_seconds
                )
            except TimeoutError:
                continue


competitor_periodic_scheduler = CompetitorPeriodicScheduler()
