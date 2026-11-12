# -*- coding: utf-8 -*-
"""
后端 SDK —— 读爬虫落盘的 JSON，无需浏览器。

``XhsBackendClient.archive.local()`` 读取 ``data/xhs/json/``，返回标准 API dict。
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal, Optional, overload

import httpx

from services.xhs_creator_dataset import XhsCreatorDataset
from services.xhs_creator_service import XhsCreatorService
from services.xhs_json_service import XhsJsonService
from services.xhs_search_dataset import XhsSearchDataset
from services.xhs_search_service import XhsSearchService

from ._http import request_json

DEFAULT_LIVE_TIMEOUT = 600.0
ApiDict = dict


class XhsBackendClient:
    """
    后端数据客户端（无浏览器），读 JSON，默认返回 **dict**。

    Example::

        client = XhsBackendClient.archive.local()
        result = client.search("美女")
        print(result["data"]["summary"]["note_count"])
        print(result["data"]["notes"][0]["title"])
    """

    def __init__(
        self,
        *,
        source: Literal["live", "archive"],
        mode: Literal["local", "remote"],
        json_dir: Path,
        platform: str = "xhs",
        base_url: Optional[str] = None,
        timeout: float = 30.0,
    ):
        self.source = source
        self.mode = mode
        self.platform = platform
        self._json_dir = json_dir
        self._json_service = XhsJsonService(json_dir=json_dir)
        self._base_url = base_url
        self._timeout = timeout
        self._http: Optional[httpx.Client] = None
        if mode == "remote":
            if not base_url:
                raise ValueError("remote 模式需要提供 base_url")
            self._http = httpx.Client(base_url=base_url.rstrip("/"), timeout=timeout)

    @classmethod
    def live(
        cls,
        base_url: str = "http://127.0.0.1:8080",
        *,
        platform: str = "xhs",
        timeout: float = DEFAULT_LIVE_TIMEOUT,
    ) -> XhsBackendClient:
        """
        实时模式：请求爬虫机 API，当场爬取并返回 dict，**不读 JSON**。
        """
        return cls(
            source="live",
            mode="remote",
            json_dir=Path("data") / platform / "json",
            platform=platform,
            base_url=base_url,
            timeout=timeout,
        )

    class archive:
        """读已落盘 JSON 的历史数据（非实时）。"""

        @staticmethod
        def local(
            json_dir: str | Path = "data/xhs/json",
            *,
            platform: str = "xhs",
        ) -> XhsBackendClient:
            return XhsBackendClient(
                source="archive",
                mode="local",
                json_dir=Path(json_dir),
                platform=platform,
            )

        @staticmethod
        def remote(
            base_url: str = "http://127.0.0.1:8080",
            *,
            platform: str = "xhs",
            timeout: float = 30.0,
        ) -> XhsBackendClient:
            return XhsBackendClient(
                source="archive",
                mode="remote",
                json_dir=Path("data") / platform / "json",
                platform=platform,
                base_url=base_url,
                timeout=timeout,
            )

    @overload
    def search(
        self,
        keyword: str,
        *,
        max_notes_count: Optional[int] = 20,
        enable_comments: bool = False,
        with_comments: bool = True,
        as_dataset: Literal[False] = False,
    ) -> ApiDict: ...

    @overload
    def search(
        self,
        keyword: str,
        *,
        max_notes_count: Optional[int] = 20,
        enable_comments: bool = False,
        with_comments: bool = True,
        as_dataset: Literal[True],
    ) -> XhsSearchDataset: ...

    def search(
        self,
        keyword: str,
        *,
        max_notes_count: Optional[int] = 20,
        enable_comments: bool = False,
        with_comments: bool = True,
        as_dataset: bool = False,
    ) -> ApiDict | XhsSearchDataset:
        """关键词搜索，默认返回标准 API dict。"""
        if self.source == "live":
            payload = request_json(
                self._http,
                "POST",
                "/api/data/crawl/search",
                json_body={
                    "platform": self.platform,
                    "keyword": keyword,
                    "max_notes_count": max_notes_count,
                    "enable_comments": enable_comments,
                },
            )
            return _dataset_from_search_payload(payload, keyword=keyword) if as_dataset else payload

        if self.mode == "local":
            dataset = self._json_service.load_search_by_keyword(
                keyword, with_comments=with_comments
            )
            return dataset if as_dataset else XhsSearchService().to_api_response(dataset)

        payload = request_json(
            self._http,
            "GET",
            "/api/data/search-json",
            params={
                "platform": self.platform,
                "keyword": keyword,
                "with_comments": with_comments,
            },
        )
        return _dataset_from_search_payload(payload, keyword=keyword) if as_dataset else payload

    @overload
    def creator(
        self,
        creator_id: str,
        *,
        max_notes_count: Optional[int] = 20,
        enable_comments: bool = False,
        nickname: Optional[str] = None,
        as_dataset: Literal[False] = False,
    ) -> ApiDict: ...

    @overload
    def creator(
        self,
        creator_id: str,
        *,
        max_notes_count: Optional[int] = 20,
        enable_comments: bool = False,
        nickname: Optional[str] = None,
        as_dataset: Literal[True],
    ) -> XhsCreatorDataset: ...

    def creator(
        self,
        creator_id: str,
        *,
        max_notes_count: Optional[int] = 20,
        enable_comments: bool = False,
        nickname: Optional[str] = None,
        as_dataset: bool = False,
    ) -> ApiDict | XhsCreatorDataset:
        """
        博主数据，默认返回标准 API dict。

        实时模式传 ``creator_id``（user_id 或主页 URL）；
        归档模式传 ``nickname``（或 ``creator_id`` 作 nickname 用）。
        """
        if self.source == "live":
            payload = request_json(
                self._http,
                "POST",
                "/api/data/crawl/creator",
                json_body={
                    "platform": self.platform,
                    "creator_id": creator_id,
                    "max_notes_count": max_notes_count,
                    "enable_comments": enable_comments,
                },
            )
            return _dataset_from_creator_payload(payload) if as_dataset else payload

        name = nickname or creator_id
        if self.mode == "local":
            dataset = self._json_service.load_creator_by_nickname(name)
            return dataset if as_dataset else XhsCreatorService().to_api_response(dataset)

        payload = request_json(
            self._http,
            "GET",
            "/api/data/creator-json",
            params={"platform": self.platform, "nickname": name},
        )
        return _dataset_from_creator_payload(payload) if as_dataset else payload

    def close(self) -> None:
        if self._http is not None:
            self._http.close()
            self._http = None

    def __enter__(self) -> XhsBackendClient:
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()


def _dataset_from_search_payload(payload: dict, *, keyword: str) -> XhsSearchDataset:
    from services.xhs_search_dataset import XhsSearchComment, XhsSearchNote

    data = payload.get("data", payload)
    notes = [XhsSearchNote.model_validate(n) for n in data.get("notes", [])]
    comments = [XhsSearchComment.model_validate(c) for c in data.get("comments", [])]
    summary = data.get("summary", {})
    return XhsSearchDataset(
        keywords=data.get("keywords", [keyword]),
        notes=notes,
        comments=comments,
        source_file=summary.get("source_file", "live"),
        comments_file=summary.get("comments_file", ""),
        note_count=summary.get("note_count", len(notes)),
        comment_count=summary.get("comment_count", len(comments)),
    )


def _dataset_from_creator_payload(payload: dict) -> XhsCreatorDataset:
    from services.xhs_creator_dataset import XhsCreatorNote, XhsCreatorProfile

    data = payload.get("data", payload)
    profile_data = data.get("profile")
    profile = XhsCreatorProfile.model_validate(profile_data) if profile_data else None
    notes = [XhsCreatorNote.model_validate(n) for n in data.get("notes", [])]
    summary = data.get("summary", {})
    return XhsCreatorDataset(
        profile=profile,
        notes=notes,
        source_file=summary.get("source_file", "live"),
        note_count=summary.get("note_count", len(notes)),
    )
