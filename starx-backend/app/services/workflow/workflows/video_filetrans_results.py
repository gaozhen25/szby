"""Qwen3-ASR-Flash-Filetrans 结果标准化与绝对时间轴恢复。"""

from __future__ import annotations

import re
from typing import Any

EMOTION_LABELS = {
    "neutral": "平静",
    "happy": "愉快",
    "sad": "悲伤",
    "angry": "愤怒",
    "fearful": "恐惧",
    "surprised": "惊讶",
    "disgusted": "厌恶",
}


def normalize_filetrans_timeline(
    payload: Any,
    *,
    chunk_start_seconds: float,
    chunk_duration_seconds: float,
) -> list[dict[str, Any]]:
    transcripts = _find_transcripts(payload)
    offset_ms = max(int(round(chunk_start_seconds * 1000)), 0)
    timeline: list[dict[str, Any]] = []
    for transcript in transcripts:
        if not isinstance(transcript, dict):
            continue
        sentences = transcript.get("sentences")
        if isinstance(sentences, list):
            for sentence in sentences:
                normalized = _normalize_sentence(sentence, offset_ms)
                if normalized:
                    timeline.append(normalized)

    if timeline:
        return sorted(timeline, key=lambda item: (item["beginMs"], item["endMs"]))

    fallback_text = _first_transcript_text(transcripts)
    if not fallback_text:
        return []
    begin_ms = offset_ms
    end_ms = offset_ms + max(int(round(chunk_duration_seconds * 1000)), 0)
    return [{
        "timeRange": _format_millisecond_range(begin_ms, end_ms),
        "beginMs": begin_ms,
        "endMs": end_ms,
        "text": fallback_text,
        "emotion": "neutral",
        "emotionLabel": EMOTION_LABELS["neutral"],
        "language": "",
        "words": [],
    }]


def normalize_flash_fallback_timeline(
    transcript: Any,
    *,
    chunk_start_seconds: float,
    chunk_duration_seconds: float,
) -> list[dict[str, Any]]:
    """将同步 ASR 文本按句长近似映射到当前波形片段。"""
    text = str(transcript or "").strip()
    if not text:
        return []
    sentences = [
        part.strip()
        for part in re.findall(r"[^。！？!?；;\n]+[。！？!?；;]?", text)
        if part.strip()
    ] or [text]
    offset_ms = max(int(round(chunk_start_seconds * 1000)), 0)
    duration_ms = max(int(round(chunk_duration_seconds * 1000)), 0)
    weights = [max(len(re.sub(r"\s+", "", sentence)), 1) for sentence in sentences]
    total_weight = max(sum(weights), 1)
    elapsed_weight = 0
    timeline: list[dict[str, Any]] = []
    for index, (sentence, weight) in enumerate(zip(sentences, weights, strict=True)):
        begin_ms = offset_ms + round(duration_ms * elapsed_weight / total_weight)
        elapsed_weight += weight
        end_ms = (
            offset_ms + duration_ms
            if index == len(sentences) - 1
            else offset_ms + round(duration_ms * elapsed_weight / total_weight)
        )
        timeline.append({
            "timeRange": _format_millisecond_range(begin_ms, end_ms),
            "beginMs": begin_ms,
            "endMs": max(end_ms, begin_ms),
            "text": sentence,
            "emotion": "neutral",
            "emotionLabel": EMOTION_LABELS["neutral"],
            "language": "",
            "words": [],
        })
    return timeline


def _normalize_sentence(value: Any, offset_ms: int) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    text = str(value.get("text") or "").strip()
    begin_ms = offset_ms + _safe_milliseconds(value.get("begin_time"))
    end_ms = offset_ms + _safe_milliseconds(value.get("end_time"))
    if end_ms < begin_ms:
        end_ms = begin_ms
    emotion = str(value.get("emotion") or "neutral").strip().lower() or "neutral"
    words = _normalize_words(value.get("words"), offset_ms)
    if not text and not words:
        return None
    return {
        "timeRange": _format_millisecond_range(begin_ms, end_ms),
        "beginMs": begin_ms,
        "endMs": end_ms,
        "text": text,
        "emotion": emotion,
        "emotionLabel": EMOTION_LABELS.get(emotion, emotion),
        "language": str(value.get("language") or "").strip(),
        "words": words,
    }


def _normalize_words(value: Any, offset_ms: int) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    words: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        begin_ms = offset_ms + _safe_milliseconds(item.get("begin_time"))
        end_ms = offset_ms + _safe_milliseconds(item.get("end_time"))
        words.append({
            "beginMs": begin_ms,
            "endMs": max(end_ms, begin_ms),
            "text": str(item.get("text") or "").strip(),
            "punctuation": str(item.get("punctuation") or "").strip(),
        })
    return words


def _find_transcripts(value: Any) -> list[Any]:
    if isinstance(value, dict):
        transcripts = value.get("transcripts")
        if isinstance(transcripts, list):
            return transcripts
        for child in value.values():
            found = _find_transcripts(child)
            if found:
                return found
    elif isinstance(value, list):
        for child in value:
            found = _find_transcripts(child)
            if found:
                return found
    return []


def _first_transcript_text(transcripts: list[Any]) -> str:
    for transcript in transcripts:
        if isinstance(transcript, dict):
            text = str(transcript.get("text") or "").strip()
            if text:
                return text
    return ""


def _safe_milliseconds(value: Any) -> int:
    try:
        return max(int(float(value or 0)), 0)
    except (TypeError, ValueError):
        return 0


def _format_millisecond_range(begin_ms: int, end_ms: int) -> str:
    return f"{_format_milliseconds(begin_ms)}-{_format_milliseconds(end_ms)}"


def _format_milliseconds(value: int) -> str:
    total_ms = max(int(value), 0)
    total_seconds, milliseconds = divmod(total_ms, 1000)
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}.{milliseconds:03d}"
    return f"{minutes:02d}:{seconds:02d}.{milliseconds:03d}"
