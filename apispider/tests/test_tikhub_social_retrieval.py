import asyncio
import inspect
from typing import Any

import pytest

from app.services.tikhub_service import (
    TikHubAccountContentsRequest,
    TikHubBusinessRequestError,
    TikHubContent,
    TikHubContentDetailRequest,
    TikHubContentPage,
    TikHubCrawlService,
    TikHubPlatform,
    TikHubProvider,
    TikHubSearchRequest,
    UnsupportedTikHubOperationError,
)


class FakeTikHubResource:
    def __init__(self, sdk: "FakeTikHubSDK", resource: str) -> None:
        self.sdk = sdk
        self.resource = resource

    def __getattr__(self, operation: str):
        async def invoke(**params: Any):
            self.sdk.calls.append((self.resource, operation, params))
            return self.sdk.responses.pop(0)

        return invoke


class FakeTikHubSDK:
    def __init__(self, responses: list[dict[str, Any]]) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    def __getattr__(self, resource: str) -> FakeTikHubResource:
        return FakeTikHubResource(self, resource)


def test_crawl_service_uses_explicit_typed_runtime_parameters():
    keyword = inspect.signature(TikHubCrawlService.crawl_by_keyword).parameters
    creator = inspect.signature(TikHubCrawlService.crawl_by_creator).parameters
    detail = inspect.signature(TikHubCrawlService.crawl_by_detail).parameters

    assert all(
        parameter.kind is not inspect.Parameter.VAR_KEYWORD
        for parameters in (keyword, creator, detail)
        for parameter in parameters.values()
    )
    assert keyword["max_notes_count"].default == 20
    assert keyword["enable_comments"].default is False
    assert keyword["max_comments_count"].default == 10
    assert keyword["reference_discovery"].default is False
    assert keyword["owner_user_ids"].default == ()
    assert creator["max_notes_count"].default == 20
    assert detail["enable_comments"].default is False


class CoordinatedKeywordProvider:
    provider_name = "tikhub"

    def __init__(self, expected: int, *, failures: set[str] | None = None) -> None:
        self.expected = expected
        self.failures = failures or set()
        self.started: set[str] = set()
        self.active = 0
        self.max_active = 0
        self.all_started = asyncio.Event()

    async def search_contents(self, request: TikHubSearchRequest) -> TikHubContentPage:
        self.started.add(request.keyword)
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        if len(self.started) == self.expected:
            self.all_started.set()
        try:
            await asyncio.wait_for(self.all_started.wait(), timeout=0.5)
            if request.keyword in self.failures:
                raise TikHubBusinessRequestError(
                    "temporary upstream failure",
                    request_id=f"req-{request.keyword}",
                )
            return TikHubContentPage(
                platform=request.platform,
                contents=[
                    TikHubContent(
                        platform=request.platform,
                        contentId=f"content-{request.keyword}",
                        title=request.keyword,
                        authorId=f"author-{request.keyword}",
                    )
                ],
            )
        finally:
            self.active -= 1


def test_keywords_run_concurrently_and_partial_failures_are_preserved():
    provider = CoordinatedKeywordProvider(3, failures={"失败词"})
    events = []
    service = TikHubCrawlService(provider=provider)  # type: ignore[arg-type]

    result = asyncio.run(
        service.crawl_by_keyword(
            keywords=["关键词一", "失败词", "关键词二"],
            platform="dy",
            max_notes_count=1,
            on_progress=events.append,
        )
    )

    assert provider.max_active == 3
    assert [item["content_id"] for item in result.contents] == [
        "content-关键词一",
        "content-关键词二",
    ]
    assert any(
        warning.startswith(
            "keyword_search_failed:dy:失败词:TikHubBusinessRequestError:req-失败词"
        )
        for warning in result.discovery_warnings
    )
    assert [event.action for event in events].count("keyword_started") == 3
    assert [event.action for event in events].count("keyword_completed") == 2
    assert [event.action for event in events].count("keyword_failed") == 1


def test_all_keyword_failures_raise_the_original_tikhub_error():
    provider = CoordinatedKeywordProvider(2, failures={"失败一", "失败二"})
    service = TikHubCrawlService(provider=provider)  # type: ignore[arg-type]

    with pytest.raises(TikHubBusinessRequestError) as captured:
        asyncio.run(
            service.crawl_by_keyword(
                keywords=["失败一", "失败二"],
                platform="dy",
                max_notes_count=1,
            )
        )

    assert captured.value.request_id == "req-失败一"
    assert provider.max_active == 2


def test_douyin_search_uses_latest_search_resource_and_preserves_cursor():
    client = FakeTikHubSDK(
        [
            {
                "code": 200,
                "data": {
                    "business_data": [
                        {
                            "data_id": "dy-1",
                            "type": 1,
                            "data": {
                                "aweme_info": {
                                    "aweme_id": "dy-1",
                                    "desc": "真实内容",
                                    "author": {"sec_uid": "sec-1", "nickname": "作者"},
                                    "statistics": {"digg_count": 12},
                                }
                            },
                        }
                    ],
                    "business_config": {
                        "has_more": 1,
                        "backtrace": "trace-1",
                        "next_page": {"cursor": 20, "search_id": "search-1"},
                    },
                },
            }
        ]
    )
    provider = TikHubProvider(sdk=client)

    page = asyncio.run(
        provider.search_contents(
            TikHubSearchRequest(platform="douyin", keyword="护肤", pageSize=20)
        )
    )

    assert client.calls == [
        (
            "douyin_search",
            "fetch_video_search_v2",
            {
                "keyword": "护肤",
                "cursor": 0,
                "sort_type": None,
                "search_id": None,
                "backtrace": None,
            },
        )
    ]
    assert page.contents[0].contentId == "dy-1"
    assert page.contents[0].authorId == "sec-1"
    assert page.contents[0].authorUrl == "https://www.douyin.com/user/sec-1"
    assert page.contents[0].likeCount == 12
    assert page.contents[0].raw["data_id"] == "dy-1"
    assert page.contents[0].raw["aweme_info"]["aweme_id"] == "dy-1"
    assert page.hasMore is True
    assert page.nextCursor

    client.responses.append({"data": {"business_data": [], "business_config": {"has_more": 0}}})
    asyncio.run(
        provider.search_contents(
            TikHubSearchRequest(
                platform="douyin",
                keyword="护肤",
                cursor=page.nextCursor,
            )
        )
    )
    assert client.calls[-1][2]["cursor"] == 20
    assert client.calls[-1][2]["search_id"] == "search-1"
    assert client.calls[-1][2]["backtrace"] == "trace-1"


def test_xiaohongshu_account_contents_and_kuaishou_detail_are_normalized():
    client = FakeTikHubSDK(
        [
            {
                "data": {
                    "notes": [
                        {
                            "note_id": "xhs-1",
                            "title": "笔记",
                            "user": {"user_id": "u-1", "nickname": "小红书作者"},
                        }
                    ],
                    "has_more": False,
                }
            },
            {
                "data": {
                    "photo": {
                        "photo_id": "ks-1",
                        "caption": "快手作品",
                        "user": {"user_id": "ks-u", "name": "快手作者"},
                        "counts": {"liked_count": 9},
                    }
                }
            },
        ]
    )
    provider = TikHubProvider(sdk=client)

    xhs_page = asyncio.run(
        provider.list_account_contents(
            TikHubAccountContentsRequest(
                platform="xiaohongshu",
                authorUrl="https://www.xiaohongshu.com/user/profile/u-1",
            )
        )
    )
    ks_content = asyncio.run(
        provider.get_content(
            TikHubContentDetailRequest(
                platform="kuaishou",
                workUrl="https://www.kuaishou.com/short-video/ks-1",
            )
        )
    )

    assert xhs_page.contents[0].contentId == "xhs-1"
    assert client.calls[0][0:2] == (
        "xiaohongshu_app_v2",
        "get_user_posted_notes",
    )
    assert ks_content.contentId == "ks-1"
    assert ks_content.authorName == "快手作者"
    assert ks_content.likeCount == 9


def test_xiaohongshu_search_uses_app_v2_filters_and_preserves_session_cursor():
    client = FakeTikHubSDK(
        [
            {
                "code": 200,
                "data": {
                    "data": {
                        "items": [
                            {
                                "xsec_token": "AB+c==",
                                "xsec_source": "pc_search",
                                "note_card": {
                                    "note_id": "xhs-hot",
                                    "title": "热门笔记",
                                    "type": "normal",
                                    "liked_count": "1.2万",
                                    "collected_count": "3,456",
                                    "comment_count": "78",
                                    "share_count": 90,
                                }
                            }
                        ],
                        "has_more": True,
                        "search_id": "search-1",
                        "search_session_id": "session-1",
                        "cursor": "cursor-1",
                    }
                },
            }
        ]
    )
    provider = TikHubProvider(sdk=client)

    page = asyncio.run(
        provider.search_contents(
            TikHubSearchRequest(
                platform="xiaohongshu",
                keyword="露营",
                sortType="collect_descending",
                noteType="普通笔记",
                timeFilter="半年内",
            )
        )
    )

    assert client.calls == [
        (
            "xiaohongshu_app_v2",
            "search_notes",
            {
                "keyword": "露营",
                "page": 1,
                "sort_type": "collect_descending",
                "note_type": "普通笔记",
                "time_filter": "半年内",
                "search_id": None,
                "search_session_id": None,
                "source": "explore_feed",
            },
        )
    ]
    assert page.contents[0].contentId == "xhs-hot"
    assert page.contents[0].contentUrl == (
        "https://www.xiaohongshu.com/explore/xhs-hot"
        "?xsec_token=AB%2Bc%3D%3D&xsec_source=pc_search"
    )
    assert page.contents[0].likeCount == 12_000
    assert page.contents[0].collectCount == 3_456
    assert page.contents[0].commentCount == 78
    assert page.contents[0].shareCount == 90
    assert page.hasMore is True
    assert page.nextCursor

    client.responses.append({"data": {"items": [], "has_more": False}})
    asyncio.run(
        provider.search_contents(
            TikHubSearchRequest(
                platform="xiaohongshu",
                keyword="露营",
                cursor=page.nextCursor,
            )
        )
    )
    assert client.calls[-1][2]["page"] == 2
    assert client.calls[-1][2]["search_id"] == "search-1"
    assert client.calls[-1][2]["search_session_id"] == "session-1"


def test_xiaohongshu_detail_never_calls_retired_app_v1():
    client = FakeTikHubSDK(
        [
            {
                "data": {
                    "note": {
                        "note_id": "video-1",
                        "title": "视频笔记",
                        "type": "video",
                    }
                }
            }
        ]
    )
    provider = TikHubProvider(sdk=client)

    content = asyncio.run(
        provider.get_content(
            TikHubContentDetailRequest(
                platform="xiaohongshu",
                workId="video-1",
                contentType="video",
            )
        )
    )

    assert content.contentId == "video-1"
    assert client.calls[0][0:2] == (
        "xiaohongshu_app_v2",
        "get_video_note_detail",
    )
    assert all(resource != "xiaohongshu_app" for resource, _, _ in client.calls)


def test_ai_content_search_fails_explicitly_instead_of_returning_normal_search():
    from app.services.tikhub_service import TikHubAiContentSearchRequest

    provider = TikHubProvider(sdk=FakeTikHubSDK([]))
    with pytest.raises(UnsupportedTikHubOperationError, match="does not provide"):
        asyncio.run(
            provider.search_ai_contents(
                TikHubAiContentSearchRequest(platform="douyin", keyword="AI")
            )
        )


def test_crawl_adapter_outputs_existing_account_report_contract():
    client = FakeTikHubSDK(
        [
            {
                "data": {
                    "data": [
                        {
                            "aweme_info": {
                                "aweme_id": "dy-1",
                                "desc": "内容",
                                "author": {"sec_uid": "sec-1", "nickname": "作者"},
                                "statistics": {"digg_count": 8},
                            }
                        }
                    ],
                    "has_more": False,
                }
            }
        ]
    )
    service = TikHubCrawlService(TikHubProvider(sdk=client))

    result = asyncio.run(
        service.crawl_by_keyword(
            keywords=["护肤"], platform="dy", max_notes_count=5
        )
    )

    assert result.platform == "dy"
    assert result.content_count == 1
    assert result.creator_count == 1
    assert result.contents[0]["aweme_id"] == "dy-1"
    assert result.contents[0]["source_keyword"] == "护肤"
    assert result.contents[0]["source_provider"] == "tikhub"
    assert result.creators[0]["sec_user_id"] == "sec-1"


def test_reference_discovery_searches_and_hydrates_accounts_and_hot_candidates():
    author = {"sec_uid": "sec-peer", "nickname": "露营作者"}
    client = FakeTikHubSDK(
        [
            {"data": {"data": [], "has_more": False}},
            {"data": {"data": [], "has_more": False}},
            {
                "data": {
                    "user_list": [
                        {"user_info": {**author, "follower_count": 100}}
                    ],
                    "has_more": False,
                }
            },
            {
                "data": {
                    "user": {
                        **author,
                        "follower_count": 12_000,
                        "aweme_count": 88,
                    }
                }
            },
            {
                "data": {
                    "aweme_list": [
                        {
                            "aweme_id": "recent-1",
                            "desc": "新手露营清单",
                            "author": author,
                            "statistics": {"digg_count": 500},
                        }
                    ],
                    "has_more": False,
                }
            },
            {
                "data": {
                    "aweme_list": [
                        {
                            "aweme_id": "hot-low-fan",
                            "desc": "露营装备爆款",
                            "author": author,
                            "statistics": {"digg_count": 50_000},
                        }
                    ]
                }
            },
            {"data": {"aweme_list": []}},
        ]
    )
    service = TikHubCrawlService(TikHubProvider(sdk=client))

    result = asyncio.run(
        service.crawl_by_keyword(
            keywords=["露营"],
            platform="dy",
            max_notes_count=10,
            reference_discovery=True,
        )
    )

    peer = next(item for item in result.creators if item["user_id"] == "sec-peer")
    hot = next(item for item in result.contents if item["aweme_id"] == "hot-low-fan")
    assert peer["fans_count"] == 12_000
    assert peer["works_count"] == 88
    assert peer["representative_contents"] == ["新手露营清单"]
    assert peer["matched_queries"] == ["露营"]
    assert hot["source_operation"] == "hot_billboard_1002"
    assert hot["source_keyword"] == "露营"


def test_all_current_social_platforms_are_supported():
    assert set(TikHubPlatform) == {
        TikHubPlatform.DOUYIN,
        TikHubPlatform.XIAOHONGSHU,
        TikHubPlatform.KUAISHOU,
    }
