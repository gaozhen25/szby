"""Shared helpers for generation workflows — asset, storage, prompt building, result parsing."""

import base64
import binascii
import json
import os
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4

from app.core.config import settings
from app.db.models import GenerationAssetRecord
from app.services.prompt_builder import build_prompt_generation_user
from app.services.resource_limits import ensure_size_within_limit

from .base import normalize_json
from .steps import IMAGE_EXTENSION_BY_CONTENT_TYPE

PROMPT_GENERATION_USER_LIMIT = 30000
PROMPT_COPY_TEXT_LIMIT = 6000
PROMPT_ANALYSES_TOTAL_LIMIT = 12000
PROMPT_ANALYSIS_ITEM_LIMIT = 3000
PROMPT_IMAGE_PROMPTS_JSON_LIMIT = 8000
PROMPT_KNOWLEDGE_CONTEXT_LIMIT = 3000

GENERATION_JOB_TYPES = ["prompt", "image", "script_rewrite", "video_script"]


# ---------------------------------------------------------------------------
# exception message
# ---------------------------------------------------------------------------

def _exc(exc: BaseException) -> str:
    original = getattr(exc, "orig", None)
    if original is not None:
        msg = str(original).strip()
        if msg:
            return msg
    msg = str(exc).strip()
    return msg or exc.__class__.__name__


# ---------------------------------------------------------------------------
# asset helpers
# ---------------------------------------------------------------------------

def _loaded_reference_assets(record: Any) -> list[Any]:
    return [asset for asset in getattr(record, "assets", []) or [] if getattr(asset, "asset_type", None) == "reference"]


def _new_asset_id() -> str:
    return f"ga_{uuid4().hex}"


def _asset_from_image_result(
    record: Any,
    item: dict[str, Any],
    index: int,
    storage: Any,
) -> tuple[GenerationAssetRecord, dict[str, str]]:
    asset_id = _new_asset_id()
    now = datetime.now(UTC)
    revised_prompt = _revised_prompt(item)
    if item.get("url"):
        url = str(item["url"])
        file_name = os.path.basename(url.split("?", 1)[0]) or f"{asset_id}.png"
        return (
            GenerationAssetRecord(
                id=asset_id,
                job_id=record.id,
                account_id=record.account_id,
                asset_type="result",
                file_name=file_name,
                mime_type="image/png",
                storage_key=url,
                url=url,
                status="completed",
                analysis="",
                error="",
                meta={"source": "url", "index": index, "revisedPrompt": revised_prompt},
                created_at=now,
            ),
            {"url": url, "revisedPrompt": revised_prompt},
        )

    raw_b64 = str(item.get("b64_json") or "")
    if not raw_b64:
        raise ValueError("image generation result did not include url or b64_json")
    data, content_type, extension = _decode_generated_image(raw_b64)
    key = _storage_key(f"generation/{record.account_id}/{record.id}/results/{asset_id}{extension}")
    url = storage.put_bytes(key, data, content_type)
    return (
        GenerationAssetRecord(
            id=asset_id,
            job_id=record.id,
            account_id=record.account_id,
            asset_type="result",
            file_name=f"{asset_id}{extension}",
            mime_type=content_type,
            storage_key=key,
            url=url,
            status="completed",
            analysis="",
            error="",
            meta={"source": "b64_json", "index": index, "revisedPrompt": revised_prompt},
            created_at=now,
        ),
        {"url": url, "revisedPrompt": revised_prompt},
    )


def _decode_generated_image(raw_b64: str) -> tuple[bytes, str, str]:
    encoded = raw_b64.strip()
    content_type = "image/png"
    if encoded.startswith("data:") and "," in encoded:
        header, encoded = encoded.split(",", 1)
        parsed_ct = header[5:].split(";", 1)[0].strip()
        if parsed_ct:
            content_type = parsed_ct
    if content_type not in IMAGE_EXTENSION_BY_CONTENT_TYPE:
        raise ValueError(f"image generation returned unsupported content type: {content_type}")
    try:
        data = base64.b64decode(encoded, validate=True)
    except binascii.Error as exc:
        raise ValueError("image generation returned invalid b64_json") from exc
    if not data:
        raise ValueError("image generation returned empty b64_json")
    ensure_size_within_limit(
        len(data),
        limit=settings.max_generated_image_bytes,
        label="generated image",
    )
    return data, content_type, IMAGE_EXTENSION_BY_CONTENT_TYPE[content_type]


def _revised_prompt(item: dict[str, Any]) -> str:
    return str(item.get("revisedPrompt") or item.get("revised_prompt") or "").strip()


def _storage_key(key: str) -> str:
    upload_dir = settings.object_storage_upload_dir
    if not upload_dir:
        return key
    return f"{upload_dir}/{key.lstrip('/')}"


def cleanup_storage_objects(storage: Any, keys: list[str]) -> None:
    for key in keys:
        for method_name in ("delete_object", "delete_bytes", "delete"):
            delete_method = getattr(storage, method_name, None)
            if not callable(delete_method):
                continue
            try:
                delete_method(key)
            except Exception:
                pass
            break


# ---------------------------------------------------------------------------
# slot / prompt helpers
# ---------------------------------------------------------------------------

def _build_slot_generation_prompt(base_prompt: str, slot: dict[str, Any], refinement: str = "") -> str:
    lines = [str(base_prompt or "").strip()]
    source_prompt = str(slot.get("sourcePrompt") or "").strip()
    if source_prompt:
        lines.append(f"单图参考: {source_prompt}")
    if refinement:
        lines.append(f"用户微调: {refinement}")
    return "\n\n".join(line for line in lines if line)


def _image_input_references(record: Any) -> list[dict[str, Any]]:
    references: list[dict[str, Any]] = []
    input_payload = record.input_payload or {}
    reference_strength = input_payload.get("referenceStrength")
    material_strength = input_payload.get("materialStrength")
    for asset in sorted(getattr(record, "assets", []) or [], key=lambda item: item.created_at):
        if asset.asset_type not in {"reference", "material"}:
            continue
        strength = (asset.meta or {}).get("strength")
        if strength is None:
            strength = reference_strength if asset.asset_type == "reference" else material_strength
        references.append({"type": asset.asset_type, "url": asset.url, "strength": strength})
    return references


def _append_image_input_prompt(prompt: str, input_references: list[dict[str, Any]]) -> str:
    if not input_references:
        return str(prompt or "").strip()
    lines = [str(prompt or "").strip(), "图片输入说明:"]
    for index, item in enumerate(input_references, start=1):
        image_type = str(item.get("type") or "")
        strength = item.get("strength")
        if image_type == "reference":
            lines.append(f"{index}. 参考图: 用于参考构图、风格、主体特征；参考强度 {strength}。")
        elif image_type == "material":
            lines.append(f"{index}. 素材图: 需要作为画面元素融入生成结果；素材融合强度 {strength}。")
    return "\n\n".join(line for line in lines if line)


def _join_parent_prompt(image_prompts: list[dict[str, str]]) -> str:
    prompts = [str(item.get("prompt") or "").strip() for item in image_prompts]
    prompts = [p for p in prompts if p]
    return "\n\n".join(prompts)


# ---------------------------------------------------------------------------
# script rewrite result parsing
# ---------------------------------------------------------------------------

def parse_script_rewrite_result(raw_text: Any) -> dict[str, Any]:
    text = str(raw_text or "").strip()
    if not text:
        raise ValueError("脚本改写结果为空，请重试")
    parsed = normalize_json(text)
    if parsed is None:
        raise ValueError("脚本改写结果格式异常，请重试")

    raw_script = parsed.get("script")
    if isinstance(raw_script, list):
        script_lines = [str(line).strip() for line in raw_script if str(line or "").strip()]
    elif isinstance(raw_script, str) and raw_script.strip():
        script_lines = [line.strip() for line in raw_script.splitlines() if line.strip()]
    else:
        script_lines = []
    if not script_lines:
        raise ValueError("脚本改写结果缺少 script 字段，请重试")

    return {
        "script": script_lines,
        "hookSuggestion": str(parsed.get("hookSuggestion") or parsed.get("hook_suggestion") or "").strip(),
        "rhythmNote": str(parsed.get("rhythmNote") or parsed.get("rhythm_note") or "").strip(),
    }


# ---------------------------------------------------------------------------
# image prompt rewrite parsing
# ---------------------------------------------------------------------------

def parse_image_prompt_rewrite_result(
    raw_text: str,
    originals: list[dict[str, str]],
) -> list[dict[str, str]]:
    parsed = normalize_json(raw_text)
    raw_items: Any = None
    if isinstance(parsed, dict):
        raw_items = parsed.get("imagePrompts") or parsed.get("prompts")
    elif isinstance(parsed, list):
        raw_items = parsed

    if isinstance(raw_items, list):
        prompts_by_asset_id: dict[str, str] = {}
        positional_prompts: list[str] = []
        for item in raw_items:
            if isinstance(item, dict):
                prompt = str(item.get("prompt") or item.get("imagePrompt") or "").strip()
                asset_id = str(item.get("assetId") or item.get("asset_id") or "").strip()
                if prompt and asset_id:
                    prompts_by_asset_id[asset_id] = prompt
                if prompt:
                    positional_prompts.append(prompt)
            else:
                prompt = str(item or "").strip()
                if prompt:
                    positional_prompts.append(prompt)
        rewritten: list[dict[str, str]] = []
        for index, original in enumerate(originals):
            asset_id = str(original.get("assetId") or "")
            prompt = prompts_by_asset_id.get(asset_id)
            if not prompt and index < len(positional_prompts):
                prompt = positional_prompts[index]
            rewritten.append({**original, "prompt": prompt or str(original.get("prompt") or "").strip()})
        if any(item["prompt"] for item in rewritten):
            return rewritten

    clean_text = str(raw_text or "").strip()
    if len(originals) == 1:
        return [{**originals[0], "prompt": clean_text or str(originals[0].get("prompt") or "").strip()}]
    return [
        {**item, "prompt": clean_text if not item.get("prompt") else f"{clean_text}\n\n单图参考: {item['prompt']}"}
        for item in originals
    ]


# ---------------------------------------------------------------------------
# unified prompt builder for PromptWorkflow
# ---------------------------------------------------------------------------

def build_unified_prompt_user(
    *,
    record: Any,
    analyses: list[str],
    image_prompts: list[dict[str, str]],
    knowledge_context: str,
) -> tuple[str, bool]:
    truncated = False
    copy_text, was_truncated = _truncate_prompt_text(record.copy_text or "", PROMPT_COPY_TEXT_LIMIT)
    truncated = truncated or was_truncated
    bounded_analyses, was_truncated = _truncate_prompt_items(
        analyses,
        total_limit=PROMPT_ANALYSES_TOTAL_LIMIT,
        item_limit=PROMPT_ANALYSIS_ITEM_LIMIT,
    )
    truncated = truncated or was_truncated
    knowledge, was_truncated = _truncate_prompt_text(knowledge_context, PROMPT_KNOWLEDGE_CONTEXT_LIMIT)
    truncated = truncated or was_truncated
    bounded_image_prompts = []
    for item in image_prompts:
        prompt, pt = _truncate_prompt_text(str(item.get("prompt") or ""), PROMPT_ANALYSIS_ITEM_LIMIT)
        analysis, at = _truncate_prompt_text(str(item.get("analysis") or ""), PROMPT_ANALYSIS_ITEM_LIMIT)
        truncated = truncated or pt or at
        bounded_image_prompts.append({**item, "prompt": prompt, "analysis": analysis})
    image_prompts_json, was_truncated = _truncate_prompt_text(
        json.dumps(bounded_image_prompts, ensure_ascii=False),
        PROMPT_IMAGE_PROMPTS_JSON_LIMIT,
    )
    truncated = truncated or was_truncated
    base = build_prompt_generation_user(
        target_platform=record.target_platform,
        topic_title=record.topic_title,
        copy_text=copy_text,
        analyses=bounded_analyses,
    )
    prompt = (
        f"{base}\n\n"
        "请基于以上每张图片的结构化分析，分别改写每一张图片的最终生图提示词。"
        "不要输出统一归纳总结；输入有几张图，就必须输出几条一一对应的 prompt。"
        "每条 prompt 都需要保留该单图的主体、构图和视觉差异，同时融合账号知识库、平台风格、文案诉求。"
        "请严格输出 JSON，格式为 {\"imagePrompts\":[{\"assetId\":\"对应 assetId\",\"prompt\":\"单张图改写后的生图提示词\"}]}，"
        "不要输出 markdown 或解释文字。\n\n"
        f"账号知识库:\n{knowledge or '无'}\n\n"
        f"每张图 prompt 草案:\n{image_prompts_json}"
    )
    prompt, was_truncated = _truncate_prompt_text(prompt, PROMPT_GENERATION_USER_LIMIT)
    return prompt, truncated or was_truncated


def _truncate_prompt_text(value: Any, limit: int) -> tuple[str, bool]:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text, False
    marker = "\n...(因输入过长已截断)"
    return f"{text[: max(0, limit - len(marker))]}{marker}", True


def _truncate_prompt_items(items: list[str], *, total_limit: int, item_limit: int) -> tuple[list[str], bool]:
    truncated = False
    bounded: list[str] = []
    remaining = total_limit
    for item in items:
        if remaining <= 0:
            truncated = True
            break
        item_text, item_truncated = _truncate_prompt_text(item, min(item_limit, remaining))
        truncated = truncated or item_truncated
        bounded.append(item_text)
        remaining -= len(item_text)
    if len(bounded) < len(items):
        truncated = True
    return bounded, truncated
