import asyncio

import pytest

from app.services.mediaspider.models import (
    CrawlResult,
    CrawlerRunConfig,
    InvalidCrawlRequestError,
)
from app.services.mediaspider.runtime import crawler_config
from app.services.mediaspider.runtime.config_scope import CrawlerConfigScope
from app.services.mediaspider.service import MediaCrawlerService
from app.services.mediaspider.platform_resolver import resolve_creator_platform


def test_crawl_by_detail_builds_douyin_detail_config():
    captured = []

    async def runner(config, on_progress=None):
        captured.append(config)
        return CrawlResult(platform=config.platform, crawl_type=config.crawl_type)

    result = asyncio.run(
        MediaCrawlerService(runner=runner).crawl_by_detail(
            content_url="https://www.douyin.com/video/123",
            cookies="sessionid=test",
        )
    )

    assert result.crawl_type == "detail"
    assert captured[0].platform == "dy"
    assert captured[0].content_url == "https://www.douyin.com/video/123"
    assert captured[0].keywords == []
    assert captured[0].creator_url is None


@pytest.mark.parametrize(
    ("url", "platform"),
    [
        ("https://www.xiaohongshu.com/explore/note-1?xsec_token=t", "xhs"),
        ("https://v.douyin.com/short-code/", "dy"),
        ("https://www.kuaishou.com/short-video/video-1", "ks"),
    ],
)
def test_crawl_by_detail_recognizes_supported_content_urls(url, platform):
    async def runner(config, on_progress=None):
        return CrawlResult(platform=config.platform, crawl_type=config.crawl_type)

    result = asyncio.run(
        MediaCrawlerService(runner=runner).crawl_by_detail(
            content_url=url,
            cookies="cookie=value",
        )
    )

    assert result.platform == platform


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/video/1",
        "https://www.douyin.com/user/creator-1",
        "javascript:alert(1)",
    ],
)
def test_crawl_by_detail_rejects_unknown_or_creator_urls(url):
    called = False

    async def runner(config, on_progress=None):
        nonlocal called
        called = True

    with pytest.raises(InvalidCrawlRequestError):
        asyncio.run(
            MediaCrawlerService(runner=runner).crawl_by_detail(
                content_url=url,
                cookies="cookie=value",
            )
        )

    assert called is False


def test_creator_platform_rejects_insecure_http_url():
    with pytest.raises(InvalidCrawlRequestError, match="HTTPS"):
        resolve_creator_platform("http://www.douyin.com/user/creator-1")


def test_detail_config_scope_sets_and_restores_only_requested_platform_list():
    original = {
        "XHS_SPECIFIED_NOTE_URL_LIST": list(crawler_config.XHS_SPECIFIED_NOTE_URL_LIST),
        "DY_SPECIFIED_ID_LIST": list(crawler_config.DY_SPECIFIED_ID_LIST),
        "KS_SPECIFIED_ID_LIST": list(crawler_config.KS_SPECIFIED_ID_LIST),
    }
    crawler_config.XHS_SPECIFIED_NOTE_URL_LIST = ["old-xhs"]
    crawler_config.DY_SPECIFIED_ID_LIST = ["old-dy"]
    crawler_config.KS_SPECIFIED_ID_LIST = ["old-ks"]
    config = CrawlerRunConfig(
        platform="dy",
        crawl_type="detail",
        content_url="https://www.douyin.com/video/123",
        cookies="cookie=value",
    )

    try:
        with CrawlerConfigScope(config):
            assert crawler_config.XHS_SPECIFIED_NOTE_URL_LIST == []
            assert crawler_config.DY_SPECIFIED_ID_LIST == [
                "https://www.douyin.com/video/123"
            ]
            assert crawler_config.KS_SPECIFIED_ID_LIST == []

        assert crawler_config.XHS_SPECIFIED_NOTE_URL_LIST == ["old-xhs"]
        assert crawler_config.DY_SPECIFIED_ID_LIST == ["old-dy"]
        assert crawler_config.KS_SPECIFIED_ID_LIST == ["old-ks"]
    finally:
        for field, value in original.items():
            setattr(crawler_config, field, value)
