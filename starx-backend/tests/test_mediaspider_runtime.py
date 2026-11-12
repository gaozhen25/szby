import asyncio
import json
import logging

import pytest

from app.services.mediaspider.models import CrawlerExecutionError, CrawlerRunConfig
from app.services.mediaspider.runtime import crawler_config
from app.services.mediaspider.runtime.collector import (
    MemoryResultCollector,
    MemoryStore,
    bind_collector,
    build_safe_creator,
    reset_collector,
)
from app.services.mediaspider.runtime.runner import (
    CrawlerFactory,
    ProcessAsyncLimiter,
    run_crawler,
)
from app.services.mediaspider.stores.douyin import update_douyin_aweme
from app.services.mediaspider.stores.kuaishou import update_kuaishou_video
from app.services.mediaspider.stores.xhs import update_xhs_note
from app.services.mediaspider.vendor import tools
from app.services.mediaspider.vendor.user_hash import anonymize_user_id


class FakeResource:
    def __init__(self):
        self.calls = []

    async def cleanup(self, *, force):
        self.calls.append(("cleanup", force))

    async def close(self):
        self.calls.append(("close",))


class FakeCrawler:
    def __init__(self, *, fail=False, entered=None, gate=None, resource=None):
        self.fail = fail
        self.entered = entered
        self.gate = gate
        self.cdp_manager = resource
        self.browser_context = None

    async def start(self):
        await MemoryStore().store_content({"note_id": "n1", "title": "结果"})
        if self.entered:
            self.entered.set()
        if self.gate:
            await self.gate.wait()
        if self.fail:
            raise RuntimeError("boom")


class FakeFactory:
    def __init__(self, crawler):
        self.crawler = crawler

    def create_crawler(self, platform):
        assert platform == "xhs"
        return self.crawler


def make_config() -> CrawlerRunConfig:
    return CrawlerRunConfig(
        platform="xhs",
        crawl_type="search",
        keywords=["美食"],
        cookies="cookie=value",
    )


def test_runner_restores_config_and_collector_after_failure():
    original = crawler_config.PLATFORM

    async def execute():
        with pytest.raises(CrawlerExecutionError) as exc_info:
            await run_crawler(make_config(), factory=FakeFactory(FakeCrawler(fail=True)))
        assert exc_info.value.partial_result.platform == "xhs"
        assert exc_info.value.partial_result.content_count == 1
        assert exc_info.value.partial_result.contents == []
        with pytest.raises(RuntimeError, match="未绑定"):
            await MemoryStore().store_content({"note_id": "outside"})

    asyncio.run(execute())
    assert crawler_config.PLATFORM == original


def test_douyin_content_prefers_sec_uid_for_profile_consistent_creator_hash():
    async def execute():
        collector = MemoryResultCollector("dy", "search", ["美妆"], None)
        token = bind_collector(collector)
        try:
            await update_douyin_aweme(
                {
                    "aweme_id": "post-1",
                    "desc": "样本",
                    "author": {
                        "uid": "numeric-uid",
                        "sec_uid": "MS4wLjABAAAA-profile-owner",
                        "nickname": "作者",
                    },
                }
            )
            return collector.to_result()
        finally:
            reset_collector(token)

    result = asyncio.run(execute())
    assert result.contents[0]["creator_hash"] == anonymize_user_id("MS4wLjABAAAA-profile-owner")


@pytest.mark.parametrize(
    ("platform", "raw_id", "update"),
    [
        (
            "xhs",
            "xhs-profile-owner",
            lambda raw_id: update_xhs_note(
                {"note_id": "post-1", "user": {"user_id": raw_id, "nickname": "作者"}}
            ),
        ),
        (
            "ks",
            "ks-profile-owner",
            lambda raw_id: update_kuaishou_video(
                {"photo": {"id": "post-1"}, "author": {"id": raw_id, "name": "作者"}}
            ),
        ),
    ],
)
def test_xhs_and_kuaishou_content_use_the_same_profile_identity(platform, raw_id, update):
    async def execute():
        collector = MemoryResultCollector(platform, "search", ["美妆"], None)
        token = bind_collector(collector)
        try:
            await update(raw_id)
            return collector.to_result()
        finally:
            reset_collector(token)

    result = asyncio.run(execute())
    assert result.contents[0]["creator_hash"] == anonymize_user_id(raw_id)


@pytest.mark.parametrize(
    ("platform", "update", "expected_url"),
    [
        (
            "xhs",
            lambda: update_xhs_note(
                {
                    "note_id": "post-1",
                    "user": {"user_id": "xhs-author", "nickname": "小红书真实作者"},
                }
            ),
            "https://www.xiaohongshu.com/user/profile/xhs-author",
        ),
        (
            "dy",
            lambda: update_douyin_aweme(
                {
                    "aweme_id": "post-1",
                    "author": {
                        "sec_uid": "dy-author",
                        "nickname": "抖音真实作者",
                    },
                }
            ),
            "https://www.douyin.com/user/dy-author",
        ),
        (
            "ks",
            lambda: update_kuaishou_video(
                {
                    "photo": {"id": "post-1"},
                    "author": {"id": "ks-author", "name": "快手真实作者"},
                }
            ),
            "https://www.kuaishou.com/profile/ks-author",
        ),
    ],
)
def test_content_records_preserve_author_display_fields(platform, update, expected_url):
    async def execute():
        collector = MemoryResultCollector(platform, "search", ["美妆"], None)
        token = bind_collector(collector)
        try:
            await update()
            return collector.to_result()
        finally:
            reset_collector(token)

    content = asyncio.run(execute()).contents[0]
    assert content["display_name"].endswith("真实作者")
    assert content["profile_url"] == expected_url


def test_runner_restores_config_and_cleans_resource_after_cancellation():
    original = crawler_config.PLATFORM

    async def execute():
        entered = asyncio.Event()
        gate = asyncio.Event()
        resource = FakeResource()
        task = asyncio.create_task(
            run_crawler(
                make_config(),
                factory=FakeFactory(
                    FakeCrawler(entered=entered, gate=gate, resource=resource)
                ),
            )
        )
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert resource.calls == [("cleanup", True)]

    asyncio.run(execute())
    assert crawler_config.PLATFORM == original


def test_runner_allows_bounded_same_platform_concurrency():
    async def execute():
        first_entered = asyncio.Event()
        first_gate = asyncio.Event()
        second_entered = asyncio.Event()
        first = asyncio.create_task(
            run_crawler(
                make_config(),
                factory=FakeFactory(
                    FakeCrawler(entered=first_entered, gate=first_gate)
                ),
            )
        )
        await first_entered.wait()
        second = asyncio.create_task(
            run_crawler(
                make_config(),
                factory=FakeFactory(FakeCrawler(entered=second_entered)),
            )
        )
        await asyncio.wait_for(second_entered.wait(), timeout=1)
        first_gate.set()
        await asyncio.gather(first, second)

    asyncio.run(execute())


def test_process_async_limiter_enforces_capacity():
    async def execute():
        limiter = ProcessAsyncLimiter(2)
        entered = []
        release = asyncio.Event()

        async def worker(index):
            async with limiter:
                entered.append(index)
                await release.wait()

        tasks = [asyncio.create_task(worker(index)) for index in range(3)]
        while len(entered) < 2:
            await asyncio.sleep(0)
        await asyncio.sleep(0.02)
        assert len(entered) == 2
        release.set()
        await asyncio.gather(*tasks)
        assert sorted(entered) == [0, 1, 2]

    asyncio.run(execute())


def test_runner_allows_different_platforms_and_isolates_task_config():
    async def execute():
        entered = {"xhs": asyncio.Event(), "dy": asyncio.Event()}
        release = asyncio.Event()
        observations = {"xhs": [], "dy": []}

        class ConfigCrawler:
            cdp_manager = None
            browser_context = None

            def __init__(self, expected_platform):
                self.expected_platform = expected_platform

            async def start(self):
                observations[self.expected_platform].append((
                    crawler_config.PLATFORM,
                    crawler_config.COOKIES,
                    crawler_config.KEYWORDS,
                ))
                entered[self.expected_platform].set()
                await release.wait()
                observations[self.expected_platform].append((
                    crawler_config.PLATFORM,
                    crawler_config.COOKIES,
                    crawler_config.KEYWORDS,
                ))

        class ConfigFactory:
            @staticmethod
            def create_crawler(platform):
                return ConfigCrawler(platform)

        xhs = asyncio.create_task(
            run_crawler(
                CrawlerRunConfig(
                    platform="xhs",
                    crawl_type="search",
                    keywords=["小红书词"],
                    cookies="xhs-cookie",
                ),
                factory=ConfigFactory,
            )
        )
        dy = asyncio.create_task(
            run_crawler(
                CrawlerRunConfig(
                    platform="dy",
                    crawl_type="search",
                    keywords=["抖音词"],
                    cookies="dy-cookie",
                ),
                factory=ConfigFactory,
            )
        )

        await asyncio.wait_for(
            asyncio.gather(entered["xhs"].wait(), entered["dy"].wait()),
            timeout=1,
        )
        release.set()
        await asyncio.gather(xhs, dy)

        assert observations == {
            "xhs": [
                ("xhs", "xhs-cookie", "小红书词"),
                ("xhs", "xhs-cookie", "小红书词"),
            ],
            "dy": [
                ("dy", "dy-cookie", "抖音词"),
                ("dy", "dy-cookie", "抖音词"),
            ],
        }

    asyncio.run(execute())


def test_factory_exposes_only_supported_crawlers():
    assert set(CrawlerFactory.CRAWLERS) == {"xhs", "dy", "ks"}


def test_platform_modules_are_importable():
    from app.services.mediaspider.http_platforms.douyin import DouyinClient
    from app.services.mediaspider.http_platforms.xhs import XhsClient

    assert DouyinClient and XhsClient


def test_kuaishou_mediaspider_is_offline():
    from app.services.mediaspider.models import UnsupportedPlatformError
    from app.services.mediaspider.runtime.runner import CrawlerFactory

    with pytest.raises(UnsupportedPlatformError):
        CrawlerFactory.create_crawler("ks")


def test_cookie_conversion_keeps_upstream_tuple_contract():
    cookie_string, cookie_dict = tools.convert_cookies(
        [{"name": "session", "value": "secret"}]
    )
    assert cookie_string == "session=secret"
    assert cookie_dict == {"session": "secret"}


def test_execution_error_does_not_echo_sensitive_cause():
    error = CrawlerExecutionError(
        "xhs",
        RuntimeError("request failed with session=super-secret"),
        MemoryResultCollector("xhs", "search", [], None).to_result(),
    )
    assert "super-secret" not in str(error)


def test_xhs_store_anonymizes_creator_identity():
    from app.services.mediaspider.stores import xhs

    async def execute():
        collector = MemoryResultCollector("xhs", "search", [], None)
        token = bind_collector(collector)
        try:
            await xhs.update_xhs_note(
                {
                    "note_id": "n1",
                    "user": {"user_id": "raw-user", "nickname": "张三"},
                    "interact_info": {},
                }
            )
        finally:
            reset_collector(token)
        return collector.to_result()

    content = asyncio.run(execute()).contents[0]
    assert content["creator_hash"] != "raw-user"
    assert content["nickname"] != "张三"


@pytest.mark.parametrize(
    ("platform", "raw_id", "expected_url"),
    [
        ("xhs", "xhs-user", "https://www.xiaohongshu.com/user/profile/xhs-user"),
        ("dy", "dy-sec-user", "https://www.douyin.com/user/dy-sec-user"),
        ("ks", "ks-user", "https://www.kuaishou.com/profile/ks-user"),
    ],
)
def test_safe_creator_preserves_public_display_fields(platform, raw_id, expected_url):
    creator = build_safe_creator(platform, raw_id, {"nickname": "公开博主名称"})

    assert creator["display_name"] == "公开博主名称"
    assert creator["nickname"] != "公开博主名称"
    assert creator["profile_url"] == expected_url
    assert raw_id not in creator["creator_hash"]


def test_safe_creator_does_not_copy_untrusted_profile_url():
    creator = build_safe_creator(
        "unknown",
        "raw-user",
        {"nickname": "公开名", "profile_url": "javascript:alert(1)"},
    )

    assert creator["profile_url"] == ""


def test_safe_creator_preserves_raw_public_data_without_cookies():
    creator = build_safe_creator(
        "dy",
        "raw-user",
        {"nickname": "公开名", "fans_count": 1234},
        raw_data={
            "nickname": "公开名",
            "follower_count": 1234,
            "signature": "公开简介",
            "cookie": "secret",
            "nested": {"cookies": "nested-secret", "verified": True},
        },
    )

    assert creator["fans_count"] == 1234
    assert creator["raw_data"] == {
        "nickname": "公开名",
        "follower_count": 1234,
        "signature": "公开简介",
        "nested": {"verified": True},
    }


def test_safe_creator_maps_douyin_account_fields_for_existing_consumers():
    creator = build_safe_creator(
        "dy",
        "raw-user",
        {
            "nickname": "公开名",
            "follower_count": 12_345,
            "following_count": 67,
            "aweme_count": 89,
            "total_favorited": 456_789,
            "signature": "公开简介",
        },
    )

    assert creator["fans_count"] == 12_345
    assert creator["following_count"] == 67
    assert creator["works_count"] == 89
    assert creator["liked_count"] == 456_789
    assert creator["bio"] == "公开简介"


def test_xhs_store_preserves_complete_note_url_with_search_token():
    async def execute():
        collector = MemoryResultCollector("xhs", "search", ["美妆"], None)
        token = bind_collector(collector)
        try:
            await update_xhs_note(
                {
                    "note_id": "6a411e68000000000701114b",
                    "xsec_token": "ABsEQjfB8dALwX2ljCtVLnK3wzfUu9tWlrIFgxVCVfq50=",
                    "xsec_source": "pc_search",
                    "user": {"user_id": "raw-user", "nickname": "张三"},
                    "interact_info": {},
                }
            )
        finally:
            reset_collector(token)
        return collector.to_result()

    content = asyncio.run(execute()).contents[0]
    assert content["note_url"] == (
        "https://www.xiaohongshu.com/explore/6a411e68000000000701114b"
        "?xsec_token=ABsEQjfB8dALwX2ljCtVLnK3wzfUu9tWlrIFgxVCVfq50%3D"
        "&xsec_source=pc_search"
    )


def test_xhs_store_falls_back_to_base_note_url_without_complete_access_params():
    async def execute():
        collector = MemoryResultCollector("xhs", "creator", [], None)
        token = bind_collector(collector)
        try:
            await update_xhs_note(
                {
                    "note_id": "note-without-token",
                    "xsec_token": "partial-token",
                    "user": {"user_id": "raw-user", "nickname": "张三"},
                    "interact_info": {},
                }
            )
        finally:
            reset_collector(token)
        return collector.to_result()

    content = asyncio.run(execute()).contents[0]
    assert content["note_url"] == (
        "https://www.xiaohongshu.com/explore/note-without-token"
    )


def test_collector_drops_cookie_fields_from_platform_records():
    collector = MemoryResultCollector("xhs", "search", [], None)
    collector.store_content(
        {"note_id": "n1", "title": "安全", "cookies": "super-secret"}
    )
    assert collector.to_result().contents == [{"note_id": "n1", "title": "安全"}]


def test_content_event_removes_chinese_wechat_and_separated_phone():
    events = []

    async def execute():
        collector = MemoryResultCollector(
            "xhs", "search", ["探店"], None, events.append
        )
        token = bind_collector(collector)
        try:
            await MemoryStore().store_content(
                {
                    "note_id": "n1",
                    "title": "探店 微信：张三 电话 138-0013-8000",
                }
            )
        finally:
            reset_collector(token)

    asyncio.run(execute())

    title = events[0].content_title
    assert title.startswith("探店")
    assert "微信" not in title
    assert "张三" not in title
    assert "138-0013-8000" not in title


def test_creator_event_masks_untrusted_nickname_at_event_boundary():
    events = []

    async def execute():
        collector = MemoryResultCollector(
            "xhs", "search", ["探店"], None, events.append
        )
        token = bind_collector(collector)
        try:
            await MemoryStore().store_creator(
                {"creator_hash": "safe-hash", "nickname": "张三丰"}
            )
        finally:
            reset_collector(token)

    asyncio.run(execute())

    assert events[0].subject == "张***丰"
    assert "张三丰" not in events[0].subject


def test_runner_emits_safe_bounded_record_events_without_comment_text():
    events = []

    async def collect(event):
        events.append(event.model_dump(mode="json", by_alias=True))

    async def execute():
        await run_crawler(
            make_config(), on_progress=collect, factory=FakeFactory(FakeCrawler())
        )

    asyncio.run(execute())
    serialized = json.dumps(events, ensure_ascii=False)
    assert [item["action"] for item in events][0] == "waiting_for_slot"
    assert "content_discovered" in [item["action"] for item in events]
    assert "cookie=value" not in serialized
    assert "commentText" not in serialized


def test_runner_emits_deduplicated_safe_record_counts():
    events = []

    class RecordCrawler:
        cdp_manager = None
        browser_context = None

        async def start(self):
            store = MemoryStore()
            content = {
                "note_id": "raw-note-id",
                "title": (
                    "探店 https://secret.example/path 联系 13800138000 "
                    "token=super-secret " + "好" * 80
                ),
                "cookies": "cookie=value",
            }
            await store.store_content(content)
            await store.store_content(content)
            creator = {
                "creator_hash": "hashed-creator-id",
                "nickname": "张*",
                "profile_url": "https://secret.example/user/raw-id",
            }
            await store.store_creator(creator)
            await store.store_creator(creator)
            comment = {
                "comment_id": "raw-comment-id",
                "commentText": "不应出现在事件中",
            }
            await store.store_comment(comment)
            await store.store_comment(comment)

    async def collect(event):
        events.append(event.model_dump(mode="json", by_alias=True))

    asyncio.run(
        run_crawler(
            make_config(), on_progress=collect, factory=FakeFactory(RecordCrawler())
        )
    )

    actions = [item["action"] for item in events]
    assert actions == [
        "waiting_for_slot",
        "run_started",
        "keyword_started",
        "content_discovered",
        "creator_discovered",
        "comments_updated",
        "run_completed",
    ]
    record_events = events[3:6]
    assert [(item["contentCount"], item["creatorCount"], item["commentCount"])
            for item in record_events] == [(1, 0, 0), (1, 1, 0), (1, 1, 1)]
    assert record_events[1]["subject"] == "张*"
    assert len(record_events[0]["contentTitle"]) <= 60
    serialized = json.dumps(events, ensure_ascii=False)
    assert "https://" not in serialized
    assert "13800138000" not in serialized
    assert "super-secret" not in serialized
    assert "raw-note-id" not in serialized
    assert "raw-comment-id" not in serialized
    assert "hashed-creator-id" not in serialized
    assert "commentText" not in serialized
    assert "不应出现在事件中" not in serialized


@pytest.mark.parametrize(
    ("crawl_type", "expected_action"),
    [("search", "keyword_started"), ("creator", "creator_started")],
)
def test_runner_emits_mode_lifecycle_event(crawl_type, expected_action):
    events = []
    config = CrawlerRunConfig(
        platform="xhs",
        crawl_type=crawl_type,
        keywords=["美食"] if crawl_type == "search" else [],
        creator_url=(
            None if crawl_type == "search" else "https://www.xiaohongshu.com/user/demo"
        ),
        cookies="cookie=value",
    )

    asyncio.run(
        run_crawler(
            config,
            on_progress=lambda event: events.append(event),
            factory=FakeFactory(FakeCrawler()),
        )
    )

    actions = [event.action for event in events]
    assert actions[:3] == ["waiting_for_slot", "run_started", expected_action]
    assert actions[-1] == "run_completed"
    expected_subject = "美食" if crawl_type == "search" else "小红书账号主页"
    assert events[2].subject == expected_subject


def test_runner_keyword_subject_drops_unsafe_keywords():
    events = []
    config = CrawlerRunConfig(
        platform="xhs",
        crawl_type="search",
        keywords=["美食", "token=keyword-subject-sentinel"],
        cookies="cookie=value",
    )

    asyncio.run(
        run_crawler(
            config,
            on_progress=lambda event: events.append(event),
            factory=FakeFactory(FakeCrawler()),
        )
    )

    event = next(item for item in events if item.action == "keyword_started")
    assert event.subject == "美食"
    assert "sentinel" not in event.model_dump_json()


def test_runner_emits_failed_lifecycle_event_before_wrapping_error():
    events = []

    with pytest.raises(CrawlerExecutionError):
        asyncio.run(
            run_crawler(
                make_config(),
                on_progress=lambda event: events.append(event),
                factory=FakeFactory(FakeCrawler(fail=True)),
            )
        )

    assert events[-1].action == "run_failed"
    assert events[-1].status == "failed"
    assert "boom" not in events[-1].message


def test_progress_callback_failures_do_not_interrupt_crawler():
    def failing_callback(event):
        raise RuntimeError(
            "callback leaked cookie=value https://secret.example raw-id commentText"
        )

    result = asyncio.run(
        run_crawler(
            make_config(),
            on_progress=failing_callback,
            factory=FakeFactory(FakeCrawler()),
        )
    )

    assert result.content_count == 1


def test_async_progress_callback_failure_is_isolated_and_safely_logged(caplog):
    sentinel = "ASYNC_CALLBACK_SECRET"

    async def failing_callback(event):
        await asyncio.sleep(0)
        raise RuntimeError(f"callback exploded {sentinel} cookie=value")

    with caplog.at_level(logging.WARNING, logger="starx.mediaspider"):
        result = asyncio.run(
            run_crawler(
                make_config(),
                on_progress=failing_callback,
                factory=FakeFactory(FakeCrawler()),
            )
        )

    assert result.content_count == 1
    assert "event=mediaspider.ProgressCallback.xhs" in caplog.text
    assert sentinel not in caplog.text
    assert "callback exploded" not in caplog.text
    assert "cookie=value" not in caplog.text
