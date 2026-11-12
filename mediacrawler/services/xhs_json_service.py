# -*- coding: utf-8 -*-
"""
从 SDK 实时爬取生成的 JSON 文件加载结构化数据。

文件命名与 ``services/sdk_json_export.py`` 一致：
    - 关键词: ``data/xhs/json/{关键词}_{日期}.json``
    - 博主:   ``data/xhs/json/{昵称}_{日期}.json``
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Optional

from tools.async_file_writer import AsyncFileWriter

from .xhs_creator_dataset import XhsCreatorDataset, XhsCreatorNote, XhsCreatorProfile
from .xhs_search_dataset import XhsSearchComment, XhsSearchDataset, XhsSearchNote

KEYWORD_DATE_JSON_PATTERN = re.compile(r"^(.+)_(\d{4}-\d{2}-\d{2})\.json$")


def _find_keyword_json_candidates(directory: Path, keyword: Optional[str] = None) -> list[Path]:
    if not directory.exists():
        return []

    safe_kw = (
        AsyncFileWriter.sanitize_filename(keyword.strip(), default="unknown_keyword")
        if keyword
        else None
    )
    candidates: list[Path] = []
    for path in directory.glob("*.json"):
        if "_comments_" in path.name:
            continue
        if safe_kw and not path.name.startswith(f"{safe_kw}_"):
            continue
        if not KEYWORD_DATE_JSON_PATTERN.match(path.name):
            continue
        candidates.append(path)
    return sorted(candidates, key=lambda p: p.stat().st_mtime, reverse=True)


def _find_creator_json_candidates(directory: Path, nickname: Optional[str] = None) -> list[Path]:
    if not directory.exists():
        return []

    old_prefixes = ("creator_", "search_", "detail_")
    candidates: list[Path] = []
    for path in directory.glob("*.json"):
        if path.name.startswith(old_prefixes) or "_comments_" in path.name:
            continue
        if nickname and not path.name.startswith(nickname):
            continue
        if not KEYWORD_DATE_JSON_PATTERN.match(path.name):
            continue
        candidates.append(path)
    return sorted(candidates, key=lambda p: p.stat().st_mtime, reverse=True)


def _load_export_payload(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"JSON 文件不存在: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON 格式无效: {path}")
    return payload.get("data", payload)


class XhsJsonService:
    """读取 ``data/xhs/json`` 下实时爬取结果，返回 Dataset 类。"""

    def __init__(self, json_dir: str | Path = "data/xhs/json"):
        self.json_dir = Path(json_dir)

    def load_search_by_keyword(
        self,
        keyword: str,
        *,
        with_comments: bool = True,
    ) -> XhsSearchDataset:
        keyword = keyword.strip()
        candidates = _find_keyword_json_candidates(self.json_dir, keyword=keyword)
        if not candidates:
            raise FileNotFoundError(
                f"在 {self.json_dir} 中未找到关键词 JSON（keyword={keyword!r}）"
            )
        return self.load_search_by_file(candidates[0], keyword=keyword, with_comments=with_comments)

    def load_search_by_file(
        self,
        json_path: str | Path,
        *,
        keyword: Optional[str] = None,
        with_comments: bool = True,
    ) -> XhsSearchDataset:
        path = Path(json_path)
        data = _load_export_payload(path)

        notes = [XhsSearchNote.model_validate(n) for n in data.get("notes", [])]
        if keyword:
            kw = keyword.strip()
            notes = [n for n in notes if (n.source_keyword or "").strip() == kw]

        comments: list[XhsSearchComment] = []
        if with_comments:
            note_ids = {n.note_id for n in notes}
            comments = [
                XhsSearchComment.model_validate(c)
                for c in data.get("comments", [])
                if c.get("note_id") in note_ids
            ]

        keywords = sorted({(n.source_keyword or "").strip() for n in notes if n.source_keyword})
        if keyword and keyword.strip() not in keywords:
            keywords = [keyword.strip()]

        return XhsSearchDataset(
            keywords=keywords,
            notes=notes,
            comments=comments,
            source_file=str(path.resolve()),
            comments_file=str(path.resolve()) if comments else "",
            note_count=len(notes),
            comment_count=len(comments),
        )

    def load_creator_by_nickname(self, nickname: str) -> XhsCreatorDataset:
        nickname = nickname.strip()
        candidates = _find_creator_json_candidates(self.json_dir, nickname=nickname)
        if not candidates:
            raise FileNotFoundError(
                f"在 {self.json_dir} 中未找到博主 JSON（nickname={nickname!r}）"
            )
        return self.load_creator_by_file(candidates[0])

    def load_creator_by_file(self, json_path: str | Path) -> XhsCreatorDataset:
        path = Path(json_path)
        data = _load_export_payload(path)
        profile_data = data.get("profile")
        profile = XhsCreatorProfile.model_validate(profile_data) if profile_data else None
        notes = [XhsCreatorNote.model_validate(n) for n in data.get("notes", [])]
        return XhsCreatorDataset(
            profile=profile,
            notes=notes,
            source_file=str(path.resolve()),
            note_count=len(notes),
        )

    def list_search_keywords(self) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        seen: set[str] = set()
        for path in _find_keyword_json_candidates(self.json_dir):
            try:
                dataset = self.load_search_by_file(path)
                for kw in dataset.keywords:
                    if kw in seen:
                        continue
                    seen.add(kw)
                    results.append(
                        {
                            "keyword": kw,
                            "file_name": path.name,
                            "file_path": str(path),
                            "note_count": dataset.note_count,
                            "modified_at": path.stat().st_mtime,
                        }
                    )
            except Exception:
                continue
        return results

    def list_creators(self) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for path in _find_creator_json_candidates(self.json_dir):
            try:
                dataset = self.load_creator_by_file(path)
                if not dataset.profile:
                    continue
                results.append(
                    {
                        "nickname": dataset.profile.nickname,
                        "file_name": path.name,
                        "file_path": str(path),
                        "fans": dataset.profile.fans,
                        "note_count": dataset.note_count,
                        "modified_at": path.stat().st_mtime,
                    }
                )
            except Exception:
                continue
        return results
