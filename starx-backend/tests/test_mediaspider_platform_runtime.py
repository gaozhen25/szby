"""HTTP mediaspider 适配层基础契约。"""

import asyncio

import pytest

from app.services.mediaspider.http_platforms.adapter import crawl_http_sync
from app.services.mediaspider.models import (
    CrawlerRunConfig,
    UnsupportedPlatformError,
)
from app.services.mediaspider.runtime.collector import MemoryResultCollector
from app.services.mediaspider.runtime.runner import CrawlerFactory, run_crawler
from app.services.mediaspider.service import MediaCrawlerService


def test_factory_still_lists_legacy_platform_keys():
    assert set(CrawlerFactory.CRAWLERS) == {"xhs", "dy", "ks"}


def test_ks_is_offline_in_run_crawler():
    config = CrawlerRunConfig(
        platform="ks",
        crawl_type="search",
        keywords=["test"],
        cookies="a=1",
        output_mode="memory",
    )
    with pytest.raises(UnsupportedPlatformError):
        asyncio.run(run_crawler(config))


def test_http_adapter_rejects_ks():
    config = CrawlerRunConfig(
        platform="ks",
        crawl_type="search",
        keywords=["test"],
        cookies="a=1",
        output_mode="memory",
    )
    collector = MemoryResultCollector("ks", "search", ["test"], None)
    with pytest.raises(UnsupportedPlatformError):
        crawl_http_sync(config, collector)


def test_http_adapter_maps_douyin_search(monkeypatch):
    from app.services.mediaspider.http_platforms import adapter as http_adapter

    class FakeClient:
        def __init__(self, cookie):
            self.cookie = cookie

        def search_pages(self, keyword, **kwargs):
            return {
                "contents": [
                    {"aweme_id": "1", "title": f"{keyword}-a"},
                    {"aweme_id": "2", "title": f"{keyword}-b"},
                ]
            }

    monkeypatch.setattr(http_adapter, "DouyinClient", FakeClient)
    config = CrawlerRunConfig(
        platform="dy",
        crawl_type="search",
        keywords=["足球"],
        cookies="sessionid=abc",
        max_notes_count=1,
        output_mode="memory",
    )
    collector = MemoryResultCollector("dy", "search", ["足球"], None)
    result = crawl_http_sync(config, collector)
    assert result.content_count == 1
    assert result.contents[0]["aweme_id"] == "1"


def test_service_uses_http_runner_for_keyword():
    async def fake_run(config, on_progress=None, **kwargs):
        return type(
            "R",
            (),
            {
                "platform": config.platform,
                "crawl_type": "search",
                "content_count": 2,
                "comment_count": 0,
                "creator_count": 0,
                "contents": [],
                "comments": [],
                "creators": [],
                "keywords": config.keywords,
                "creator_url": None,
                "content_url": None,
            },
        )()

    service = MediaCrawlerService(runner=fake_run)
    result = asyncio.run(
        service.crawl_by_keyword(
            keywords=["足球"],
            platform="dy",
            cookies="a=1",
        )
    )
    assert result.content_count == 2
