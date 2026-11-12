# -*- coding: utf-8 -*-
"""博主数据资源。"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

from services.xhs_creator_dataset import (
    XhsCreatorDataset,
    XhsCreatorNote,
    XhsCreatorProfile,
)
from services.xhs_creator_service import XhsCreatorService

from .._http import request_json

if TYPE_CHECKING:
    from ..client import XhsDataClient


class CreatorResource:
    """博主合并 CSV 的读写入口。"""

    def __init__(self, client: XhsDataClient):
        self._client = client

    def load(
        self,
        *,
        nickname: Optional[str] = None,
        file_path: Optional[str | Path] = None,
    ) -> XhsCreatorDataset:
        """
        加载博主结构化数据，返回 ``XhsCreatorDataset``。

        Args:
            nickname: 博主昵称，匹配 ``{昵称}_*.csv`` 最新文件。
            file_path: 指定 CSV 路径。
        """
        if self._client.mode == "local":
            return self._load_local(nickname=nickname, file_path=file_path)
        return self._load_remote(nickname=nickname, file_path=str(file_path) if file_path else None)

    def export(
        self,
        *,
        nickname: Optional[str] = None,
        file_path: Optional[str | Path] = None,
    ) -> dict[str, Any]:
        """返回与 HTTP ``/api/data/creator-export`` 一致的数据结构。"""
        dataset = self.load(nickname=nickname, file_path=file_path)
        return dataset.to_dict()

    def summary(self, *, nickname: Optional[str] = None) -> dict[str, Any]:
        """返回博主数据摘要。"""
        if self._client.mode == "local":
            dataset = self._client._creator_service.load_by_nickname(nickname) if nickname else self._client._creator_service.load_latest()
            return dataset.summary()

        return request_json(
            self._client._http,
            "GET",
            "/api/data/creator-export/summary",
            params=self._remote_params(nickname=nickname),
        )

    def list_available(self) -> list[dict[str, Any]]:
        """列出目录下所有博主 CSV 摘要。"""
        if self._client.mode == "local":
            return self._client._creator_service.list_available_creators()

        results: list[dict[str, Any]] = []
        for item in self._client.files.list(platform=self._client.platform, file_type="csv"):
            rel_path = item.get("path", "")
            if not rel_path or rel_path.startswith(("creator_", "search_", "detail_")):
                continue
            try:
                dataset = self.load(file_path=rel_path)
            except Exception:
                continue
            if dataset.profile is None and not dataset.notes:
                continue
            results.append(
                {
                    "file_name": item.get("name", ""),
                    "file_path": rel_path,
                    "nickname": dataset.profile.nickname if dataset.profile else "",
                    "fans": dataset.profile.fans if dataset.profile else "",
                    "note_count": dataset.note_count,
                    "modified_at": item.get("modified_at"),
                }
            )
        return results

    def to_db_records(self, dataset: XhsCreatorDataset) -> dict[str, Any]:
        """转换为入库结构。"""
        return self._client._creator_service.to_db_records(dataset)

    def _load_local(
        self,
        *,
        nickname: Optional[str],
        file_path: Optional[str | Path],
    ) -> XhsCreatorDataset:
        service = self._client._creator_service
        if file_path is not None:
            return service.load_by_file(file_path)
        if nickname is not None:
            return service.load_by_nickname(nickname)
        return service.load_latest()

    def _load_remote(
        self,
        *,
        nickname: Optional[str],
        file_path: Optional[str],
    ) -> XhsCreatorDataset:
        payload = request_json(
            self._client._http,
            "GET",
            "/api/data/creator-export",
            params={
                **self._remote_params(nickname=nickname),
                "file_path": file_path,
            },
        )
        profile_data = payload.get("profile")
        return XhsCreatorDataset(
            profile=XhsCreatorProfile.model_validate(profile_data) if profile_data else None,
            notes=[XhsCreatorNote.model_validate(n) for n in payload.get("notes", [])],
            source_file=payload.get("source_file", ""),
            note_count=payload.get("note_count", len(payload.get("notes", []))),
        )

    def _remote_params(self, *, nickname: Optional[str] = None) -> dict[str, Any]:
        params: dict[str, Any] = {"platform": self._client.platform}
        if nickname is not None:
            params["nickname"] = nickname
        return params
