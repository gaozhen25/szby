# -*- coding: utf-8 -*-
"""
MediaCrawler 小红书数据 SDK。

- **爬虫侧**：``keyword_ex(platform, keyword) -> dict`` / ``creator_ex(...) -> dict``
- **后端侧**：``XhsBackendClient.archive.local()`` — 读 ``data/xhs/json/``，返回 dict

快速上手（爬虫）::

    from sdk import keyword_ex
    result = keyword_ex("xhs", "旅游")
    print(result["data"]["summary"]["note_count"])

快速上手（后端，读 JSON）::

    from sdk import XhsBackendClient
    result = XhsBackendClient.archive.local().search("旅游")
    print(result["data"]["summary"]["note_count"])
"""

from services.xhs_creator_dataset import (
    XhsCreatorDataset,
    XhsCreatorNote,
    XhsCreatorProfile,
)
from services.xhs_search_dataset import (
    XhsSearchComment,
    XhsSearchDataset,
    XhsSearchNote,
)

from .backend_client import XhsBackendClient
from .client import XhsDataClient
from .exceptions import ApiError, NotFoundError, SdkError
from .extractor import (
    MediaCrawlerSDK,
    creator_ex,
    creator_ex_async,
    keyword_ex,
    keyword_ex_async,
)

__all__ = [
    "XhsDataClient",
    "XhsBackendClient",
    "MediaCrawlerSDK",
    "keyword_ex",
    "keyword_ex_async",
    "creator_ex",
    "creator_ex_async",
    "SdkError",
    "NotFoundError",
    "ApiError",
    # 数据模型（与 services 保持一致）
    "XhsSearchNote",
    "XhsSearchComment",
    "XhsSearchDataset",
    "XhsCreatorProfile",
    "XhsCreatorNote",
    "XhsCreatorDataset",
]
