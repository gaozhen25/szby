# -*- coding: utf-8 -*-
"""通用文件资源（主要用于远程模式）。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional

from .._http import request_json

if TYPE_CHECKING:
    from ..client import XhsDataClient


class FilesResource:
    """数据文件列表、预览与统计。"""

    def __init__(self, client: XhsDataClient):
        self._client = client

    def list(
        self,
        *,
        platform: Optional[str] = None,
        file_type: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """列出数据文件。"""
        if self._client.mode == "local":
            return self._list_local(platform=platform, file_type=file_type)

        payload = request_json(
            self._client._http,
            "GET",
            "/api/data/files",
            params={"platform": platform, "file_type": file_type},
        )
        return payload.get("files", [])

    def preview(
        self,
        file_path: str,
        *,
        limit: int = 100,
    ) -> dict[str, Any]:
        """预览 CSV/JSON 文件内容。"""
        if self._client.mode == "local":
            return self._preview_local(file_path, limit=limit)

        return request_json(
            self._client._http,
            "GET",
            f"/api/data/files/{file_path}",
            params={"preview": True, "limit": limit},
        )

    def stats(self) -> dict[str, Any]:
        """返回数据目录统计信息。"""
        if self._client.mode == "local":
            return self._stats_local()

        return request_json(self._client._http, "GET", "/api/data/stats")

    def health(self) -> dict[str, Any]:
        """远程模式健康检查；本地模式固定返回 ok。"""
        if self._client.mode == "local":
            return {"status": "ok", "mode": "local"}
        return request_json(self._client._http, "GET", "/api/health")

    def _list_local(
        self,
        *,
        platform: Optional[str],
        file_type: Optional[str],
    ) -> list[dict[str, Any]]:
        data_dir = self._client.data_root
        if not data_dir.exists():
            return []

        files: list[dict[str, Any]] = []
        for file_path in data_dir.rglob("*"):
            if not file_path.is_file():
                continue
            if file_path.suffix.lower() not in {".json", ".csv", ".xlsx", ".xls"}:
                continue

            rel_path = str(file_path.relative_to(data_dir))
            if platform and platform.lower() not in rel_path.lower():
                continue
            if file_type and file_path.suffix[1:].lower() != file_type.lower():
                continue

            stat = file_path.stat()
            files.append(
                {
                    "name": file_path.name,
                    "path": rel_path,
                    "size": stat.st_size,
                    "modified_at": stat.st_mtime,
                    "type": file_path.suffix[1:],
                }
            )

        files.sort(key=lambda item: item["modified_at"], reverse=True)
        return files

    def _preview_local(self, file_path: str, *, limit: int) -> dict[str, Any]:
        import csv
        import json

        full_path = self._client.data_root / file_path
        if not full_path.exists():
            from ..exceptions import NotFoundError

            raise NotFoundError(f"File not found: {file_path}")

        if full_path.suffix == ".json":
            with open(full_path, encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                return {"data": data[:limit], "total": len(data)}
            return {"data": data, "total": 1}

        if full_path.suffix == ".csv":
            with open(full_path, encoding="utf-8-sig", newline="") as f:
                reader = csv.DictReader(f)
                rows = []
                for i, row in enumerate(reader):
                    if i >= limit:
                        break
                    rows.append(row)
            with open(full_path, encoding="utf-8-sig", newline="") as f:
                total = sum(1 for _ in f) - 1
            return {"data": rows, "total": total}

        raise ValueError(f"Unsupported file type for preview: {full_path.suffix}")

    def _stats_local(self) -> dict[str, Any]:
        data_dir = self._client.data_root
        stats = {
            "total_files": 0,
            "total_size": 0,
            "by_platform": {},
            "by_type": {},
        }
        if not data_dir.exists():
            return stats

        for file_path in data_dir.rglob("*"):
            if not file_path.is_file():
                continue
            if file_path.suffix.lower() not in {".json", ".csv", ".xlsx", ".xls"}:
                continue

            stat = file_path.stat()
            stats["total_files"] += 1
            stats["total_size"] += stat.st_size

            file_type = file_path.suffix[1:].lower()
            stats["by_type"][file_type] = stats["by_type"].get(file_type, 0) + 1

            rel_path = str(file_path.relative_to(data_dir))
            for platform in ["xhs", "dy", "ks", "bili", "wb", "tieba", "zhihu"]:
                if platform in rel_path.lower():
                    stats["by_platform"][platform] = stats["by_platform"].get(platform, 0) + 1
                    break

        return stats
