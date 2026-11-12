"""ScriptRewriteWorkflow — generation variant that rewrites scripts from WorkflowRecord data."""

from typing import Any

from app.services.ai_service import AI_SERVICE_FORBIDDEN_SENTINEL
from app.services.prompt_builder import build_script_rewrite_system, build_script_rewrite_user

from .base import BaseWorkflow, WorkflowRegister
from .generation_helpers import _exc, parse_script_rewrite_result


@WorkflowRegister.register
class ScriptRewriteWorkflow(BaseWorkflow):
    type = "script_rewrite"

    def __init__(self, workflow_id: str, context: dict[str, Any] | None = None) -> None:
        super().__init__(workflow_id, context)

    async def execute(self) -> dict[str, Any]:
        record: Any = self.store.get_workflow(self.workflow_id)
        if record is None:
            raise ValueError(f"workflow {self.workflow_id} not found")

        input_payload = record.input_payload or {}
        original_script = list(input_payload.get("originalScript") or [])
        if not original_script:
            raise ValueError("original script is missing from job input")

        step_id = self.store.create_step(
            workflow_id=self.workflow_id,
            user_id=record.user_id,
            account_id=record.account_id,
            step_type="script_rewrite",
            input_payload={"originalScript": original_script, "copyText": record.copy_text or ""},
            group_key="script_rewrite",
        )
        self.store.update_progress(self.workflow_id, progress=20, current_stage="script_rewrite")

        try:
            self.store.mark_step_running(step_id)
            raw_text = await self.ai_service.chat_completion(
                messages=[{
                    "role": "user",
                    "content": build_script_rewrite_user(
                        target_platform=record.target_platform,
                        topic_title=record.topic_title,
                        copy_text=record.copy_text or "",
                        original_script=original_script,
                    ),
                }],
                system_prompt=build_script_rewrite_system(),
                temperature=0.75,
            )
            if raw_text == AI_SERVICE_FORBIDDEN_SENTINEL:
                raise ValueError("AI service token is not configured")

            result = parse_script_rewrite_result(raw_text)
            self.store.mark_step_completed(step_id, result)
        except Exception as exc:
            self.store.mark_step_failed(step_id, _exc(exc))
            raise

        self.store.update_progress(
            self.workflow_id, progress=100, current_stage="completed", result_payload=result
        )
        return result
