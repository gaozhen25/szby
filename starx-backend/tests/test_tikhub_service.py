import asyncio
from typing import Any

import httpx
from tikhub import AsyncTikHub

from app.main import app
from app.services.tikhub_service import TikHubRuntime


class FakeAsyncTikHub:
    captured: dict[str, Any] = {}

    def __init__(self, **kwargs: Any) -> None:
        type(self).captured = kwargs
        self.closed = False

    async def aclose(self) -> None:
        self.closed = True


def test_tikhub_runtime_only_manages_official_sdk_lifecycle():
    transport = httpx.MockTransport(lambda request: httpx.Response(200))
    runtime = TikHubRuntime(
        api_key="test-key",
        base_url="https://api.tikhub.test",
        timeout_seconds=12,
        max_retries=2,
        client_factory=FakeAsyncTikHub,
        transport=transport,
    )

    first = runtime.client
    second = runtime.client

    assert first is second
    assert FakeAsyncTikHub.captured == {
        "api_key": "test-key",
        "base_url": "https://api.tikhub.test",
        "timeout": 12,
        "max_retries": 2,
        "transport": transport,
    }

    asyncio.run(runtime.aclose())
    assert first.closed is True


def test_tikhub_runtime_recreates_owned_client_after_close():
    runtime = TikHubRuntime(
        api_key="test-key",
        client_factory=FakeAsyncTikHub,
        transport=httpx.MockTransport(lambda request: httpx.Response(200)),
    )
    first = runtime.client

    asyncio.run(runtime.aclose())
    second = runtime.client

    assert first is not second


def test_tikhub_generic_proxy_routes_are_removed():
    paths = app.openapi()["paths"]

    assert "/api/v1/tikhub/call" not in paths
    assert "/api/v1/tikhub/resources" not in paths


def test_official_sdk_exposes_full_typed_cross_platform_catalog():
    async def inspect_sdk() -> None:
        sdk = AsyncTikHub(api_key="contract-test-key")
        try:
            resource_names = {
                name
                for name in dir(sdk)
                if not name.startswith("_")
                and not callable(getattr(sdk, name, None))
            }

            assert len(resource_names) >= 52
            assert {
                "bilibili_web",
                "douyin_app_v3",
                "instagram_v3",
                "kuaishou_app",
                "tiktok_web",
                "wechat_channels",
                "weibo_web",
                "xiaohongshu_app_v2",
                "youtube_web",
                "zhihu_web",
            } <= resource_names
            required_operations = {
                "douyin_app_v3": {
                    "fetch_one_video_by_share_url",
                    "fetch_one_video_v3",
                    "fetch_user_post_videos",
                    "fetch_video_comments",
                    "handler_user_profile",
                },
                "douyin_billboard": {"fetch_hot_total_video_list"},
                "douyin_index": {"fetch_daren_similar_users"},
                "douyin_search": {
                    "fetch_user_search_v2",
                    "fetch_video_search_v2",
                },
                "douyin_web": {
                    "get_sec_user_id",
                    "handler_user_profile_v2",
                    "handler_user_profile_v4",
                },
                "kuaishou_app": {
                    "fetch_one_user_v2",
                    "fetch_one_video",
                    "fetch_one_video_by_url",
                    "fetch_one_video_comment",
                    "fetch_user_post_v2",
                    "search_user_v2",
                    "search_video_v2",
                },
                "kuaishou_web": {"fetch_get_user_id"},
                "xiaohongshu_app_v2": {
                    "get_creator_hot_inspiration_feed",
                    "get_image_note_detail",
                    "get_note_comments",
                    "get_user_info",
                    "get_user_posted_notes",
                    "get_video_note_detail",
                    "search_notes",
                    "search_users",
                },
            }
            for resource_name, operations in required_operations.items():
                resource = getattr(sdk, resource_name)
                assert all(callable(getattr(resource, name)) for name in operations)

            assert callable(sdk.tiktok_web.fetch_search_video)
        finally:
            await sdk.aclose()

    asyncio.run(inspect_sdk())
