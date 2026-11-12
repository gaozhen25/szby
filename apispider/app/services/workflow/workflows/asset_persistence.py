"""链接解析资源的后台持久化工作流。"""

from __future__ import annotations

import asyncio
from typing import Any

from app.services.extract_service.asset_persistence import ExtractAssetPersistenceService
from .base import BaseWorkflow, WorkflowRegister


@WorkflowRegister.register
class AssetPersistenceWorkflow(BaseWorkflow):
    type = "asset_persistence"
    requires_ai = False

    async def execute(self) -> dict[str, Any]:
        snapshot = self.store.load_asset_persistence_context(self.workflow_id)
        self.store.update_progress(self.workflow_id, progress=10, current_stage="media_persistence")
        service = self.context.get("_persistence_service") or ExtractAssetPersistenceService(
            storage=self.storage,
        )
        result = await asyncio.to_thread(service.persist, snapshot)
        self.store.apply_asset_persistence_result(self.workflow_id, result)
        self.store.update_progress(self.workflow_id, progress=95, current_stage=result.status)
        return {
            "persistenceStatus": result.status,
            "assets": result.assets,
            "urlMap": result.url_map,
            "retryCount": result.retry_count,
            "error": result.error,
        }
