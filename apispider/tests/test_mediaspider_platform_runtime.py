import asyncio
import time

import pytest

from app.services.mediaspider.runtime import crawler_config
from app.services.mediaspider.runtime.collector import (
    MemoryResultCollector,
    bind_collector,
    reset_collector,
)
from app.services.mediaspider.runtime.context import (
    comment_tasks_var,
    creator_profile_var,
)
from app.services.mediaspider.vendor.cdp_browser import CDPBrowserManager


async def _noop(*args, **kwargs):
    return None


class _XhsSearchClient:
    async def get_note_by_keyword(self, *, page, **kwargs):
        return {
            "has_more": True,
            "items": [
                {
                    "id": f"xhs-{page}-{index}",
                    "xsec_source": "pc_search",
                    "xsec_token": "token",
                    "model_type": "note",
                }
                for index in range(20)
            ],
        }


class _DouyinSearchClient:
    async def search_info_by_keyword(self, *, offset, **kwargs):
        return {
            "data": [
                {
                    "aweme_info": {
                        "aweme_id": f"dy-{offset + index}",
                        "author": {},
                        "statistics": {},
                    }
                }
                for index in range(10)
            ],
            "extra": {"logid": "search-id"},
        }


class _KuaishouSearchClient:
    async def search_info_by_keyword(self, *, pcursor, **kwargs):
        page = int(pcursor)
        return {
            "visionSearchPhoto": {
                "result": 1,
                "searchSessionId": "search-id",
                "feeds": [
                    {
                        "photo": {
                            "id": f"ks-{page}-{index}",
                            "caption": "video",
                        },
                        "author": {},
                    }
                    for index in range(20)
                ],
            }
        }


async def _run_platform_search(platform, max_count):
    if platform == "xhs":
        from app.services.mediaspider.platforms.xhs.core import XiaoHongShuCrawler

        crawler = XiaoHongShuCrawler()
        crawler.xhs_client = _XhsSearchClient()

        async def get_note_detail(*, note_id, xsec_source, xsec_token, semaphore):
            return {
                "note_id": note_id,
                "xsec_token": xsec_token,
                "user": {},
                "interact_info": {},
            }

        crawler.get_note_detail_async_task = get_note_detail
        crawler.get_notice_media = _noop
        crawler.batch_get_note_comments = _noop
    elif platform == "dy":
        from app.services.mediaspider.platforms.douyin.core import DouYinCrawler

        crawler = DouYinCrawler()
        crawler.dy_client = _DouyinSearchClient()
        crawler.get_aweme_media = _noop
        crawler.batch_get_note_comments = _noop
    else:
        from app.services.mediaspider.platforms.kuaishou.core import KuaishouCrawler

        crawler = KuaishouCrawler()
        crawler.ks_client = _KuaishouSearchClient()
        crawler.batch_get_video_comments = _noop

    collector = MemoryResultCollector(platform, "search", ["测试"], None)
    token = bind_collector(collector)
    try:
        await crawler.search()
    finally:
        reset_collector(token)
    return collector.to_result()


@pytest.mark.parametrize("platform", ["xhs", "dy", "ks"])
@pytest.mark.parametrize("max_count", [1, 12])
def test_platform_search_wires_mock_client_to_real_store_with_exact_limit(
    monkeypatch, platform, max_count
):
    monkeypatch.setattr(crawler_config, "KEYWORDS", "测试")
    monkeypatch.setattr(crawler_config, "START_PAGE", 1)
    monkeypatch.setattr(crawler_config, "CRAWLER_MAX_NOTES_COUNT", max_count)
    monkeypatch.setattr(crawler_config, "CRAWLER_MAX_SLEEP_SEC", 0)

    result = asyncio.run(_run_platform_search(platform, max_count))

    assert result.content_count == max_count
    assert crawler_config.CRAWLER_MAX_NOTES_COUNT == max_count


def test_xhs_search_defaults_missing_xsec_source_to_pc_search(monkeypatch):
    from app.services.mediaspider.platforms.xhs.core import XiaoHongShuCrawler

    class SearchClientWithoutSource:
        async def get_note_by_keyword(self, **kwargs):
            return {
                "has_more": False,
                "items": [
                    {
                        "id": "6a33b902000000001700a690",
                        "xsec_token": "signed-token=",
                        "model_type": "note",
                    }
                ],
            }

    async def execute():
        crawler = XiaoHongShuCrawler()
        crawler.xhs_client = SearchClientWithoutSource()

        async def get_note_detail(
            *, note_id, xsec_source, xsec_token, semaphore
        ):  # noqa: ARG001
            return {
                "note_id": note_id,
                "xsec_source": xsec_source,
                "xsec_token": xsec_token,
                "user": {},
                "interact_info": {},
            }

        crawler.get_note_detail_async_task = get_note_detail
        crawler.get_notice_media = _noop
        crawler.batch_get_note_comments = _noop
        collector = MemoryResultCollector("xhs", "search", ["测试"], None)
        token = bind_collector(collector)
        try:
            await crawler.search()
        finally:
            reset_collector(token)
        return collector.to_result()

    monkeypatch.setattr(crawler_config, "KEYWORDS", "测试")
    monkeypatch.setattr(crawler_config, "START_PAGE", 1)
    monkeypatch.setattr(crawler_config, "CRAWLER_MAX_NOTES_COUNT", 1)
    monkeypatch.setattr(crawler_config, "CRAWLER_MAX_SLEEP_SEC", 0)

    result = asyncio.run(execute())

    assert result.contents[0]["note_url"] == (
        "https://www.xiaohongshu.com/explore/6a33b902000000001700a690"
        "?xsec_token=signed-token%3D&xsec_source=pc_search"
    )


def test_contextvars_do_not_share_mutable_defaults():
    assert creator_profile_var.get() is None
    assert comment_tasks_var.get() is None


def test_kuaishou_comment_failure_cancels_only_siblings_without_blocking(monkeypatch):
    from app.services.mediaspider.platforms.kuaishou import core

    sync_sleep_calls = []
    async_sleep_calls = []

    async def non_blocking_sleep(seconds):
        async_sleep_calls.append(seconds)

    monkeypatch.setattr(time, "sleep", lambda seconds: sync_sleep_calls.append(seconds))
    monkeypatch.setattr(core.asyncio, "sleep", non_blocking_sleep)
    monkeypatch.setattr(crawler_config, "CRAWLER_MAX_SLEEP_SEC", 0)
    monkeypatch.setattr(crawler_config, "MAX_CONCURRENCY_NUM", 2)
    monkeypatch.setattr(crawler_config, "ENABLE_GET_COMMENTS", True)

    class Client:
        sibling_cancelled = False

        async def get_video_all_comments(self, *, photo_id, **kwargs):
            if photo_id == "failed":
                raise RuntimeError("blocked")
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                self.sibling_cancelled = True
                raise

        async def update_cookies(self, **kwargs):
            return None

    class Page:
        async def goto(self, url):
            return None

    async def execute():
        crawler = core.KuaishouCrawler()
        crawler.ks_client = Client()
        crawler.context_page = Page()
        crawler.browser_context = object()
        current = asyncio.current_task()

        await crawler.batch_get_video_comments(["failed", "sibling"])

        assert current is not None
        assert current.cancelling() == 0
        assert crawler.ks_client.sibling_cancelled is True

    asyncio.run(execute())
    assert sync_sleep_calls == []
    assert 20 in async_sleep_calls


class _FakeContext:
    def __init__(self):
        self.close_calls = 0
        self.pages = []

    async def close(self):
        self.close_calls += 1


class _FakeBrowser:
    def __init__(self):
        self.close_calls = 0

    def is_connected(self):
        return True

    async def close(self):
        self.close_calls += 1


class _FakeLauncher:
    def __init__(self):
        self.browser_process = object()
        self.cleanup_calls = 0

    def cleanup(self):
        self.cleanup_calls += 1


def test_cdp_readiness_failure_cleans_process_created_by_launcher(monkeypatch):
    class Launcher(_FakeLauncher):
        def find_available_port(self, port):
            return port

        def launch_browser(self, **kwargs):
            return self.browser_process

        def wait_for_browser_ready(self, debug_port, timeout):
            return False

    async def execute():
        manager = CDPBrowserManager()
        manager.launcher = Launcher()

        async def browser_path():
            return "/fake/chrome"

        manager._get_browser_path = browser_path
        monkeypatch.setattr(crawler_config, "CDP_CONNECT_EXISTING", False)
        monkeypatch.setattr(crawler_config, "AUTO_CLOSE_BROWSER", False)

        with pytest.raises(RuntimeError, match="failed to start"):
            await manager.launch_and_connect(playwright=object())

        assert manager.launcher.cleanup_calls == 1

    asyncio.run(execute())


def test_cdp_readiness_wait_does_not_block_event_loop():
    observations = []
    ticks = 0

    class Launcher(_FakeLauncher):
        def launch_browser(self, **kwargs):
            return self.browser_process

        def wait_for_browser_ready(self, debug_port, timeout):
            before = ticks
            time.sleep(0.05)
            observations.append((before, ticks))
            return True

    async def execute():
        nonlocal ticks
        manager = CDPBrowserManager()
        manager.launcher = Launcher()
        manager.debug_port = 9222

        async def ticker():
            nonlocal ticks
            while True:
                ticks += 1
                await asyncio.sleep(0)

        async def cdp_ready(port):
            return True

        manager._test_cdp_connection = cdp_ready
        ticker_task = asyncio.create_task(ticker())
        await asyncio.sleep(0)
        try:
            await manager._launch_browser("/fake/chrome", headless=True)
        finally:
            ticker_task.cancel()
            await asyncio.gather(ticker_task, return_exceptions=True)

    asyncio.run(execute())
    assert observations[0][1] > observations[0][0]


def test_cdp_cleanup_preserves_external_context_after_config_restore(monkeypatch):
    async def execute():
        manager = CDPBrowserManager()
        context = _FakeContext()
        browser = _FakeBrowser()
        manager.browser_context = context
        manager.browser = browser
        manager.launcher = _FakeLauncher()
        manager._connected_to_external_browser = True
        manager._owns_browser_context = False
        manager._owns_browser_process = False
        monkeypatch.setattr(crawler_config, "CDP_CONNECT_EXISTING", False)

        await manager.cleanup(force=True)

        assert manager.browser_context is None
        assert manager.browser is None
        assert manager.launcher.cleanup_calls == 0
        assert context.close_calls == 0
        assert browser.close_calls == 0

    asyncio.run(execute())


def test_cdp_cleanup_releases_owned_resources_after_config_restore(monkeypatch):
    async def execute():
        manager = CDPBrowserManager()
        context = _FakeContext()
        browser = _FakeBrowser()
        manager.browser_context = context
        manager.browser = browser
        manager.launcher = _FakeLauncher()
        manager._connected_to_external_browser = False
        manager._owns_browser_context = True
        manager._owns_browser_process = True
        monkeypatch.setattr(crawler_config, "CDP_CONNECT_EXISTING", True)

        await manager.cleanup(force=True)

        assert context.close_calls == 1
        assert browser.close_calls == 1
        assert manager.launcher.cleanup_calls == 1

    asyncio.run(execute())


def test_xhs_search_processes_items_on_last_page(monkeypatch):
    from app.services.mediaspider.platforms.xhs.core import XiaoHongShuCrawler

    class LastPageClient:
        async def get_note_by_keyword(self, **kwargs):
            return {
                "has_more": False,
                "items": [
                    {
                        "id": "last-note",
                        "xsec_source": "pc_search",
                        "xsec_token": "token",
                        "model_type": "note",
                    }
                ],
            }

    async def execute():
        crawler = XiaoHongShuCrawler()
        crawler.xhs_client = LastPageClient()

        async def get_note_detail(*, note_id, xsec_token, **kwargs):
            return {
                "note_id": note_id,
                "xsec_token": xsec_token,
                "user": {},
                "interact_info": {},
            }

        crawler.get_note_detail_async_task = get_note_detail
        crawler.get_notice_media = _noop
        crawler.batch_get_note_comments = _noop
        collector = MemoryResultCollector("xhs", "search", ["测试"], None)
        token = bind_collector(collector)
        try:
            await crawler.search()
        finally:
            reset_collector(token)
        return collector.to_result()

    monkeypatch.setattr(crawler_config, "KEYWORDS", "测试")
    monkeypatch.setattr(crawler_config, "START_PAGE", 1)
    monkeypatch.setattr(crawler_config, "CRAWLER_MAX_NOTES_COUNT", 1)
    monkeypatch.setattr(crawler_config, "CRAWLER_MAX_SLEEP_SEC", 0)

    result = asyncio.run(execute())
    assert [item["note_id"] for item in result.contents] == ["last-note"]


def test_kuaishou_comment_coordinator_does_not_log_exception_secrets(
    monkeypatch, caplog
):
    from app.services.mediaspider.platforms.kuaishou import core

    async def non_blocking_sleep(seconds):
        return None

    class Client:
        async def get_video_all_comments(self, **kwargs):
            raise RuntimeError("cookie=secret")

        async def update_cookies(self, **kwargs):
            return None

    class Page:
        async def goto(self, url):
            return None

    async def execute():
        crawler = core.KuaishouCrawler()
        crawler.ks_client = Client()
        crawler.context_page = Page()
        crawler.browser_context = object()
        await crawler.batch_get_video_comments(["failed"])

    monkeypatch.setattr(core.asyncio, "sleep", non_blocking_sleep)
    monkeypatch.setattr(crawler_config, "ENABLE_GET_COMMENTS", True)
    monkeypatch.setattr(crawler_config, "MAX_CONCURRENCY_NUM", 1)
    caplog.set_level("ERROR", logger="starx.mediaspider")

    asyncio.run(execute())

    assert "secret" not in caplog.text
    assert "RuntimeError" in caplog.text
