"""Manual-backed video script generation workflow."""

from typing import Any

from app.services.ai_service import AI_SERVICE_FORBIDDEN_SENTINEL

from .base import BaseWorkflow, WorkflowRegister
from .generation_helpers import _exc
from .video_script_contract import normalize_video_script_result
from .video_script_prompts import (
    build_video_script_system_prompt,
    build_video_script_user_prompt,
)


@WorkflowRegister.register
class VideoScriptWorkflow(BaseWorkflow):
    type = "video_script"

    async def execute(self) -> dict[str, Any]:
        record: Any = self.store.get_workflow(self.workflow_id)
        if record is None:
            raise ValueError(f"workflow {self.workflow_id} not found")
        if not record.account_id:
            raise ValueError("video script account is missing")

        input_payload = dict(record.input_payload or {})
        topic_id = str(input_payload.get("topicId") or "").strip()
        if not topic_id:
            raise ValueError("video topic is missing from job input")

        preferences = {
            "targetPlatform": str(
                input_payload.get("targetPlatform") or record.target_platform or ""
            ).strip(),
            "durationSeconds": int(input_payload.get("durationSeconds") or 60),
            "contentGoal": str(input_payload.get("contentGoal") or "auto").strip(),
            "videoFormat": str(input_payload.get("videoFormat") or "auto").strip(),
            "toneStyle": str(input_payload.get("toneStyle") or "auto").strip(),
            "customRequirements": str(input_payload.get("customRequirements") or "").strip(),
        }

        self.store.update_progress(
            self.workflow_id,
            progress=10,
            current_stage="context_loading",
        )
        context = self.store.video_script_context(
            record.user_id,
            record.account_id,
            topic_id,
        )

        self.store.update_progress(
            self.workflow_id,
            progress=25,
            current_stage="prompt_building",
        )
        user_prompt = build_video_script_user_prompt(context, preferences)
        step_id = self.store.create_step(
            workflow_id=self.workflow_id,
            user_id=record.user_id,
            account_id=record.account_id,
            step_type="video_script_generation",
            input_payload={"prompt": user_prompt},
            group_key="video_script_generation",
        )

        self.store.update_progress(
            self.workflow_id,
            progress=40,
            current_stage="ai_generation",
        )
        try:
            self.store.mark_step_running(step_id)
            raw_result = await self.ai_service.chat_completion(
                messages=[{"role": "user", "content": user_prompt}],
                system_prompt=build_video_script_system_prompt(),
                temperature=0.7,
            )
            if raw_result == AI_SERVICE_FORBIDDEN_SENTINEL:
                raise ValueError("AI service token is not configured")

            self.store.update_progress(
                self.workflow_id,
                progress=80,
                current_stage="normalization",
            )
            result = normalize_video_script_result(
                raw_result,
                duration_seconds=preferences["durationSeconds"],
            )
            self.store.mark_step_completed(step_id, result)
        except Exception as exc:
            self.store.mark_step_failed(step_id, _exc(exc))
            raise

        self.store.update_progress(
            self.workflow_id,
            progress=100,
            current_stage="completed",
            result_payload=result,
        )
        return result
