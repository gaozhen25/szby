"""Video script rewrite workflow."""

from typing import Any

from app.services.ai_service import default_ai_service
from app.services.prompt_builder import build_script_rewrite_system, build_script_rewrite_user
from .base import BaseWorkflow, WorkflowRegister, normalize_json


@WorkflowRegister.register
class VideoScriptRewriteWorkflow(BaseWorkflow):
    type = "video_script_rewrite"

    def __init__(self, workflow_id: str, context: dict[str, Any] | None = None) -> None:
        super().__init__(workflow_id, context)
        ctx = context or {}
        self.origin_script = str(ctx.get("source_script") or "")
        self.target_platform = str(ctx.get("target_platform") or "")
        self.topic_title = str(ctx.get("topic_title") or "")
        self.user_info = str(ctx.get("user_info") or "")

    async def execute(self) -> dict[str, Any]:
        if not self.origin_script:
            raise ValueError("Video script rewrite workflow requires 'source_script' in context")

        # ---- create step record ----
        step_id = self.store.create_step(
            workflow_id=self.workflow_id,
            user_id="",
            account_id=None,
            step_type="script_rewrite",
            input_payload={
                "originalScript": [self.origin_script],
                "copyText": self.user_info,
                "targetPlatform": self.target_platform,
                "topicTitle": self.topic_title,
            },
            group_key="script_rewrite",
        )

        # ---- update progress: starting ----
        self.store.update_progress(self.workflow_id, progress=20, current_stage="script_rewrite")

        # ---- execute ----
        try:
            self.store.mark_step_running(step_id)
            raw = await default_ai_service.chat_completion(
                messages=[
                    {
                        "role": "user",
                        "content": build_script_rewrite_user(
                            target_platform=self.target_platform,
                            topic_title=self.topic_title,
                            copy_text=self.user_info,
                            original_script=[self.origin_script],
                        ),
                    }
                ],
                system_prompt=build_script_rewrite_system(),
                temperature=0.75,
            )
        except Exception as exc:
            self.store.mark_step_failed(step_id, _exc_msg(exc))
            raise

        # ---- normalize ----
        parsed = normalize_json(raw)
        if parsed is None:
            # fallback: treat entire text as single script line
            result = {"script": [str(raw or "").strip()], "hookSuggestion": "", "rhythmNote": ""}
        else:
            script = parsed.get("script")
            if isinstance(script, list):
                script_lines = [str(line).strip() for line in script if str(line or "").strip()]
            elif isinstance(script, str) and script.strip():
                script_lines = [line.strip() for line in script.splitlines() if line.strip()]
            else:
                script_lines = []
            result = {
                "script": script_lines,
                "hookSuggestion": str(parsed.get("hookSuggestion") or "").strip(),
                "rhythmNote": str(parsed.get("rhythmNote") or "").strip(),
            }

        self.store.mark_step_completed(step_id, result)
        self.store.update_progress(self.workflow_id, progress=100, current_stage="completed")

        return result


def _exc_msg(exc: BaseException) -> str:
    original = getattr(exc, "orig", None)
    if original is not None:
        msg = str(original).strip()
        if msg:
            return msg
    msg = str(exc).strip()
    return msg or exc.__class__.__name__
