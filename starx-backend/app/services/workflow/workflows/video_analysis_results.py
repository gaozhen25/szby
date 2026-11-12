from __future__ import annotations

import re
from typing import Any


def normalize_video_analysis_result(value: Any) -> dict[str, Any]:
    source = value if isinstance(value, dict) else {}
    return {
        "sourceAudioUrl": _text(source.get("sourceAudioUrl") or source.get("source_audio_url")),
        "audioTimeline": _normalize_video_script(
            source.get("audioTimeline") or source.get("audio_timeline")
        ),
        "videoScript": _normalize_video_script(source.get("videoScript")),
        "shotBreakdown": _normalize_shot_breakdown(source.get("shotBreakdown")),
        "rewriteReferences": _normalize_rewrite_references(source.get("rewriteReferences")),
        "publishCopy": _text(source.get("publishCopy")),
        "replicationPrompt": str(source.get("replicationPrompt") or "").strip(),
    }


def merge_video_analysis_results(results: list[dict[str, Any]]) -> dict[str, Any]:
    merged = {
        "sourceAudioUrl": "",
        "audioTimeline": [],
        "videoScript": [],
        "shotBreakdown": [],
        "rewriteReferences": [],
        "publishCopy": "",
        "replicationPrompt": "",
    }
    publish_copies: list[str] = []
    replication_prompts: list[str] = []
    for result in results:
        normalized = normalize_video_analysis_result(result)
        if normalized["sourceAudioUrl"] and not merged["sourceAudioUrl"]:
            merged["sourceAudioUrl"] = normalized["sourceAudioUrl"]
        merged["audioTimeline"].extend(normalized["audioTimeline"])
        merged["videoScript"].extend(normalized["videoScript"])
        merged["shotBreakdown"].extend(normalized["shotBreakdown"])
        merged["rewriteReferences"].extend(normalized["rewriteReferences"])
        if normalized["publishCopy"] and normalized["publishCopy"] not in publish_copies:
            publish_copies.append(normalized["publishCopy"])
        if normalized["replicationPrompt"] and normalized["replicationPrompt"] not in replication_prompts:
            replication_prompts.append(normalized["replicationPrompt"])

    for index, shot in enumerate(merged["shotBreakdown"], start=1):
        shot["shot"] = index
    merged["publishCopy"] = "\n".join(publish_copies)
    merged["replicationPrompt"] = "\n".join(replication_prompts)
    return merged


def offset_video_analysis_result(result: dict[str, Any], offset_seconds: float) -> dict[str, Any]:
    normalized = normalize_video_analysis_result(result)
    if offset_seconds <= 0:
        return normalized
    for item in normalized["videoScript"]:
        item["timeRange"] = _offset_time_range(item.get("timeRange"), offset_seconds)
    for item in normalized["shotBreakdown"]:
        item["timeRange"] = _offset_time_range(item.get("timeRange"), offset_seconds)
    return normalized


def format_video_timestamp(seconds: float) -> str:
    total = max(int(round(seconds)), 0)
    hours, remainder = divmod(total, 3600)
    minutes, seconds_part = divmod(remainder, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{seconds_part:02d}"
    return f"{minutes:02d}:{seconds_part:02d}"


def _offset_time_range(value: Any, offset_seconds: float) -> str:
    text = _text(value)
    match = re.match(r"^\s*([0-9:.]+)\s*[-~–—至]\s*([0-9:.]+)\s*$", text)
    if not match:
        return text
    start = _parse_timestamp(match.group(1))
    end = _parse_timestamp(match.group(2))
    if start is None or end is None:
        return text
    return f"{format_video_timestamp(start + offset_seconds)}-{format_video_timestamp(end + offset_seconds)}"


def _parse_timestamp(value: str) -> float | None:
    parts = value.strip().split(":")
    if not parts or len(parts) > 3:
        return None
    try:
        numbers = [float(part) for part in parts]
    except ValueError:
        return None
    if len(numbers) == 3:
        return numbers[0] * 3600 + numbers[1] * 60 + numbers[2]
    if len(numbers) == 2:
        return numbers[0] * 60 + numbers[1]
    return numbers[0]


def _normalize_video_script(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    items: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        time_range = str(item.get("timeRange") or item.get("time_range") or "").strip()
        text = str(item.get("text") or "").strip()
        if time_range or text:
            words = item.get("words") if isinstance(item.get("words"), list) else []
            items.append({
                "timeRange": time_range,
                "beginMs": _safe_int(item.get("beginMs") or item.get("begin_ms")),
                "endMs": _safe_int(item.get("endMs") or item.get("end_ms")),
                "text": text,
                "emotion": _text(item.get("emotion")) or "neutral",
                "emotionLabel": _text(item.get("emotionLabel") or item.get("emotion_label")) or "平静",
                "language": _text(item.get("language")),
                "words": [
                    {
                        "beginMs": _safe_int(word.get("beginMs") or word.get("begin_ms")),
                        "endMs": _safe_int(word.get("endMs") or word.get("end_ms")),
                        "text": _text(word.get("text")),
                        "punctuation": _text(word.get("punctuation")),
                    }
                    for word in words
                    if isinstance(word, dict)
                ],
            })
    return items


def _normalize_shot_breakdown(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    items: list[dict[str, Any]] = []
    for index, item in enumerate(value, start=1):
        if not isinstance(item, dict):
            continue
        items.append({
            "shot": _safe_int(item.get("shot"), index),
            "image": _text(item.get("image")),
            "timeRange": _text(item.get("timeRange") or item.get("time_range")),
            "script": _text(item.get("script")),
            "scriptRole": _text(item.get("scriptRole") or item.get("script_role")),
            "visualContent": _text(item.get("visualContent") or item.get("visual_content")),
            "visualRole": _text(item.get("visualRole") or item.get("visual_role")),
            "shotSizeCamera": _text(item.get("shotSizeCamera") or item.get("shot_size_camera")),
            "shootingTechnique": _text(item.get("shootingTechnique") or item.get("shooting_technique")),
            "bgmSound": _text(item.get("bgmSound") or item.get("bgm_sound")),
            "moodPace": _text(item.get("moodPace") or item.get("mood_pace")),
            "optimizationSuggestion": _text(item.get("optimizationSuggestion") or item.get("optimization_suggestion")),
        })
    return items


def _normalize_rewrite_references(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    items: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        script = item.get("script")
        if isinstance(script, list):
            script_lines = [_text(line) for line in script if _text(line)]
        else:
            script_lines = [_text(script)] if _text(script) else []
        items.append({
            "title": _text(item.get("title")),
            "rhythm": _text(item.get("rhythm")),
            "script": script_lines,
        })
    return items


def _safe_int(value: Any, fallback: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return fallback


def _text(value: Any) -> str:
    return str(value or "").strip()
