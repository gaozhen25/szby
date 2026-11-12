"""Structured contract and prompt builder for topic-driven image plans."""

from __future__ import annotations

import json
import re
from typing import Any

from .base import normalize_json


IMAGE_PROMPT_PLAN_SCHEMA_VERSION = 1

ALLOWED_IMAGE_COUNTS = {1, 2, 3, 4}
ALLOWED_COLLECTION_MODES = {"independent", "series"}
ALLOWED_RATIOS = {"1:1", "3:4", "9:16", "4:3", "16:9"}
ALLOWED_CREATIVITY_LEVELS = {"low", "medium", "high"}
ALLOWED_VISUAL_STYLES = {
    "auto",
    "realistic_photography",
    "commercial_poster",
    "lifestyle_editorial",
    "illustration",
    "minimal_graphic",
}
SERIES_ROLES = {
    2: ["cover", "ending"],
    3: ["cover", "content", "ending"],
    4: ["cover", "content", "content", "ending"],
}


def normalize_image_prompt_plan(
    raw: Any,
    preferences: dict[str, Any],
) -> dict[str, Any]:
    """Normalize an AI response while keeping request metadata authoritative."""

    parsed = normalize_json(raw)
    if not parsed:
        raise ValueError("图片提示词方案格式异常，请重试")

    image_count = _allowed_preference(
        preferences,
        "imageCount",
        ALLOWED_IMAGE_COUNTS,
    )
    collection_mode = _allowed_preference(
        preferences,
        "collectionMode",
        ALLOWED_COLLECTION_MODES,
    )
    target_platform = _required_preference_text(preferences, "targetPlatform")
    ratio = _allowed_preference(preferences, "ratio", ALLOWED_RATIOS)
    creativity_level = _allowed_preference(
        preferences,
        "creativityLevel",
        ALLOWED_CREATIVITY_LEVELS,
    )
    visual_style = _allowed_preference(
        preferences,
        "visualStyle",
        ALLOWED_VISUAL_STYLES,
    )

    prompts = parsed.get("prompts")
    if not isinstance(prompts, list) or len(prompts) != image_count:
        raise ValueError(f"image prompt plan must contain exactly {image_count} prompts")

    shared_style = _plain_text(parsed.get("sharedStyle"))
    if collection_mode == "series":
        if image_count not in SERIES_ROLES:
            raise ValueError("series image prompt plan requires at least 2 prompts")
        if not shared_style:
            raise ValueError("series image prompt plan requires a shared style")
        roles = SERIES_ROLES[image_count]
    else:
        roles = ["standalone"] * image_count

    normalized_prompts = _normalize_prompt_items(
        prompts,
        roles=roles,
        shared_style=shared_style if collection_mode == "series" else "",
    )

    return {
        "schemaVersion": IMAGE_PROMPT_PLAN_SCHEMA_VERSION,
        "targetPlatform": target_platform,
        "imageCount": image_count,
        "collectionMode": collection_mode,
        "ratio": ratio,
        "creativityLevel": creativity_level,
        "visualStyle": visual_style,
        "customRequirements": _plain_text(preferences.get("customRequirements")),
        "sharedStyle": shared_style,
        "prompts": normalized_prompts,
        "negativePrompt": _plain_text(parsed.get("negativePrompt")),
        "publishCopy": _plain_text(parsed.get("publishCopy")),
        "hashtags": _hashtags(parsed.get("hashtags")),
    }


def build_image_prompt_plan_user(
    context: dict[str, Any],
    preferences: dict[str, Any],
    reference_analyses: list[str] | None = None,
) -> str:
    """Build the text-only planning prompt for a topic and confirmed preferences."""

    image_count = int(preferences.get("imageCount") or 1)
    collection_mode = str(preferences.get("collectionMode") or "independent")
    roles = (
        SERIES_ROLES.get(image_count, [])
        if collection_mode == "series"
        else ["standalone"] * image_count
    )
    output_shape = {
        "sharedStyle": (
            "主体、色彩、光线、构图和文字安全区组成的共享视觉规范"
            if collection_mode == "series"
            else "独立模式可为空字符串"
        ),
        "prompts": [
            {
                "slotId": f"topic_{index}",
                "role": role,
                "title": _example_title(role, index, roles),
                "prompt": (
                    "仅描述该页特有的主体动作、场景和信息表达"
                    if collection_mode == "series"
                    else "可直接交给生图模型的完整独立中文提示词"
                ),
            }
            for index, role in enumerate(roles, start=1)
        ],
        "negativePrompt": "低质量、模糊、畸变",
        "publishCopy": "适配目标平台的发布文案",
        "hashtags": ["#主题标签", "#人群标签"],
    }
    input_payload = {
        "topic": context.get("topic") or {},
        "account": context.get("account") or {},
        "enabledKnowledge": _enabled_knowledge(context),
        "preferences": {
            "targetPlatform": preferences.get("targetPlatform") or "",
            "imageCount": image_count,
            "collectionMode": collection_mode,
            "ratio": preferences.get("ratio") or "",
            "creativityLevel": preferences.get("creativityLevel") or "",
            "visualStyle": preferences.get("visualStyle") or "",
            "customRequirements": preferences.get("customRequirements") or "",
        },
        "referenceImageAnalyses": list(reference_analyses or []),
    }
    mode_rules = (
        "系列图要求：sharedStyle 完整定义统一主体、色彩、光线、构图和文字安全区；"
        "每项 prompt 只写该页特有的主体动作、场景和信息表达，不得重复 sharedStyle，"
        "也不要添加“共享视觉约束”或“本页画面要求”等包装标签；"
        "后端会把 sharedStyle 统一且仅一次地拼入每张最终提示词。"
        if collection_mode == "series"
        else "独立图要求：每张图都是可独立使用的创意方向，彼此不依赖上下文。"
    )
    return "\n\n".join(
        [
            "请根据输入资料策划可供用户检查、编辑后再生图的提示词方案。",
            (
                "真实性要求：只使用输入中的选题、账号和已启用知识；"
                "不得编造产品事实、案例、效果、数据或承诺。"
            ),
            (
                "参考爆款要求：referenceImageAnalyses 是从选题绑定爆款笔记原图反推得到的视觉信息；"
                "借鉴其构图、视觉节奏、色彩和信息层级，但不得照搬文字、品牌标识或可识别人物。"
            ),
            mode_rules,
            "输入资料：\n" + json.dumps(input_payload, ensure_ascii=False, indent=2),
            (
                "输出要求：\n"
                "- 只输出一个 JSON 对象，不输出 markdown、代码块、解释或前后缀。\n"
                f"- prompts 必须恰好包含 {image_count} 项，每项 prompt 都必须完整且非空。\n"
                "- 每项 title 必须是便于用户识别和编辑的非空卡片标题。\n"
                "- negativePrompt 和 publishCopy 必须是字符串，hashtags 必须是字符串数组。\n"
                "- slotId、role 和请求偏好由后端最终校准，不要添加其他图片槽位。\n"
                "JSON 精确结果示例：\n"
                + json.dumps(output_shape, ensure_ascii=False, indent=2)
            ),
        ]
    )


def _enabled_knowledge(context: dict[str, Any]) -> Any:
    knowledge_context = context.get("knowledgeContext")
    if knowledge_context:
        return knowledge_context

    knowledge = context.get("knowledge") or {}
    if isinstance(knowledge, dict):
        if "enabledFields" in knowledge:
            return knowledge.get("enabledFields") or []
        return {
            key: value
            for key, value in knowledge.items()
            if key != "disabledFields" and value
        }
    if isinstance(knowledge, list):
        return [
            item
            for item in knowledge
            if not isinstance(item, dict) or item.get("enabled", True)
        ]
    return knowledge


def _allowed_preference(
    preferences: dict[str, Any],
    key: str,
    allowed: set[Any],
) -> Any:
    value = preferences.get(key)
    if value not in allowed:
        raise ValueError(f"unsupported image preference: {key}")
    return value


def _required_preference_text(preferences: dict[str, Any], key: str) -> str:
    value = _plain_text(preferences.get(key))
    if not value:
        raise ValueError(f"missing image preference: {key}")
    return value


def _prompt_text(item: Any, index: int) -> str:
    if not isinstance(item, dict):
        raise ValueError(f"image prompt plan item {index} must contain prompt text")
    prompt = _plain_text(item.get("prompt"))
    if not prompt:
        raise ValueError(f"image prompt plan item {index} must contain prompt text")
    return prompt


def _normalize_prompt_items(
    prompts: list[Any],
    *,
    roles: list[str],
    shared_style: str,
) -> list[dict[str, str]]:
    normalized: list[dict[str, str]] = []
    for index, item in enumerate(prompts, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"image prompt plan item {index} must contain prompt text")
        title = _plain_text(item.get("title"))
        if not title:
            raise ValueError(f"image prompt plan item {index} must contain a title")
        prompt = _prompt_text(item, index)
        if shared_style:
            prompt = _compose_series_prompt(prompt, shared_style)
        normalized.append(
            {
                "slotId": f"topic_{index}",
                "role": roles[index - 1],
                "title": title,
                "prompt": prompt,
            }
        )
    return normalized


def _compose_series_prompt(prompt: str, shared_style: str) -> str:
    """Make a series prompt independently usable with one shared-style copy."""

    page_direction = _clean_page_direction(prompt, shared_style)
    shared_rule = f"共享视觉约束：{shared_style}"
    if not page_direction:
        return shared_rule
    return f"{shared_rule}\n本页画面要求：{page_direction}"


def _clean_page_direction(prompt: str, shared_style: str) -> str:
    """Remove model-added shared content and common presentation wrappers."""

    text = prompt.replace(shared_style, "")
    text = re.sub(
        r"(?:共享视觉约束|共享视觉规范|共享风格|系列共享规范)\s*[：:]",
        "",
        text,
    )
    text = re.sub(
        r"(?:本页画面要求|本页要求|页面画面要求|单页画面要求)\s*[：:]",
        "",
        text,
    )
    return text.strip(" \n\t；;，,。")


def _hashtags(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    normalized: list[str] = []
    for item in value:
        if isinstance(item, (dict, list)):
            continue
        text = str(item or "").strip().lstrip("#").strip()
        hashtag = f"#{text}" if text else ""
        if hashtag and hashtag not in normalized:
            normalized.append(hashtag)
    return normalized


def _example_title(role: str, index: int, roles: list[str]) -> str:
    if role == "cover":
        return "封面"
    if role == "ending":
        return "收尾页"
    if role == "content":
        content_index = roles[:index].count("content")
        return f"内容页 {content_index}"
    return f"独立图 {index}"


def _plain_text(value: Any) -> str:
    if isinstance(value, (dict, list)):
        return ""
    return str(value or "").strip()
