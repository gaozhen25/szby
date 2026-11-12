"""Stable result contract for manual-backed video script generation."""

from __future__ import annotations

import re
from typing import Any

from .base import normalize_json

VIDEO_SCRIPT_MANUAL_VERSION = "2026-07-10.v1"
VIDEO_SCRIPT_SCHEMA_VERSION = 3

ALLOWED_DURATIONS = {30, 60, 90, 180}
MIN_SHOT_COUNTS = {30: 4, 60: 8, 90: 12, 180: 20}
ALLOWED_CONTENT_GOALS = {"auto", "exposure", "acquisition", "conversion", "persona"}
ALLOWED_VIDEO_FORMATS = {
    "auto",
    "list_talking_head",
    "knowledge_explainer",
    "vlog_workday",
    "story_case",
    "product_service_showcase",
    "interview_dialogue",
}
ALLOWED_TONE_STYLES = {
    "auto",
    "professional",
    "conversational",
    "sharp",
    "humorous",
    "empathetic_story",
}

APPLIED_PRINCIPLES = [
    "single_goal",
    "seed_user",
    "need_solution",
    "atomic_list",
    "three_second_hook",
    "real_resources",
    "no_fabrication",
    "goal_cta",
]

_TIME_RANGE_PATTERN = re.compile(r"^(\d{2}):(\d{2})-(\d{2}):(\d{2})$")


def normalize_video_script_result(raw: Any, duration_seconds: int) -> dict[str, Any]:
    """Validate and normalize the AI result into the public video-script contract."""

    if duration_seconds not in ALLOWED_DURATIONS:
        raise ValueError("unsupported duration")

    parsed = normalize_json(raw)
    if not parsed:
        raise ValueError("视频脚本生成结果格式异常，请重试")

    goal = _required_text(parsed, "contentGoal")
    if goal not in ALLOWED_CONTENT_GOALS - {"auto"}:
        raise ValueError("视频脚本生成结果包含无效内容目的")

    draft_script = _script_lines(parsed.get("draftScript"), "draftScript")
    final_script = _normalize_final_script(parsed.get("finalScript"), duration_seconds)
    hashtags = list(
        dict.fromkeys(
            f"#{str(item).strip().lstrip('#')}"
            for item in parsed.get("hashtags") or []
            if str(item).strip().lstrip("#")
        )
    )

    return {
        "schemaVersion": VIDEO_SCRIPT_SCHEMA_VERSION,
        "manualVersion": VIDEO_SCRIPT_MANUAL_VERSION,
        "appliedPrinciples": list(APPLIED_PRINCIPLES),
        "title": _required_text(parsed, "title"),
        "contentGoal": goal,
        "contentGoalReason": _required_text(parsed, "contentGoalReason"),
        "targetAudience": _required_text(parsed, "targetAudience"),
        "coreNeed": _required_text(parsed, "coreNeed"),
        "coreSolution": _required_text(parsed, "coreSolution"),
        "draftScript": draft_script,
        "finalScript": final_script,
        "publishCopy": _required_text(parsed, "publishCopy"),
        "hashtags": hashtags,
        "bgmSuggestion": _required_text(parsed, "bgmSuggestion"),
        "hookSuggestion": _required_text(parsed, "hookSuggestion"),
        "rhythmNote": str(parsed.get("rhythmNote") or "").strip(),
        "callToAction": _required_text(parsed, "callToAction"),
    }


def _required_text(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if isinstance(value, (dict, list)):
        value = ""
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"视频脚本生成结果缺少必填字段: {key}")
    return text


def _script_lines(raw: Any, field_name: str) -> list[str]:
    if isinstance(raw, str):
        lines = [line.strip() for line in raw.splitlines() if line.strip()]
    elif isinstance(raw, list):
        lines = [
            str(line).strip()
            for line in raw
            if not isinstance(line, (dict, list)) and str(line).strip()
        ]
    else:
        lines = []
    if not lines:
        raise ValueError(f"视频脚本生成结果缺少有效脚本: {field_name}")
    return lines


def _parse_time_range(value: Any) -> tuple[int, int]:
    text = str(value or "").strip()
    matched = _TIME_RANGE_PATTERN.fullmatch(text)
    if not matched:
        raise ValueError("finalScript time ranges must cover requested duration")
    start_minute, start_second, end_minute, end_second = (
        int(part) for part in matched.groups()
    )
    if start_second >= 60 or end_second >= 60:
        raise ValueError("finalScript time ranges must cover requested duration")
    start = start_minute * 60 + start_second
    end = end_minute * 60 + end_second
    if end <= start:
        raise ValueError("finalScript time ranges must cover requested duration")
    return start, end


def _normalize_final_script(raw: Any, duration_seconds: int) -> list[dict[str, Any]]:
    if not isinstance(raw, list) or not raw:
        raise ValueError("视频脚本生成结果缺少有效脚本: finalScript")

    normalized: list[dict[str, Any]] = []
    expected_start = 0
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ValueError("视频脚本生成结果缺少有效脚本: finalScript")
        time_range = str(item.get("timeRange") or "").strip()
        start, end = _parse_time_range(time_range)
        if start != expected_start or end > duration_seconds:
            raise ValueError("finalScript time ranges must cover requested duration")
        narration = str(item.get("narration") or item.get("text") or "").strip()
        if not narration:
            raise ValueError("视频脚本生成结果缺少必填字段: narration")
        purpose = _required_text(item, "purpose")
        visual = _required_text(item, "visual")
        shot_size_camera = _required_alias_text(
            item, "shotSizeCamera", "shot_size_camera"
        )
        shooting_technique = _required_alias_text(
            item, "shootingTechnique", "shooting_technique"
        )
        subtitle = _required_text(item, "subtitle")
        bgm_sound = _required_alias_text(item, "bgmSound", "bgm_sound")
        sound_narration = str(
            item.get("soundNarration")
            or item.get("sound_narration")
            or ""
        ).strip()
        if not sound_narration:
            sound_narration = "；".join(
                value for value in (narration, bgm_sound) if value
            )
        normalized.append(
            {
                "shotNumber": index + 1,
                "timeRange": time_range,
                "text": narration,
                "narration": narration,
                "soundNarration": sound_narration,
                "purpose": purpose,
                "visual": visual,
                "shotSizeCamera": shot_size_camera,
                "shootingTechnique": shooting_technique,
                "subtitle": subtitle,
                "bgmSound": bgm_sound,
            }
        )
        expected_start = end

    if expected_start != duration_seconds:
        raise ValueError("finalScript time ranges must cover requested duration")
    if len(normalized) < MIN_SHOT_COUNTS[duration_seconds]:
        raise ValueError(
            f"视频脚本生成结果分镜数量不足，{duration_seconds} 秒视频至少需要 "
            f"{MIN_SHOT_COUNTS[duration_seconds]} 个镜头"
        )
    return normalized


def _required_alias_text(item: dict[str, Any], primary: str, alias: str) -> str:
    raw = item.get(primary) or item.get(alias)
    if isinstance(raw, (dict, list)):
        raw = ""
    value = str(raw or "").strip()
    if not value:
        raise ValueError(f"视频脚本生成结果缺少必填字段: {primary}")
    return value
