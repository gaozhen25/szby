# -*- coding: utf-8 -*-
"""Minimal response wrapper used by XhsClient profile/search helpers."""

from __future__ import annotations

from typing import Any, Dict, List, Optional


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
        result.update({"creators": creators, "contents": contents, "comments": comments})
    else:
        result.update({"contents": contents, "creators": creators, "comments": comments})
    result.update(extra)
    return result
