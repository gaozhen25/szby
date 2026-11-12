# -*- coding: utf-8 -*-
"""关键词搜索数据资源。"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

from services.xhs_search_dataset import (
    XhsSearchComment,
    XhsSearchDataset,
    XhsSearchNote,
)
from services.xhs_search_service import XhsSearchService

from .._http import request_json

if TYPE_CHECKING:
    from ..client import XhsDataClient


class SearchResource:
    """关键词搜索 CSV 的读写入口。"""

    def __init__(self, client: XhsDataClient):
        self._client = client

    def load(
        self,
        *,
        keyword: Optional[str] = None,
        file_path: Optional[str | Path] = None,
        with_comments: bool = False,
    ) -> XhsSearchDataset:
        """
        加载结构化搜索数据，返回 ``XhsSearchDataset``。

        Args:
            keyword: 按关键词过滤，如 ``"旅游"``。
            file_path: 指定 CSV 路径（本地模式为绝对/相对路径；远程模式为相对 ``data/`` 的路径）。
            with_comments: 是否同时加载评论。
        """
        if self._client.mode == "local":
            return self._load_local(
                keyword=keyword,
                file_path=file_path,
                with_comments=with_comments,
            )
        return self._load_remote(
            keyword=keyword,
            file_path=str(file_path) if file_path else None,
            with_comments=with_comments,
        )

    def export(
        self,
        *,
        keyword: Optional[str] = None,
        file_path: Optional[str | Path] = None,
        with_comments: bool = False,
    ) -> dict[str, Any]:
        """返回与 HTTP ``/api/data/search-export`` 一致的 API 响应体。"""
        dataset = self.load(
            keyword=keyword,
            file_path=file_path,
            with_comments=with_comments,
        )
        return self._client._search_service.to_api_response(dataset)

    def summary(self, *, keyword: Optional[str] = None) -> dict[str, Any]:
        """返回搜索数据摘要。"""
        if self._client.mode == "local":
            dataset = self._client._search_service.load_latest(keyword=keyword)
            return dataset.summary()

        payload = request_json(
            self._client._http,
            "GET",
            "/api/data/search-export/summary",
            params=self._remote_params(keyword=keyword),
        )
        return payload

    def list_available(self) -> list[dict[str, Any]]:
        """列出目录下所有关键词搜索 CSV 摘要。"""
        if self._client.mode == "local":
            return self._client._search_service.list_available_searches()

        files = self._client.files.list(platform=self._client.platform, file_type="csv")
        results: list[dict[str, Any]] = []
        for item in files:
            rel_path = item.get("path", "")
            name = item.get("name", "")
            if "_comments_" in name or not rel_path.endswith(".csv"):
                continue
            try:
                dataset = self.load(file_path=rel_path)
            except Exception:
                continue
            if not dataset.notes:
                continue
            results.append(
                {
                    "file_name": name,
                    "file_path": rel_path,
                    "keywords": dataset.keywords,
                    "note_count": dataset.note_count,
                    "modified_at": item.get("modified_at"),
                }
            )
        return results

    def to_db_records(self, dataset: XhsSearchDataset) -> dict[str, Any]:
        """转换为入库结构。"""
        return self._client._search_service.to_db_records(dataset)

    def _load_local(
        self,
        *,
        keyword: Optional[str],
        file_path: Optional[str | Path],
        with_comments: bool,
    ) -> XhsSearchDataset:
        service = self._client._search_service
        if file_path is not None:
            return service.load_by_file(file_path, keyword=keyword, with_comments=with_comments)
        return service.load_latest(keyword=keyword, with_comments=with_comments)

    def _load_remote(
        self,
        *,
        keyword: Optional[str],
        file_path: Optional[str],
        with_comments: bool,
    ) -> XhsSearchDataset:
        payload = request_json(
            self._client._http,
            "GET",
            "/api/data/search-export",
            params={
                **self._remote_params(keyword=keyword),
                "file_path": file_path,
                "with_comments": with_comments,
            },
        )
        data = payload.get("data", payload)
        summary = data.get("summary", {})
        return XhsSearchDataset(
            keywords=data.get("keywords", []),
            notes=[XhsSearchNote.model_validate(n) for n in data.get("notes", [])],
            comments=[XhsSearchComment.model_validate(c) for c in data.get("comments", [])],
            source_file=summary.get("source_file", ""),
            comments_file=summary.get("comments_file", ""),
            note_count=summary.get("note_count", len(data.get("notes", []))),
            comment_count=summary.get("comment_count", len(data.get("comments", []))),
        )

    def _remote_params(self, *, keyword: Optional[str] = None) -> dict[str, Any]:
        params: dict[str, Any] = {"platform": self._client.platform}
        if keyword is not None:
            params["keyword"] = keyword
        return params
