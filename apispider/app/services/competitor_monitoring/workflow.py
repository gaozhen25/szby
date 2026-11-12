"""执行单个竞品监控对象刷新。"""

from __future__ import annotations

import asyncio
from contextlib import suppress
from datetime import UTC, datetime

from app.core.config import settings
from app.core.logging import get_logger
from app.services.mediaspider.failure_catalog import public_crawler_failure
from app.services.mediaspider.models import CrawlerExecutionError
from app.services.workflow.workflows.base import BaseWorkflow, WorkflowRegister

from .service import CompetitorMonitoringService

logger = get_logger(__name__)


class CompetitorRefreshFailed(Exception):
    pass


@WorkflowRegister.register
class CompetitorRefreshWorkflow(BaseWorkflow):
    type = "competitor_refresh"
    requires_ai = False

    async def execute(self) -> dict[str, object]:
        service = self.context.get("_competitor_service") or CompetitorMonitoringService()
        heartbeat = asyncio.create_task(
            self._heartbeat(service), name=f"competitor-heartbeat-{self.workflow_id}"
        )
        try:
            return await service.execute_refresh(
                self.workflow_id,
                crawler_service=self.context.get("_crawler_service"),
                cookie_pool_loader=self.context.get("_cookie_pool_loader"),
                runtime_options_loader=self.context.get("_runtime_options_loader"),
            )
        except CrawlerExecutionError as exc:
            failure = exc.failure
            logger.warning(
                "competitor refresh crawler failed workflow_id=%s "
                "failure_code=%s cause_type=%s partial_creators=%s partial_contents=%s",
                self.workflow_id,
                failure.code,
                exc.cause_type,
                exc.partial_result.creator_count,
                exc.partial_result.content_count,
            )
        except Exception:
            failure = public_crawler_failure("crawler_failed")
        finally:
            heartbeat.cancel()
            with suppress(asyncio.CancelledError):
                await heartbeat
        service.fail_refresh(self.workflow_id, failure.code, failure.message)
        raise CompetitorRefreshFailed(failure.message) from None

    async def _heartbeat(self, service) -> None:
        interval = self.context.get("_heartbeat_seconds") or settings.COMPETITOR_WORKFLOW_HEARTBEAT_SECONDS
        while True:
            await asyncio.sleep(interval)
            try:
                alive = await asyncio.to_thread(
                    service.touch_refresh, self.workflow_id, datetime.now(UTC)
                )
            except Exception:
                logger.warning(
                    "competitor refresh heartbeat failed workflow_id=%s",
                    self.workflow_id,
                )
                continue
            if not alive:
                return
