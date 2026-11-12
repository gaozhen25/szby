from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable


@dataclass(frozen=True)
class SubtitleCue:
    content: str
    start_seconds: float
    end_seconds: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "content": self.content,
            "startSeconds": self.start_seconds,
            "endSeconds": self.end_seconds,
        }


def subtitle_cues_from_payload(value: Any) -> tuple[SubtitleCue, ...]:
    if not isinstance(value, list):
        return ()
    cues: list[SubtitleCue] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        content = str(item.get("content") or "").strip()
        try:
            start = float(item.get("startSeconds"))
            end = float(item.get("endSeconds"))
        except (TypeError, ValueError):
            continue
        if content and start >= 0 and end > start:
            cues.append(SubtitleCue(content, start, end))
    return tuple(sorted(cues, key=lambda cue: (cue.start_seconds, cue.end_seconds)))


def build_timed_subtitle_cues(
    sentences: Iterable[dict[str, Any]],
    *,
    max_chars: int = 18,
) -> tuple[SubtitleCue, ...]:
    """把 CosyVoice 的字级时间戳映射回原始文案，生成可直接用于 ICE 的字幕。"""
    cues: list[SubtitleCue] = []
    last_end = 0.0
    for sentence in sentences:
        text = str(sentence.get("text") or "")
        words = _valid_words(sentence.get("words"))
        if not text.strip() or not words:
            continue
        # CosyVoice 后续 sentence 的 begin_index/end_index 是相对整篇输入
        # 文案的全局索引，而 original_text 是当前 sentence 的局部文本。
        # 归一化到当前 sentence，否则长文案从第二段开始无法命中字幕。
        sentence_index_offset = min(word["begin_index"] for word in words)
        for content, span_start, span_end in _subtitle_spans(text, max_chars):
            matched = [
                word
                for word in words
                if word["end_index"] - sentence_index_offset > span_start
                and word["begin_index"] - sentence_index_offset < span_end
            ]
            if not matched:
                continue
            start = max(0.0, matched[0]["begin_time"] / 1000)
            end = max(start + 0.1, matched[-1]["end_time"] / 1000)
            # 时间戳应当全局递增。对供应商偶发的毫秒级交叠做收敛，
            # 避免 ICE 同一字幕轨出现重叠片段。
            start = max(start, last_end)
            end = max(start + 0.1, end)
            cues.append(
                SubtitleCue(
                    content=content,
                    start_seconds=round(start, 3),
                    end_seconds=round(end, 3),
                )
            )
            last_end = end
    return tuple(cues)


def timed_subtitle_cues_are_complete(
    cues: Iterable[SubtitleCue],
    script_text: str,
    *,
    minimum_coverage: float = 0.9,
) -> bool:
    expected = _comparable_text(script_text)
    if not expected:
        return True
    actual = _comparable_text("".join(cue.content for cue in cues))
    return len(actual) / len(expected) >= minimum_coverage


def _valid_words(value: Any) -> list[dict[str, int]]:
    if not isinstance(value, list):
        return []
    words: list[dict[str, int]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        try:
            begin_index = int(item.get("begin_index"))
            end_index = int(item.get("end_index"))
            begin_time = int(item.get("begin_time"))
            end_time = int(item.get("end_time"))
        except (TypeError, ValueError):
            continue
        if (
            begin_index >= 0
            and end_index > begin_index
            and begin_time >= 0
            and end_time > begin_time
        ):
            words.append(
                {
                    "begin_index": begin_index,
                    "end_index": end_index,
                    "begin_time": begin_time,
                    "end_time": end_time,
                }
            )
    return sorted(words, key=lambda word: (word["begin_time"], word["end_time"]))


def _subtitle_spans(text: str, max_chars: int) -> list[tuple[str, int, int]]:
    limit = max(1, int(max_chars))
    spans: list[tuple[str, int, int]] = []
    # 优先在自然停顿处分段，再限制单条字幕长度。
    for match in re.finditer(r".+?(?:[，。！？；,.!?;]+|$)", text, re.DOTALL):
        segment_start, segment_end = match.span()
        cursor = segment_start
        while cursor < segment_end:
            raw_end = min(cursor + limit, segment_end)
            raw = text[cursor:raw_end]
            leading = len(raw) - len(raw.lstrip())
            trailing = len(raw.rstrip())
            if trailing > leading:
                start = cursor + leading
                end = cursor + trailing
                spans.append((text[start:end], start, end))
            cursor = raw_end
    return spans


def _comparable_text(value: str) -> str:
    return re.sub(r"[\s，。！？；,.!?;]+", "", str(value or ""))
