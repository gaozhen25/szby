# -*- coding: utf-8 -*-
"""热点宝搜索榜字段归一化（对齐 MediaCrawler store.douyin.save_search_hot_board）。"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional


def _now_ts() -> int:
    return int(time.time() * 1000)


def normalize_search_item(
    item: Dict[str, Any],
    *,
    rank: int,
    sub_type: int,
    date_window: int,
) -> Dict[str, Any]:
    return {
        "rank": rank,
        "key_word": item.get("key_word") or "",
        "search_score": item.get("search_score"),
        "trends": item.get("trends") or [],
        "sub_type": sub_type,
        "date_window": date_window,
        "last_modify_ts": _now_ts(),
    }


def normalize_search_list(
    search_list: List[Dict[str, Any]],
    *,
    start_rank: int = 1,
    sub_type: int,
    date_window: int,
    limit: Optional[int] = None,
) -> List[Dict[str, Any]]:
    result: List[Dict[str, Any]] = []
    for offset, item in enumerate(search_list or []):
        if limit is not None and len(result) >= limit:
            break
        if not isinstance(item, dict):
            continue
        result.append(
            normalize_search_item(
                item,
                rank=start_rank + offset,
                sub_type=sub_type,
                date_window=date_window,
            )
        )
    return result


def normalize_board_payload(
    items: List[Dict[str, Any]],
    *,
    meta: Optional[Dict[str, Any]] = None,
    board_name: str = "搜索热点总榜",
) -> Dict[str, Any]:
    meta = meta or {}
    return {
        "code": 0,
        "message": "ok",
        "data": {
            "board_name": board_name,
            "sub_type": meta.get("sub_type"),
            "date_window": meta.get("date_window"),
            "total_count": meta.get("total_count"),
            "fetched_count": meta.get("fetched_count", len(items)),
            "items": items,
            "summary": {
                "board_name": board_name,
                "sub_type": meta.get("sub_type"),
                "date_window": meta.get("date_window"),
                "total_count": meta.get("total_count"),
                "fetched_count": meta.get("fetched_count", len(items)),
            },
        },
    }
