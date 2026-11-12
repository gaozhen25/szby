# -*- coding: utf-8 -*-
"""JSON 落盘：对齐 MediaCrawler / mediaspider 命名与 CrawlResult 结构。"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional


ROOT = Path(__file__).resolve().parents[2]


def sanitize_filename(name: str, default: str = "unknown") -> str:
    if not name:
        return default
    safe = re.sub(r'[\\/:*?"<>|\s]+', "_", str(name).strip())
    return safe[:80] or default


def current_date() -> str:
    return time.strftime("%Y-%m-%d")


def json_dir(platform: str) -> Path:
    path = ROOT / "data" / platform / "json"
    path.mkdir(parents=True, exist_ok=True)
    return path


def search_json_path(platform: str, keyword: str) -> Path:
    """data/{platform}/json/{关键词}_{日期}.json"""
    name = sanitize_filename(keyword, default="unknown_keyword")
    return json_dir(platform) / f"{name}_{current_date()}.json"


def creator_json_path(platform: str, nickname: str) -> Path:
    """data/{platform}/json/{昵称}_{日期}.json"""
    name = sanitize_filename(nickname, default="unknown_creator")
    return json_dir(platform) / f"{name}_{current_date()}.json"


def excel_dir(platform: str) -> Path:
    path = ROOT / "data" / platform / "excel"
    path.mkdir(parents=True, exist_ok=True)
    return path


def creator_excel_path(platform: str, nickname: str) -> Path:
    """data/{platform}/excel/{昵称}_{日期}.xlsx"""
    name = sanitize_filename(nickname, default="unknown_creator")
    return excel_dir(platform) / f"{name}_{current_date()}.xlsx"


def search_excel_path(platform: str, label: str) -> Path:
    """data/{platform}/excel/{关键词标签}_{日期}.xlsx"""
    name = sanitize_filename(label, default="search")
    return excel_dir(platform) / f"{name}_{current_date()}.xlsx"


def creator_media_dir(platform: str, nickname: str) -> Path:
    """data/{platform}/media/{昵称}/ — 图片下载缓存，便于 Excel 断点续传。"""
    path = ROOT / "data" / platform / "media" / sanitize_filename(
        nickname, default="unknown_creator"
    )
    path.mkdir(parents=True, exist_ok=True)
    return path


def checkpoint_dir(platform: str) -> Path:
    path = ROOT / "data" / platform / "checkpoints"
    path.mkdir(parents=True, exist_ok=True)
    return path


def creator_checkpoint_path(platform: str, sec_uid: str) -> Path:
    """data/{platform}/checkpoints/{sec_uid}.json"""
    name = sanitize_filename(sec_uid, default="unknown_sec")
    return checkpoint_dir(platform) / f"{name}.json"


def detail_json_path(platform: str, content_id: str) -> Path:
    """data/{platform}/json/{note_id|aweme_id}_{日期}.json"""
    name = sanitize_filename(content_id, default="unknown_content")
    return json_dir(platform) / f"{name}_{current_date()}.json"


def crawl_result(
    *,
    platform: str,
    crawl_type: str,
    keywords: Optional[List[str]] = None,
    creator_url: Optional[str] = None,
    content_url: Optional[str] = None,
    contents: Optional[List[Dict[str, Any]]] = None,
    creators: Optional[List[Dict[str, Any]]] = None,
    comments: Optional[List[Dict[str, Any]]] = None,
    **extra: Any,
) -> Dict[str, Any]:
    contents = contents or []
    creators = creators or []
    comments = comments or []
    result: Dict[str, Any] = {
        "platform": platform,
        "crawl_type": crawl_type,
        "keywords": keywords or [],
        "creator_url": creator_url,
        "content_url": content_url,
    }
    if crawl_type == "creator":
        result.update(
            {
                "creators": creators,
                "contents": contents,
                "comments": comments,
            }
        )
    else:
        result.update(
            {
                "contents": contents,
                "comments": comments,
                "creators": creators,
            }
        )
    result.update(
        {
            "content_count": len(contents),
            "comment_count": len(comments),
            "creator_count": len(creators),
            "source_operations": [],
            "discovery_warnings": [],
        }
    )
    result.update(extra)
    return result


def write_json(data: Dict[str, Any], path: Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return path.resolve()
