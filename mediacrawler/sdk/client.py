# -*- coding: utf-8 -*-
"""
小红书数据 SDK —— 统一入口。

支持两种模式:
    - **local**: 直接读取 CSV（同项目部署，性能更好）
    - **remote**: 通过 HTTP 调用 FastAPI 服务（跨服务部署）

Example::

    from sdk import XhsDataClient

    # 本地模式（推荐）
    client = XhsDataClient.local()
    dataset = client.search.load(keyword="旅游")
    records = client.search.to_db_records(dataset)

    # 远程模式
    client = XhsDataClient.remote("http://127.0.0.1:8080")
    dataset = client.search.load(keyword="旅游")
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal, Optional

import httpx

from services.xhs_creator_service import XhsCreatorService
from services.xhs_search_service import XhsSearchService

from .resources.creator import CreatorResource
from .resources.files import FilesResource
from .resources.search import SearchResource


class XhsDataClient:
    """小红书爬取数据 SDK 客户端。"""

    def __init__(
        self,
        *,
        mode: Literal["local", "remote"],
        data_dir: Path,
        data_root: Path,
        platform: str = "xhs",
        base_url: Optional[str] = None,
        timeout: float = 30.0,
    ):
        self.mode = mode
        self.platform = platform
        self.data_root = data_root
        self._csv_dir = data_dir
        self._base_url = base_url
        self._timeout = timeout

        self._search_service = XhsSearchService(data_dir=data_dir)
        self._creator_service = XhsCreatorService(data_dir=data_dir)
        self._http: Optional[httpx.Client] = None
        if mode == "remote":
            if not base_url:
                raise ValueError("remote 模式需要提供 base_url")
            self._http = httpx.Client(base_url=base_url.rstrip("/"), timeout=timeout)

        self.search = SearchResource(self)
        self.creator = CreatorResource(self)
        self.files = FilesResource(self)

    @classmethod
    def local(
        cls,
        data_dir: str | Path = "data/xhs/csv",
        *,
        platform: str = "xhs",
        data_root: str | Path | None = None,
    ) -> XhsDataClient:
        """
        创建本地模式客户端，直接读取 CSV。

        Args:
            data_dir: CSV 目录，默认 ``data/xhs/csv``。
            platform: 平台标识，默认 ``xhs``。
            data_root: 数据根目录，默认从 ``data_dir`` 推断为 ``data/``。
        """
        csv_dir = Path(data_dir)
        root = Path(data_root) if data_root is not None else _infer_data_root(csv_dir)
        return cls(mode="local", data_dir=csv_dir, data_root=root, platform=platform)

    @classmethod
    def remote(
        cls,
        base_url: str = "http://127.0.0.1:8080",
        *,
        platform: str = "xhs",
        timeout: float = 30.0,
    ) -> XhsDataClient:
        """
        创建远程模式客户端，通过 HTTP 调用 API。

        Args:
            base_url: FastAPI 服务地址。
            platform: 平台标识，默认 ``xhs``。
            timeout: 请求超时秒数。
        """
        return cls(
            mode="remote",
            data_dir=Path("data") / platform / "csv",
            data_root=Path("data"),
            platform=platform,
            base_url=base_url,
            timeout=timeout,
        )

    def close(self) -> None:
        """关闭远程 HTTP 连接。"""
        if self._http is not None:
            self._http.close()
            self._http = None

    def __enter__(self) -> XhsDataClient:
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()


def _infer_data_root(csv_dir: Path) -> Path:
    """从 ``data/xhs/csv`` 推断 ``data/`` 根目录。"""
    if csv_dir.name == "csv" and csv_dir.parent.name in {
        "xhs", "dy", "ks", "bili", "wb", "tieba", "zhihu",
    }:
        return csv_dir.parent.parent
    if csv_dir.name == "data":
        return csv_dir
    return Path("data")
