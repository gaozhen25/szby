"""ImageWorkflow — generate images from prompts (with optional slot/variant matrix)."""

import asyncio
from typing import Any

from .base import BaseWorkflow, WorkflowRegister
from . import steps as workflow_steps
from .steps import ImageEvaluationStep, ImageGenerationStep
from .generation_helpers import (
    _append_image_input_prompt,
    _asset_from_image_result,
    _build_slot_generation_prompt,
    _exc,
    _image_input_references,
    cleanup_storage_objects,
)


@WorkflowRegister.register
class ImageWorkflow(BaseWorkflow):
    type = "image"

    def __init__(self, workflow_id: str, context: dict[str, Any] | None = None) -> None:
        super().__init__(workflow_id, context)

    async def execute(self) -> dict[str, Any]:
        record: Any = self.store.get_workflow(self.workflow_id)
        if record is None:
            raise ValueError(f"workflow {self.workflow_id} not found")

        input_payload = record.input_payload or {}
        uses_slots = bool(input_payload.get("usesSlots"))
        refinement = str(input_payload.get("refinement") or "").strip()
        input_references = _image_input_references(record)

        if uses_slots:
            slots = list(input_payload.get("slots") or [])
            variants_per_slot = int(input_payload.get("variantsPerSlot") or 1)
            slot_prompts = self.store.image_prompts_for_generation_job(
                record, record.requested_count, record.prompt
            )
            payloads: list[dict[str, Any]] = []
            for slot_index, slot in enumerate(slots):
                slot_payload = dict(slot or {})
                base_prompt = slot_prompts[slot_index] if slot_index < len(slot_prompts) else record.prompt
                for variant_index in range(variants_per_slot):
                    payloads.append({
                        "sort_order": len(payloads),
                        "prompt": _append_image_input_prompt(
                            _build_slot_generation_prompt(base_prompt, slot_payload, refinement),
                            input_references,
                        ),
                        "ratio": record.ratio or "3:4",
                        "input_references": input_references,
                        "slot": slot_payload,
                        "slotIndex": slot_index,
                        "variantIndex": variant_index,
                        "refinement": refinement,
                    })
        else:
            prompts = self.store.image_prompts_for_generation_job(
                record, record.requested_count, record.prompt
            )
            payloads = [
                {
                    "sort_order": index,
                    "prompt": _append_image_input_prompt(prompt, input_references),
                    "ratio": record.ratio or "3:4",
                    "input_references": input_references,
                }
                for index, prompt in enumerate(prompts)
            ]

        # ---- run image generation sub-jobs ----
        image_results = await self._run_generation_steps(record, payloads)

        # ---- build image payloads ----
        image_payloads: list[dict[str, str]] = []
        image_prompt_payloads: list[dict[str, str]] = []
        groups_by_slot: dict[str, dict[str, Any]] = {}
        storage_keys: list[str] = []
        result_asset_ids: list[str] = []

        try:
            for index, result in enumerate(image_results):
                image_info = dict(result.get("image") or {})
                image_payload = {
                    "url": str(image_info.get("url") or ""),
                    "revisedPrompt": str(image_info.get("revisedPrompt") or ""),
                }
                storage_managed = bool(image_info.get("storageManaged"))
                storage_key = str(image_info.get("storageKey") or "")
                _asset_id = str(result.get("assetId") or image_info.get("assetId") or "")
                if storage_managed and storage_key:
                    storage_keys.append(storage_key)
                if _asset_id:
                    result_asset_ids.append(_asset_id)

                if uses_slots:
                    slot = dict(result.get("slot") or {})
                    slot_id = str(slot.get("slotId") or f"slot_{index + 1}")
                    variant_index = int(result.get("variantIndex") or 0)
                    variant_id = f"{_asset_id}_{variant_index}"
                    image_payload = {
                        **image_payload,
                        "slotId": slot_id,
                        "variantId": variant_id,
                        "variantIndex": variant_index,
                    }
                    group = groups_by_slot.setdefault(slot_id, {
                        "slotId": slot_id,
                        "sourceType": str(slot.get("sourceType") or "manual"),
                        "sourceUrl": str(slot.get("sourceUrl") or ""),
                        "sourcePrompt": str(slot.get("sourcePrompt") or ""),
                        "refinement": refinement,
                        "variants": [],
                    })
                    group["variants"].append(dict(image_payload))

                image_payloads.append(image_payload)
                prompt_payload = {"url": image_payload["url"], "prompt": str(result.get("prompt") or "")}
                if uses_slots:
                    prompt_payload["slotId"] = image_payload["slotId"]
                    prompt_payload["variantIndex"] = image_payload["variantIndex"]
                image_prompt_payloads.append(prompt_payload)
        except Exception:
            cleanup_storage_objects(self.storage, storage_keys)
            self.store.delete_assets(result_asset_ids)
            raise

        # ---- evaluation step ----
        step_id = self.store.create_step(
            workflow_id=self.workflow_id,
            user_id=record.user_id,
            account_id=record.account_id,
            step_type=ImageEvaluationStep.sub_type,
            input_payload={"images": image_prompt_payloads, "prompt": record.prompt, "ratio": record.ratio or "3:4"},
            group_key="image_evaluation",
        )
        self.store.update_progress(self.workflow_id, progress=80, current_stage="image_evaluation")

        try:
            self.store.mark_step_running(step_id)
            evaluator = ImageEvaluationStep(ai_service=self.ai_service, storage=self.storage)
            evaluation = await evaluator.execute({
                "images": image_prompt_payloads,
                "prompt": record.prompt,
                "ratio": record.ratio or "3:4",
            })
            self.store.mark_step_completed(step_id, evaluation)
        except Exception as exc:
            cleanup_storage_objects(self.storage, storage_keys)
            self.store.delete_assets(result_asset_ids)
            self.store.mark_step_failed(step_id, _exc(exc))
            raise

        result_payload: dict[str, Any] = {
            "images": image_payloads,
            "imagePrompts": image_prompt_payloads,
            "evaluation": evaluation,
        }
        if uses_slots:
            image_groups = list(groups_by_slot.values())
            for group in image_groups:
                group["variants"] = sorted(group["variants"], key=lambda item: item["variantIndex"])
            result_payload["imageGroups"] = image_groups

        self.store.update_progress(
            self.workflow_id, progress=100, current_stage="completed", result_payload=result_payload
        )
        return result_payload

    async def _run_generation_steps(
        self,
        record: Any,
        payloads: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        semaphore = asyncio.Semaphore(workflow_steps.IMAGE_GENERATION_SUB_JOB_CONCURRENCY)
        uploaded_storage_keys: list[str] = []
        uploaded_asset_ids: list[str] = []

        async def _run_one(payload: dict[str, Any]) -> dict[str, Any]:
            step_id = self.store.create_step(
                workflow_id=self.workflow_id,
                user_id=record.user_id,
                account_id=record.account_id,
                step_type=ImageGenerationStep.sub_type,
                input_payload=payload,
                sort_order=int(payload.get("sort_order", 0)),
                group_key="image_generation",
            )
            try:
                async with semaphore:
                    self.store.mark_step_running(step_id)
                    step = ImageGenerationStep(ai_service=self.ai_service, storage=self.storage)
                    raw_result = await step.execute(payload)
                    asset, image_payload = _asset_from_image_result(
                        record,
                        raw_result.get("image") or {},
                        int(payload.get("sort_order", 0)),
                        self.storage,
                    )
                    source = str((asset.meta or {}).get("source") or "")
                    asset_id = asset.id
                    storage_key = asset.storage_key
                    lightweight_image = {
                        "url": image_payload["url"],
                        "revisedPrompt": image_payload.get("revisedPrompt", ""),
                        "source": "generated_upload" if source == "b64_json" else source,
                        "assetId": asset_id,
                        "storageKey": storage_key,
                        "storageManaged": source == "b64_json",
                    }
                    self.store.add_asset(asset)
                    uploaded_asset_ids.append(asset_id)
                    if source == "b64_json":
                        uploaded_storage_keys.append(storage_key)
                    result = {**raw_result, "image": lightweight_image, "assetId": asset_id}
                self.store.mark_step_completed(step_id, result)
                return result
            except Exception as exc:
                cleanup_storage_objects(self.storage, uploaded_storage_keys)
                self.store.delete_assets(uploaded_asset_ids)
                uploaded_storage_keys.clear()
                uploaded_asset_ids.clear()
                self.store.mark_step_failed(step_id, _exc(exc))
                raise

        return await asyncio.gather(*[_run_one(p) for p in payloads])
