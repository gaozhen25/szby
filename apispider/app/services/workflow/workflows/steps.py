"""Pure WorkflowStep subclasses for generation pipelines.

Steps receive plain payloads, return plain payloads, and must not access the
database.
"""

from typing import Any

from app.core.config import settings
from .base import WorkflowStep

REFERENCE_IMAGE_ANALYSIS_ATTEMPTS = 2
IMAGE_GENERATION_SUB_JOB_CONCURRENCY = max(settings.image_generation_sub_job_concurrency or 5, 1)
ALLOWED_IMAGE_CONTENT_TYPES = {"image/png", "image/jpeg", "image/webp"}

RATIO_SIZES = {
    "1:1": "1024x1024",
    "3:4": "960x1280",
    "4:3": "1280x960",
    "9:16": "1008x1792",
    "16:9": "1792x1008",
}

IMAGE_EXTENSION_BY_CONTENT_TYPE = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
}


class ImageAnalysisStep(WorkflowStep):
    sub_type = "image_analysis"

    async def execute(self, payload: dict[str, Any]) -> dict[str, Any]:
        last_analysis = ""
        last_error: BaseException | None = None
        for _ in range(REFERENCE_IMAGE_ANALYSIS_ATTEMPTS):
            try:
                analysis = await self.ai_service.image_view(
                    prompt=str(payload.get("analysis_prompt") or ""),
                    image_url=str(payload.get("image_url") or ""),
                )
            except Exception as exc:
                last_error = exc
                continue
            last_analysis = str(analysis or "").strip()
            if last_analysis:
                return {"analysis": last_analysis, "imagePrompt": last_analysis}
        if last_error is not None:
            raise last_error
        raise ValueError("reference image analysis returned an empty result")


class ImageGenerationStep(WorkflowStep):
    sub_type = "image_generation"

    async def execute(self, payload: dict[str, Any]) -> dict[str, Any]:
        input_references = list(payload.get("input_references") or [])
        model_references: list[dict[str, Any]] = []
        for item in input_references:
            if isinstance(item, dict) and item.get("url"):
                model_references.append({"type": "image_url", "image_url": {"url": str(item["url"])}})
        generation_kwargs: dict[str, Any] = {
            "model": None,
            "prompt": str(payload.get("prompt") or ""),
            "size": RATIO_SIZES.get(str(payload.get("ratio") or ""), RATIO_SIZES["3:4"]),
            "n": 1,
        }
        if model_references:
            results = await self.ai_service.image_edit(
                **generation_kwargs,
                input_reference=model_references,
            )
        else:
            results = await self.ai_service.image_generation(**generation_kwargs)
        if not results:
            raise ValueError("image generation returned an empty result")
        result: dict[str, Any] = {"image": results[0], "prompt": str(payload.get("prompt") or "")}
        for key in ("slot", "slotIndex", "variantIndex", "refinement"):
            if key in payload:
                result[key] = payload[key]
        return result


class ImageEvaluationStep(WorkflowStep):
    sub_type = "image_evaluation"

    async def execute(self, payload: dict[str, Any]) -> dict[str, Any]:
        evaluator = getattr(self.ai_service, "image_evaluation", None)
        if callable(evaluator):
            result = await evaluator(**payload)
            if isinstance(result, dict):
                return result
            return {"summary": str(result or "").strip()}
        return {"summary": "", "items": []}
