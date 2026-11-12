# -*- coding: utf-8 -*-
"""
services 包 —— CSV 数据访问底层实现与程序化爬虫入口。

新代码请优先使用 ``sdk`` 包（``from sdk import XhsDataClient`` 或 ``MediaCrawlerSDK``），
本包仍保留供 SDK 与历史代码复用。

模块说明:
    - xhs_creator_dataset.py / xhs_creator_service.py : 博主爬取
    - xhs_search_dataset.py  / xhs_search_service.py  : 关键词搜索爬取
    - crawler_runner.py                               : SDK 实时爬取入口
"""

from .crawler_runner import run_creator_crawl, run_keyword_search
from .xhs_json_service import XhsJsonService

from .xhs_creator_dataset import (
    XhsCreatorDataset,
    XhsCreatorNote,
    XhsCreatorProfile,
)
from .xhs_creator_service import XhsCreatorService
from .xhs_search_dataset import (
    XhsSearchComment,
    XhsSearchDataset,
    XhsSearchNote,
)
from .xhs_search_service import XhsSearchService

__all__ = [
    # 博主模式
    "XhsCreatorProfile",
    "XhsCreatorNote",
    "XhsCreatorDataset",
    "XhsCreatorService",
    # 关键词搜索模式
    "XhsSearchNote",
    "XhsSearchComment",
    "XhsSearchDataset",
    "XhsSearchService",
    # 实时爬取
    "run_keyword_search",
    "run_creator_crawl",
    "XhsJsonService",
]
