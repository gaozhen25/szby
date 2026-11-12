# -*- coding: utf-8 -*-
"""
SDK 实时爬取结果 —— JSON 落盘（关键词/博主名 + 日期，去重合并）。
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Optional

from tools.async_file_writer import AsyncFileWriter
from tools.time_util import get_current_date


def get_search_json_path(platform: str, keyword: str, *, data_root: str | Path = "data") -> Path:
    """``data/{platform}/json/{关键词}_{日期}.json``"""
    safe_name = AsyncFileWriter.sanitize_filename(keyword.strip(), default="unknown_keyword")
    directory = Path(data_root) / platform / "json"
    directory.mkdir(parents=True, exist_ok=True)
    return directory / f"{safe_name}_{get_current_date()}.json"


def get_creator_json_path(platform: str, nickname: str, *, data_root: str | Path = "data") -> Path:
    """``data/{platform}/json/{博主昵称}_{日期}.json``"""
    safe_name = AsyncFileWriter.sanitize_filename(nickname.strip(), default="unknown_creator")
    directory = Path(data_root) / platform / "json"
    directory.mkdir(parents=True, exist_ok=True)
    return directory / f"{safe_name}_{get_current_date()}.json"


def _merge_records_by_id(
    existing: list[dict[str, Any]],
    incoming: list[dict[str, Any]],
    id_field: str,
) -> list[dict[str, Any]]:
    """保留已有顺序，仅追加新 id，不覆盖已有记录。"""
    merged: dict[str, dict[str, Any]] = {}
    order: list[str] = []

    for item in existing:
        record_id = str(item.get(id_field) or "").strip()
        if not record_id or record_id in merged:
            continue
        merged[record_id] = item
        order.append(record_id)

    for item in incoming:
        record_id = str(item.get(id_field) or "").strip()
        if not record_id or record_id in merged:
            continue
        merged[record_id] = item
        order.append(record_id)

    return [merged[record_id] for record_id in order]


def _build_search_summary(data: dict[str, Any], source_file: str) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for note in data.get("notes", []):
        keyword = (note.get("source_keyword") or "").strip() or "未知关键词"
        grouped[keyword].append(note)

    keywords = sorted(grouped.keys())
    return {
        "source_file": source_file,
        "keywords": keywords,
        "note_count": len(data.get("notes", [])),
        "comment_count": len(data.get("comments", [])),
        "notes_per_keyword": {kw: len(notes) for kw, notes in grouped.items()},
    }


def merge_search_response(existing: Optional[dict[str, Any]], incoming: dict[str, Any]) -> dict[str, Any]:
    """合并两次关键词搜索 API 响应，按 ``note_id`` / ``comment_id`` 去重。"""
    if not existing:
        return incoming

    existing_data = existing.get("data", existing)
    incoming_data = incoming.get("data", incoming)

    notes = _merge_records_by_id(
        list(existing_data.get("notes", [])),
        list(incoming_data.get("notes", [])),
        "note_id",
    )
    comments = _merge_records_by_id(
        list(existing_data.get("comments", [])),
        list(incoming_data.get("comments", [])),
        "comment_id",
    )

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for note in notes:
        keyword = (note.get("source_keyword") or "").strip() or "未知关键词"
        grouped[keyword].append(note)

    data = {
        "keywords": sorted(grouped.keys()),
        "notes": notes,
        "comments": comments,
        "grouped_notes": dict(grouped),
        "summary": incoming_data.get("summary", {}),
    }
    data["summary"] = _build_search_summary(data, str(data["summary"].get("source_file", "")))

    return {"code": 0, "message": "ok", "data": data}


def merge_creator_response(existing: Optional[dict[str, Any]], incoming: dict[str, Any]) -> dict[str, Any]:
    """合并两次博主 API 响应，profile 取最新，笔记按 ``note_id`` 去重追加。"""
    if not existing:
        return incoming

    existing_data = existing.get("data", existing)
    incoming_data = incoming.get("data", incoming)

    profile = incoming_data.get("profile") or existing_data.get("profile")
    notes = _merge_records_by_id(
        list(existing_data.get("notes", [])),
        list(incoming_data.get("notes", [])),
        "note_id",
    )

    data = {
        "profile": profile,
        "notes": notes,
        "summary": incoming_data.get("summary", {}),
    }
    nickname = (profile or {}).get("nickname", "")
    data["summary"] = {
        "source_file": str(data["summary"].get("source_file", "")),
        "nickname": nickname,
        "fans": (profile or {}).get("fans", ""),
        "follows": (profile or {}).get("follows", ""),
        "ip_location": (profile or {}).get("ip_location", ""),
        "note_count": len(notes),
    }

    return {"code": 0, "message": "ok", "data": data}


def _load_json_file(path: Path) -> Optional[dict[str, Any]]:
    if not path.exists() or path.stat().st_size == 0:
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def _write_json_file(path: Path, payload: dict[str, Any]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(path.resolve())


def export_search_response(
    response: dict[str, Any],
    *,
    platform: str,
    keyword: str,
    data_root: str | Path = "data",
) -> tuple[dict[str, Any], str]:
    """
    将搜索响应写入 ``{关键词}_{日期}.json``，若文件已存在则去重合并后写回。
    """
    path = get_search_json_path(platform, keyword, data_root=data_root)
    existing = _load_json_file(path)
    merged = merge_search_response(existing, response)
    merged["data"]["summary"] = _build_search_summary(merged["data"], str(path))
    file_path = _write_json_file(path, merged)
    merged["data"]["summary"]["source_file"] = file_path
    return merged, file_path


def export_creator_response(
    response: dict[str, Any],
    *,
    platform: str,
    nickname: str,
    data_root: str | Path = "data",
) -> tuple[dict[str, Any], str]:
    """
    将博主响应写入 ``{昵称}_{日期}.json``，若文件已存在则去重合并后写回。
    """
    path = get_creator_json_path(platform, nickname, data_root=data_root)
    existing = _load_json_file(path)
    merged = merge_creator_response(existing, response)
    profile = merged["data"].get("profile") or {}
    merged["data"]["summary"] = {
        "source_file": str(path),
        "nickname": profile.get("nickname", nickname),
        "fans": profile.get("fans", ""),
        "follows": profile.get("follows", ""),
        "ip_location": profile.get("ip_location", ""),
        "note_count": len(merged["data"].get("notes", [])),
    }
    file_path = _write_json_file(path, merged)
    merged["data"]["summary"]["source_file"] = file_path
    return merged, file_path
