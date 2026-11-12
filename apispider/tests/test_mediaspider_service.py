import asyncio

import pytest

from app.services.mediaspider.models import (
    CrawlResult,
    CrawlerProgressEvent,
    CrawlerRunConfig,
    InvalidCrawlRequestError,
)
from app.services.mediaspider.service import MediaCrawlerService


def test_keyword_and_creator_calls_return_structured_results():
    captured = []

    async def runner(config, on_progress=None):
        captured.append(config)
        return CrawlResult(platform=config.platform, crawl_type=config.crawl_type)

    service = MediaCrawlerService(runner=runner)
    async def execute():
        await service.crawl_by_keyword(
            keywords="护肤, 通勤妆", platform="小红书", cookies="cookie=value"
        )
        await service.crawl_by_creator(
            creator_url="https://www.douyin.com/user/demo", cookies="cookie=value"
        )

    asyncio.run(execute())

    assert captured[0].platform == "xhs"
    assert captured[0].keywords == ["护肤", "通勤妆"]
    assert captured[1].platform == "dy"
    assert captured[1].crawl_type == "creator"


def test_service_maps_all_runtime_options():
    captured = []

    async def runner(config, on_progress=None):
        captured.append(config)
        return CrawlResult(platform=config.platform, crawl_type=config.crawl_type)

    asyncio.run(
        MediaCrawlerService(runner=runner).crawl_by_keyword(
            keywords=["美食"],
            platform="kuaishou",
            login_type="cookie",
            start_page=2,
            enable_comments=True,
            enable_sub_comments=True,
            headless=True,
            cookies="secret-cookie",
            max_comments_count=11,
            max_notes_count=22,
            max_concurrency=3,
            enable_ip_proxy=True,
            ip_proxy_pool_count=4,
            ip_proxy_provider="static",
            static_proxy_url="http://127.0.0.1:7890",
            enable_cdp_mode=True,
            cdp_connect_existing=True,
            cdp_debug_port=9333,
            custom_browser_path="/browser",
        )
    )

    config = captured[0]
    assert config.platform == "ks"
    assert config.start_page == 2
    assert config.max_notes_count == 22
    assert config.static_proxy_url == "http://127.0.0.1:7890"


def test_cookie_is_excluded_from_serialization_and_repr():
    config = CrawlerRunConfig(
        platform="xhs",
        crawl_type="search",
        keywords=["护肤"],
        cookies="super-secret",
    )

    assert "cookies" not in config.model_dump()
    assert "super-secret" not in repr(config)
    assert "super-secret" not in str(config)


@pytest.mark.parametrize(
    ("platform", "expected"),
    [("xhs", "xhs"), ("抖音", "dy"), ("快手", "ks")],
)
def test_supported_platform_aliases(platform, expected):
    async def runner(config, on_progress=None):
        return CrawlResult(platform=config.platform, crawl_type=config.crawl_type)

    result = asyncio.run(
        MediaCrawlerService(runner=runner).crawl_by_keyword(
            keywords="测试", platform=platform, cookies="cookie=value"
        )
    )
    assert result.platform == expected


def test_rejects_unsupported_platform_before_runner():
    called = False

    async def runner(config, on_progress=None):
        nonlocal called
        called = True

    with pytest.raises(InvalidCrawlRequestError, match="不支持"):
        asyncio.run(
            MediaCrawlerService(runner=runner).crawl_by_keyword(
                keywords="测试", platform="bili", cookies="cookie=value"
            )
        )
    assert called is False


def test_validation_error_does_not_expose_cookie():
    cookie = "very-secret-cookie"
    with pytest.raises(InvalidCrawlRequestError) as exc_info:
        asyncio.run(
            MediaCrawlerService().crawl_by_keyword(
                keywords="测试",
                platform="xhs",
                cookies=cookie,
                start_page=0,
            )
        )

    assert cookie not in str(exc_info.value)


def test_service_passes_progress_callback_to_runner():
    events = []

    async def runner(config, on_progress=None):
        await on_progress(
            CrawlerProgressEvent(
                platform=config.platform,
                crawlType=config.crawl_type,
                action="run_started",
                status="running",
                message="开始采集小红书",
            )
        )
        return CrawlResult(platform=config.platform, crawl_type=config.crawl_type)

    async def execute():
        await MediaCrawlerService(runner=runner).crawl_by_keyword(
            keywords=["探店"],
            platform="xhs",
            cookies="cookie=value",
            on_progress=lambda event: events.append(event),
        )

    asyncio.run(execute())
    assert [event.action for event in events] == ["run_started"]


def test_service_keeps_legacy_single_argument_runner_without_progress_callback():
    captured = []

    async def runner(config):
        captured.append(config)
        return CrawlResult(platform=config.platform, crawl_type=config.crawl_type)

    result = asyncio.run(
        MediaCrawlerService(runner=runner).crawl_by_keyword(
            keywords=["探店"], platform="xhs", cookies="cookie=value"
        )
    )

    assert result.platform == "xhs"
    assert captured[0].keywords == ["探店"]


def test_service_passes_progress_callback_to_keyword_only_runner():
    events = []

    async def runner(config, *, on_progress=None):
        await on_progress(
            CrawlerProgressEvent(
                platform=config.platform,
                crawlType=config.crawl_type,
                action="run_started",
                status="running",
                message="开始采集小红书",
            )
        )
        return CrawlResult(platform=config.platform, crawl_type=config.crawl_type)

    result = asyncio.run(
        MediaCrawlerService(runner=runner).crawl_by_keyword(
            keywords=["探店"],
            platform="xhs",
            cookies="cookie=value",
            on_progress=lambda event: events.append(event),
        )
    )

    assert result.platform == "xhs"
    assert [event.action for event in events] == ["run_started"]
