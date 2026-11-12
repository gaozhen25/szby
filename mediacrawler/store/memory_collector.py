# -*- coding: utf-8 -*-
"""SDK 爬取模式使用的内存数据收集器。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class MemoryCollector:
    """单次爬取任务在内存中累积的博主、笔记与评论。"""

    creator: dict[str, Any] | None = None
    notes: dict[str, dict[str, Any]] = field(default_factory=dict)
    comments: dict[str, dict[str, Any]] = field(default_factory=dict)

    def reset(self) -> None:
        self.creator = None
        self.notes.clear()
        self.comments.clear()

    def set_creator(self, item: dict[str, Any]) -> None:
        self.creator = item

    def upsert_note(self, item: dict[str, Any]) -> None:
        note_id = str(item.get("note_id") or "").strip()
        if not note_id:
            return
        self.notes[note_id] = item

    def upsert_comment(self, item: dict[str, Any]) -> None:
        comment_id = str(item.get("comment_id") or "").strip()
        if not comment_id:
            return
        self.comments[comment_id] = item

    def note_list(self) -> list[dict[str, Any]]:
        return list(self.notes.values())

    def comment_list(self) -> list[dict[str, Any]]:
        return list(self.comments.values())


_collector = MemoryCollector()


def get_memory_collector() -> MemoryCollector:
    return _collector


def reset_memory_collector() -> None:
    _collector.reset()
