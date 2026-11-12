"""PromptWorkflow — analyse reference images and generate unified image prompts."""

from typing import Any

from app.services.ai_service import AI_SERVICE_FORBIDDEN_SENTINEL
from app.services.prompt_builder import (
    build_image_analysis_prompt,
    build_prompt_generation_system,
    build_prompt_generation_user,
)

from .base import BaseWorkflow, WorkflowRegister
from .steps import ImageAnalysisStep
from .generation_helpers import (
    _exc,
    _join_parent_prompt,
    _loaded_reference_assets,
    build_unified_prompt_user,
    parse_image_prompt_rewrite_result,
)
from .image_prompt_plan import build_image_prompt_plan_user, normalize_image_prompt_plan


IMAGE_PROMPT_PLAN_SYSTEM_PROMPT = (
    "你是社交媒体视觉策划与图像提示词专家。只输出 JSON，不编造账号、产品或案例信息。"
)


@WorkflowRegister.register
class PromptWorkflow(BaseWorkflow):
    type = "prompt"

    def __init__(self, workflow_id: str, context: dict[str, Any] | None = None) -> None:
        super().__init__(workflow_id, context)

    async def execute(self) -> dict[str, Any]:
        record: Any = self.store.get_workflow(self.workflow_id)
        if record is None:
            raise ValueError(f"workflow {self.workflow_id} not found")

        reference_assets = _loaded_reference_assets(record)
        input_payload = record.input_payload or {}
        if input_payload.get("mode") == "topic_image_plan":
            return await self._execute_topic_image_plan(record, input_payload)

        text_only_prompt = not reference_assets and input_payload.get("mode") == "topic_text"
        analysis_prompt = build_image_analysis_prompt(
            target_platform=record.target_platform,
            topic_title=record.topic_title,
            copy_text=record.copy_text or "",
        )

        # ---- run image analysis sub-jobs ----
        payloads = [
            {
                "asset_id": asset.id,
                "sort_order": index,
                "image_url": asset.url,
                "file_name": asset.file_name,
                "analysis_prompt": analysis_prompt,
            }
            for index, asset in enumerate(reference_assets)
        ]
        analysis_results = [] if text_only_prompt else await self._run_analysis_steps(record, payloads)

        asset_by_id = {asset.id: asset for asset in reference_assets}
        analyses: list[str] = []
        image_prompts: list[dict[str, str]] = []
        for result in analysis_results:
            asset_id = str(result.get("asset_id", ""))
            analysis = str(result.get("analysis") or "").strip()
            image_prompt = str(result.get("imagePrompt") or analysis).strip()
            analyses.append(analysis)
            image_prompts.append({"assetId": asset_id, "prompt": image_prompt, "analysis": analysis})
            asset = asset_by_id.get(asset_id)
            if asset is not None:
                self.store.mark_asset_completed(asset.id, analysis, prompt=image_prompt)

        # ---- build unified prompt ----
        knowledge_context = self.store.account_knowledge_context(record.account_id)
        if text_only_prompt:
            prompt_user = build_prompt_generation_user(
                target_platform=record.target_platform,
                topic_title=record.topic_title,
                copy_text=record.copy_text or "",
                analyses=[],
            )
            if knowledge_context:
                prompt_user = f"{prompt_user}\n\n账号知识库:\n{knowledge_context}"
            prompt_input_truncated = False
        else:
            prompt_user, prompt_input_truncated = build_unified_prompt_user(
                record=record,
                analyses=analyses,
                image_prompts=image_prompts,
                knowledge_context=knowledge_context,
            )

        # ---- prompt summary step ----
        step_id = self.store.create_step(
            workflow_id=self.workflow_id,
            user_id=record.user_id,
            account_id=record.account_id,
            step_type="prompt_summary",
            input_payload={"prompt_user": prompt_user},
            group_key="prompt_summary",
        )
        self.store.update_progress(self.workflow_id, progress=60, current_stage="prompt_summary")

        try:
            self.store.mark_step_running(step_id)
            raw_prompt = await self.ai_service.chat_completion(
                messages=[{"role": "user", "content": prompt_user}],
                system_prompt=build_prompt_generation_system(),
                temperature=0.7,
            )
        except Exception as exc:
            self.store.mark_step_failed(step_id, _exc(exc))
            raise

        clean_prompt = str(raw_prompt or "").strip()
        if raw_prompt == AI_SERVICE_FORBIDDEN_SENTINEL:
            raise ValueError("AI service token is not configured")
        if not clean_prompt:
            raise ValueError("prompt generation returned an empty prompt")

        self.store.mark_step_completed(step_id, {"raw": raw_prompt})

        rewritten_image_prompts = [] if text_only_prompt else parse_image_prompt_rewrite_result(clean_prompt, image_prompts)
        parent_prompt = clean_prompt if text_only_prompt else _join_parent_prompt(rewritten_image_prompts)

        result: dict[str, Any] = {
            "prompt": parent_prompt,
            "analyses": analyses,
            "imagePrompts": rewritten_image_prompts,
            "rewriteRaw": clean_prompt,
            "knowledgeContext": knowledge_context,
            "truncated": prompt_input_truncated,
        }
        self.store.update_progress(
            self.workflow_id,
            progress=100,
            current_stage="completed",
            prompt=parent_prompt,
            result_payload=result,
        )
        return result

    async def _execute_topic_image_plan(
        self,
        record: Any,
        input_payload: dict[str, Any],
    ) -> dict[str, Any]:
        self.store.update_progress(self.workflow_id, progress=10, current_stage="context_loading")
        context = self.store.image_prompt_plan_context(
            record.user_id,
            record.account_id,
            str(input_payload["topicId"]),
        )
        reference_assets = _loaded_reference_assets(record)
        reference_note = dict((context.get("topic") or {}).get("referenceNote") or {})
        has_image_reference = (
            reference_note.get("contentType") == "image"
            and bool(str(reference_note.get("publicUrl") or "").strip())
        )
        if has_image_reference and not reference_assets:
            raise ValueError("图文选题缺少参考爆款笔记原图，请重新解析后重试")
        analysis_prompt = build_image_analysis_prompt(
            target_platform=record.target_platform,
            topic_title=record.topic_title,
            copy_text=(
                "请反推原图的主体、场景、构图、镜头、光线、配色、材质、文字安全区和视觉节奏，"
                "忽略水印、品牌标识和原图文字，不要照搬可识别人物。"
            ),
        )
        analysis_payloads = [
            {
                "asset_id": asset.id,
                "sort_order": index,
                "image_url": asset.url,
                "file_name": asset.file_name,
                "analysis_prompt": analysis_prompt,
            }
            for index, asset in enumerate(reference_assets)
        ]
        if analysis_payloads:
            self.store.update_progress(self.workflow_id, progress=15, current_stage="reference_image_analysis")
        analysis_results = await self._run_analysis_steps(record, analysis_payloads)
        asset_by_id = {asset.id: asset for asset in reference_assets}
        reference_analyses: list[str] = []
        for result in analysis_results:
            analysis = str(result.get("analysis") or "").strip()
            if analysis:
                reference_analyses.append(analysis)
            asset = asset_by_id.get(str(result.get("asset_id") or ""))
            if asset is not None:
                self.store.mark_asset_completed(asset.id, analysis, prompt=analysis)
        self.store.update_progress(self.workflow_id, progress=25, current_stage="prompt_building")
        prompt_user = build_image_prompt_plan_user(context, input_payload, reference_analyses)
        step_id = self.store.create_step(
            workflow_id=self.workflow_id,
            user_id=record.user_id,
            account_id=record.account_id,
            step_type="prompt_summary",
            input_payload={"prompt_user": prompt_user},
            group_key="prompt_summary",
        )

        try:
            self.store.mark_step_running(step_id)
            self.store.update_progress(self.workflow_id, progress=40, current_stage="ai_generation")
            raw_result = await self.ai_service.chat_completion(
                messages=[{"role": "user", "content": prompt_user}],
                system_prompt=IMAGE_PROMPT_PLAN_SYSTEM_PROMPT,
                temperature=0.7,
            )
            if raw_result == AI_SERVICE_FORBIDDEN_SENTINEL:
                raise ValueError("AI service token is not configured")
            if not str(raw_result or "").strip():
                raise ValueError("image prompt plan generation returned an empty result")

            self.store.update_progress(self.workflow_id, progress=80, current_stage="normalization")
            result = normalize_image_prompt_plan(raw_result, input_payload)
            result["referenceNote"] = dict((context.get("topic") or {}).get("referenceNote") or {})
            result["referenceAnalyses"] = reference_analyses
            self.store.mark_step_completed(step_id, result)
        except Exception as exc:
            self.store.mark_step_failed(step_id, _exc(exc))
            raise

        self.store.update_progress(
            self.workflow_id,
            progress=100,
            current_stage="completed",
            prompt=result["prompts"][0]["prompt"],
            result_payload=result,
        )
        return result

    async def _run_analysis_steps(
        self,
        record: Any,
        payloads: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for payload in payloads:
            step_id = self.store.create_step(
                workflow_id=self.workflow_id,
                user_id=record.user_id,
                account_id=record.account_id,
                step_type=ImageAnalysisStep.sub_type,
                input_payload=payload,
                sort_order=int(payload.get("sort_order", 0)),
                group_key="image_analysis",
                asset_id=payload.get("asset_id"),
            )
            try:
                self.store.mark_step_running(step_id)
                step = ImageAnalysisStep(ai_service=self.ai_service, storage=self.storage)
                result = await step.execute(payload)
                self.store.mark_step_completed(step_id, result)
                result["asset_id"] = payload.get("asset_id")
                results.append(result)
            except Exception as exc:
                error = _exc(exc)
                self.store.mark_step_failed(step_id, error)
                asset_id = str(payload.get("asset_id") or "")
                if asset_id:
                    self.store.mark_asset_failed(asset_id, error)
                raise
        return results
