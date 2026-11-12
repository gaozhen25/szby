import asyncio
import inspect
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest

from app.services.tikhub_service import (
    TikHubAccount,
    TikHubAccountContentsRequest,
    TikHubAccountDetailRequest,
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
from app.services.tikhub_service.crawl_service import _merge_account_details


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
    assert keyword["hydrate_douyin_creator_details"].default is False
    assert keyword["max_creator_details"].default == 8
    assert creator["max_notes_count"].default == 20
    assert creator["max_detail_count"].default is None
    assert creator["sec_user_id"].default == ""
    assert creator["recent_since"].default is None
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


class PaginatedKeywordProvider:
    provider_name = "tikhub"

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    async def search_contents(self, request: TikHubSearchRequest) -> TikHubContentPage:
        self.calls.append((request.keyword, request.cursor))
        return TikHubContentPage(
            platform=request.platform,
            hasMore=True,
            nextCursor=f"next-{request.keyword}",
            contents=[
                TikHubContent(
                    platform=request.platform,
                    contentId=f"{request.keyword}-{index}",
                    authorId=f"{request.keyword}-author-{index}",
                )
                for index in range(8)
            ],
        )


def test_report_collects_eight_notes_per_keyword_from_first_page():
    provider = PaginatedKeywordProvider()
    service = TikHubCrawlService(provider=provider)  # type: ignore[arg-type]

    result = asyncio.run(
        service.crawl_by_keyword(
            keywords=["关键词一", "关键词二", "关键词三", "关键词四", "关键词五"],
            platform="dy",
            max_notes_count=8,
        )
    )

    assert provider.calls == [
        ("关键词一", ""),
        ("关键词二", ""),
        ("关键词三", ""),
        ("关键词四", ""),
        ("关键词五", ""),
    ]
    assert result.content_count == 40
    assert result.creator_count == 40


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
                                    "author": {
                                        "sec_uid": "sec-1",
                                        "nickname": "作者",
                                        "avatar_thumb": {"url_list": ["https://example.com/a.jpg"]},
                                        "follower_count": 12_345,
                                        "aweme_count": 67,
                                        "total_favorited": 890_000,
                                    },
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
    assert page.contents[0].authorAvatarUrl == "https://example.com/a.jpg"
    assert page.contents[0].authorFollowers == 12_345
    assert page.contents[0].authorContentCount == 67
    assert page.contents[0].authorTotalLikes == 890_000
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


def test_xiaohongshu_search_card_builds_author_profile_without_profile_request():
    client = FakeTikHubSDK(
        [
            {
                "data": {
                    "items": [
                        {
                            "id": "xhs-note-1",
                            "title": "护肤心得",
                            "timestamp": 1775807335,
                            "user": {
                                "userid": "5a34cd1811be103ff72f06a2",
                                "nickname": "小红书作者",
                            },
                            "liked_count": 90,
                            "comments_count": 47,
                            "collected_count": 71,
                            "shared_count": 8,
                        }
                    ],
                    "has_more": False,
                }
            }
        ]
    )
    provider = TikHubProvider(sdk=client)

    page = asyncio.run(
        provider.search_contents(
            TikHubSearchRequest(platform="xiaohongshu", keyword="护肤")
        )
    )

    content = page.contents[0]
    assert content.authorId == "5a34cd1811be103ff72f06a2"
    assert content.authorUrl == (
        "https://www.xiaohongshu.com/user/profile/5a34cd1811be103ff72f06a2"
    )
    assert content.publishedAt == "1775807335"
    assert content.likeCount == 90
    assert content.commentCount == 47
    assert content.collectCount == 71
    assert content.shareCount == 8
    assert [(resource, operation) for resource, operation, _ in client.calls] == [
        ("xiaohongshu_app_v2", "search_notes")
    ]


def test_douyin_account_contents_use_app_v3_latest_sort_and_preserve_cursor():
    client = FakeTikHubSDK(
        [
            {
                "data": {
                    "aweme_list": [
                        {
                            "aweme_id": "dy-post-1",
                            "desc": "主页作品",
                            "author": {"sec_uid": "sec-1", "nickname": "作者"},
                        }
                    ],
                    "has_more": True,
                    "max_cursor": 123456,
                }
            }
        ]
    )
    provider = TikHubProvider(sdk=client)

    page = asyncio.run(
        provider.list_account_contents(
            TikHubAccountContentsRequest(
                platform="douyin",
                secUserId="sec-1",
                pageSize=10,
            )
        )
    )

    assert client.calls == [
        (
            "douyin_app_v3",
            "fetch_user_post_videos",
            {
                "sec_user_id": "sec-1",
                "max_cursor": 0,
                "count": 10,
                "sort_type": 0,
            },
        )
    ]
    assert page.contents[0].contentId == "dy-post-1"
    assert page.hasMore is True
    assert page.nextCursor

    client.responses.append({"data": {"aweme_list": [], "has_more": False}})
    asyncio.run(
        provider.list_account_contents(
            TikHubAccountContentsRequest(
                platform="douyin",
                secUserId="sec-1",
                pageSize=10,
                cursor=page.nextCursor,
            )
        )
    )
    assert client.calls[-1][2]["max_cursor"] == 123456


def test_douyin_profile_url_uses_embedded_sec_user_id_without_resolver_call():
    sec_user_id = "MS4wLjABAAA-test"
    profile_url = f"https://www.douyin.com/user/{sec_user_id}?relation=1"
    client = FakeTikHubSDK(
        [
            {
                "data": {
                    "status_code": 0,
                    "user": {
                        "sec_uid": sec_user_id,
                        "nickname": "作者",
                        "user_age": 28,
                    },
                    "live_user": {
                        "gender": 1,
                        "level": 35,
                        "fans_club": {"data": {"club_name": "作者粉丝团"}},
                    },
                }
            },
            {"data": {"aweme_list": [], "has_more": False}},
        ]
    )
    provider = TikHubProvider(sdk=client)

    account = asyncio.run(
        provider.get_account(
            TikHubAccountDetailRequest(
                platform="douyin",
                authorUrl=profile_url,
            )
        )
    )
    asyncio.run(
        provider.list_account_contents(
            TikHubAccountContentsRequest(
                platform="douyin",
                authorUrl=profile_url,
            )
        )
    )

    assert account.userId == sec_user_id
    assert account.raw["user"]["user_age"] == 28
    assert account.raw["live_user"]["gender"] == 1
    assert account.raw["live_user"]["level"] == 35
    assert (
        account.raw["live_user"]["fans_club"]["data"]["club_name"]
        == "作者粉丝团"
    )
    assert client.calls == [
        (
            "douyin_web",
            "handler_user_profile_v4",
            {"sec_user_id": sec_user_id},
        ),
        (
            "douyin_app_v3",
            "fetch_user_post_videos",
            {
                "sec_user_id": sec_user_id,
                "max_cursor": 0,
                "count": 20,
                "sort_type": 0,
            },
        ),
    ]


def test_douyin_web_v4_profile_rejects_unsuccessful_inner_status():
    provider = TikHubProvider(
        sdk=FakeTikHubSDK(
            [{"data": {"status_code": 8, "status_msg": "profile unavailable"}}]
        )
    )

    with pytest.raises(TikHubBusinessRequestError):
        asyncio.run(
            provider.get_account(
                TikHubAccountDetailRequest(
                    platform="douyin",
                    userId="MS4wLjABAAA-failed",
                )
            )
        )


def test_douyin_account_handle_uses_unique_id_profile_endpoint_directly():
    client = FakeTikHubSDK(
        [
            {
                "data": {
                    "status_code": 0,
                    "user": {
                        "short_id": "335476752",
                        "unique_id": "",
                        "sec_uid": "MS4wLjABAAA-stable",
                        "nickname": "数字抖音号",
                        "mplatform_followers_count": 60,
                    },
                }
            }
        ]
    )
    provider = TikHubProvider(sdk=client)

    account = asyncio.run(
        provider.get_account(
            TikHubAccountDetailRequest(
                platform="douyin",
                accountId="335476752",
            )
        )
    )

    assert account.accountId == "335476752"
    assert account.userId == "MS4wLjABAAA-stable"
    assert account.followers == 60
    assert client.calls == [
        (
            "douyin_web",
            "handler_user_profile_v2",
            {"unique_id": "335476752"},
        )
    ]


def test_douyin_creator_crawl_uses_stored_sec_user_id():
    client = FakeTikHubSDK(
        [
            {"data": {"user": {"sec_uid": "stored-sec-id", "nickname": "作者"}}},
            {"data": {"aweme_list": [], "has_more": False}},
        ]
    )
    service = TikHubCrawlService(TikHubProvider(sdk=client))
    partial_results = []

    result = asyncio.run(
        service.crawl_by_creator(
            creator_url="https://www.douyin.com/user/url-sec-id",
            sec_user_id="stored-sec-id",
            on_partial_result=lambda partial: partial_results.append(
                (len(client.calls), partial.creators[0]["display_name"])
            ),
        )
    )

    assert partial_results == [(1, "作者")]
    assert result.creators[0]["sec_user_id"] == "stored-sec-id"
    assert [call[2]["sec_user_id"] for call in client.calls] == [
        "stored-sec-id",
        "stored-sec-id",
    ]
    assert all(operation != "get_sec_user_id" for _, operation, _ in client.calls)


def test_douyin_creator_crawl_hydrates_recent_work_with_v3_detail():
    now = datetime.now(UTC)
    client = FakeTikHubSDK(
        [
            {"data": {"user": {"sec_uid": "stored-sec-id", "nickname": "作者"}}},
            {
                "data": {
                    "aweme_list": [
                        {
                            "aweme_id": "recent-aweme",
                            "desc": "列表标题",
                            "create_time": int(now.timestamp()),
                        }
                    ],
                    "has_more": False,
                }
            },
            {
                "data": {
                    "aweme_detail": {
                        "aweme_id": "recent-aweme",
                        "desc": "详情标题",
                        "create_time": int(now.timestamp()),
                        "statistics": {
                            "digg_count": 321,
                            "collect_count": 54,
                            "comment_count": 7,
                            "share_count": 8,
                            "play_count": 999,
                        },
                        "video": {
                            "cover": {
                                "url_list": [
                                    "https://p3.douyinpic.com/aweme/recent-aweme.heic?x-signature=heic-signature",
                                    "https://p3.douyinpic.com/aweme/recent-aweme.jpeg?x-signature=jpeg-signature",
                                ]
                            }
                        },
                    }
                }
            },
        ]
    )
    service = TikHubCrawlService(TikHubProvider(sdk=client))

    result = asyncio.run(
        service.crawl_by_creator(
            creator_url="https://www.douyin.com/user/stored-sec-id",
            sec_user_id="stored-sec-id",
            recent_since=now - timedelta(days=7),
        )
    )

    assert result.contents[0]["liked_count"] == 321
    assert result.contents[0]["collected_count"] == 54
    assert result.contents[0]["view_count"] == 999
    assert result.contents[0]["cover_url"] == (
        "https://p3.douyinpic.com/aweme/recent-aweme.jpeg?x-signature=jpeg-signature"
    )
    assert result.contents[0]["aweme_url"] == (
        "https://www.douyin.com/video/recent-aweme"
    )
    assert client.calls[-1] == (
        "douyin_app_v3",
        "fetch_one_video_v3",
        {"aweme_id": "recent-aweme"},
    )


def test_xiaohongshu_creator_crawl_hydrates_only_recent_details_and_keeps_token_url():
    now = datetime.now(UTC)
    client = FakeTikHubSDK(
        [
            {"data": {"data": {"userid": "xhs-user", "nickname": "作者"}}},
            {
                "data": {
                    "data": {
                        "notes": [
                            {
                                "id": "recent-note",
                                "title": "近期笔记",
                                "create_time": int(now.timestamp()),
                                "type": "normal",
                            },
                            {
                                "id": "old-note",
                                "title": "历史笔记",
                                "create_time": int((now - timedelta(days=8)).timestamp()),
                                "type": "normal",
                            },
                        ],
                        "has_more": True,
                    }
                }
            },
            {
                "data": {
                    "data": [
                        {
                            "note_list": [
                                {
                                    "id": "recent-note",
                                    "title": "近期笔记详情",
                                    "create_time": int(now.timestamp()),
                                    "liked_count": 123,
                                    "collected_count": 45,
                                    "comments_count": 6,
                                    "mini_program_info": {
                                        "webpage_url": (
                                            "https://www.xiaohongshu.com/discovery/item/"
                                            "recent-note?xsec_source=app_share&xsec_token=token-value"
                                        )
                                    },
                                }
                            ]
                        }
                    ]
                }
            },
        ]
    )
    service = TikHubCrawlService(TikHubProvider(sdk=client))

    result = asyncio.run(
        service.crawl_by_creator(
            creator_url="https://www.xiaohongshu.com/user/profile/xhs-user",
            recent_since=now - timedelta(days=7),
            max_notes_count=100,
        )
    )

    assert len(result.contents) == 2
    assert result.contents[0]["note_id"] == "recent-note"
    assert result.contents[0]["liked_count"] == 123
    assert result.contents[0]["collected_count"] == 45
    assert "xsec_token=token-value" in result.contents[0]["note_url"]
    assert result.contents[1]["note_id"] == "old-note"
    assert [operation for _, operation, _ in client.calls] == [
        "get_user_info",
        "get_user_posted_notes",
        "get_image_note_detail",
    ]


def test_xiaohongshu_account_contents_and_kuaishou_detail_are_normalized():
    client = FakeTikHubSDK(
        [
            {
                "data": {
                    "data": {
                        "share_link": (
                            "https://www.xiaohongshu.com/user/profile/"
                            "5ce74ebb0000000018005631?xsec_token=profile-token&"
                            "xsec_source=app_share"
                        ),
                        "notes": [
                            {
                                "note_id": "xhs-1",
                                "title": "笔记",
                                "user": {"nickname": "小红书作者"},
                            }
                        ],
                        "has_more": False,
                    }
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
    assert xhs_page.contents[0].authorUrl == (
        "https://www.xiaohongshu.com/user/profile/"
        "5ce74ebb0000000018005631?xsec_token=profile-token&"
        "xsec_source=app_share"
    )
    assert client.calls[0][0:2] == (
        "xiaohongshu_app_v2",
        "get_user_posted_notes",
    )
    assert client.calls[0][2] == {"cursor": None, "user_id": "u-1"}
    assert ks_content.contentId == "ks-1"
    assert ks_content.authorName == "快手作者"
    assert ks_content.likeCount == 9


@pytest.mark.parametrize(
    ("identity", "expected_params"),
    [
        (
            "https://www.xiaohongshu.com/user/profile/66c00ad8000000001d022c50",
            {"user_id": "66c00ad8000000001d022c50"},
        ),
        (
            "https://xhslink.com/m/3ZSCJZAMz0a",
            {"share_text": "https://xhslink.com/m/3ZSCJZAMz0a"},
        ),
    ],
)
def test_xiaohongshu_account_identity_uses_supported_parameter(
    identity,
    expected_params,
):
    client = FakeTikHubSDK(
        [{"data": {"user": {"user_id": "xhs-user", "nickname": "作者"}}}]
    )
    provider = TikHubProvider(sdk=client)

    asyncio.run(
        provider.get_account(
            TikHubAccountDetailRequest(
                platform="xiaohongshu",
                authorUrl=identity,
            )
        )
    )

    assert client.calls == [
        ("xiaohongshu_app_v2", "get_user_info", expected_params)
    ]


def test_xiaohongshu_app_v2_account_metrics_are_normalized():
    client = FakeTikHubSDK(
        [
            {
                "data": {
                    "data": {
                        "userid": "66c00ad8000000001d022c50",
                        "nickname": "晴有时 | 学习日记🌻",
                        "desc": "今天也在努力学习鸭！",
                        "imageb": "https://cdn.example.test/xhs-avatar.webp",
                        "fans": 186,
                        "follows": 6,
                        "ndiscovery": 21,
                        "liked": 415,
                    }
                }
            }
        ]
    )
    provider = TikHubProvider(sdk=client)

    account = asyncio.run(
        provider.get_account(
            TikHubAccountDetailRequest(
                platform="xiaohongshu",
                userId="66c00ad8000000001d022c50",
            )
        )
    )

    assert account.userId == "66c00ad8000000001d022c50"
    assert account.avatarUrl == "https://cdn.example.test/xhs-avatar.webp"
    assert account.followers == 186
    assert account.follows == 6
    assert account.contentCount == 21
    assert account.totalLikes == 415


def test_douyin_account_uses_large_avatar():
    client = FakeTikHubSDK(
        [
            {
                "data": {
                    "user": {
                        "sec_uid": "sec-1",
                        "nickname": "作者",
                        "avatar_thumb": {
                            "url_list": ["https://cdn.example.test/avatar-small.jpg"]
                        },
                        "avatar_larger": {
                            "url_list": [
                                "https://p3.douyinpic.com/aweme/avatar-large.heic?from=profile",
                                "https://p3.douyinpic.com/aweme/avatar-large.jpeg?from=profile",
                            ]
                        },
                    }
                }
            }
        ]
    )
    provider = TikHubProvider(sdk=client)

    account = asyncio.run(
        provider.get_account(
            TikHubAccountDetailRequest(platform="douyin", userId="sec-1")
        )
    )

    assert account.avatarUrl == (
        "https://p3.douyinpic.com/aweme/avatar-large.jpeg?from=profile"
    )


@pytest.mark.parametrize(
    ("aweme_type", "images", "expected"),
    [
        (0, None, "video"),
        (68, [{"url_list": ["https://example.test/image.jpeg"]}], "image"),
    ],
)
def test_douyin_aweme_type_is_normalized_for_dashboard_structure(
    aweme_type,
    images,
    expected,
):
    client = FakeTikHubSDK(
        [
            {
                "data": {
                    "aweme_list": [
                        {
                            "aweme_id": f"content-{aweme_type}",
                            "aweme_type": aweme_type,
                            "images": images,
                            "video": {"cover": {"url_list": []}},
                        }
                    ],
                    "has_more": False,
                }
            }
        ]
    )

    page = asyncio.run(
        TikHubProvider(sdk=client).list_account_contents(
            TikHubAccountContentsRequest(
                platform="douyin",
                secUserId="sec-user",
            )
        )
    )

    assert page.contents[0].contentType == expected


def test_account_record_uses_profile_link_from_recent_xiaohongshu_content():
    service = TikHubCrawlService(
        provider=SimpleNamespace(provider_name="tikhub")  # type: ignore[arg-type]
    )

    record = service._account_record(
        "xhs",
        TikHubAccount(
            platform="xiaohongshu",
            accountId="69a139280000000021006a8d",
            name="小红书作者",
        ),
        recent_contents=[
            TikHubContent(
                platform="xiaohongshu",
                contentId="xhs-1",
                authorUrl=(
                    "https://www.xiaohongshu.com/user/profile/"
                    "5ce74ebb0000000018005631?xsec_token=profile-token&"
                    "xsec_source=app_share"
                ),
            )
        ],
    )

    assert record["profile_url"] == (
        "https://www.xiaohongshu.com/user/profile/"
        "5ce74ebb0000000018005631?xsec_token=profile-token&"
        "xsec_source=app_share"
    )


def test_sparse_account_details_do_not_erase_discovered_profile_link():
    discovered = TikHubAccount(
        platform="xiaohongshu",
        accountId="red-id",
        userId="5ce74ebb0000000018005631",
        name="搜索账号名",
        profileUrl=(
            "https://www.xiaohongshu.com/user/profile/"
            "5ce74ebb0000000018005631"
        ),
        followers=100,
    )
    hydrated = TikHubAccount(
        platform="xiaohongshu",
        accountId="red-id",
        name="详情账号名",
        followers=200,
    )

    merged = _merge_account_details(discovered, hydrated)

    assert merged.name == "详情账号名"
    assert merged.followers == 200
    assert merged.userId == "5ce74ebb0000000018005631"
    assert merged.profileUrl == (
        "https://www.xiaohongshu.com/user/profile/"
        "5ce74ebb0000000018005631"
    )


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
        "get_image_note_detail",
    )
    assert all(resource != "xiaohongshu_app" for resource, _, _ in client.calls)


def test_xiaohongshu_detail_falls_back_when_success_payload_is_empty():
    client = FakeTikHubSDK(
        [
            {"data": {"code": 0, "success": True, "data": {}, "msg": "成功"}},
            {
                "data": {
                    "data": [
                        {
                            "note_list": [
                                {
                                    "id": "video-1",
                                    "type": "video",
                                    "liked_count": 46,
                                    "comments_count": 1,
                                    "collected_count": 12,
                                    "mini_program_info": {
                                        "webpage_url": (
                                            "https://www.xiaohongshu.com/discovery/item/"
                                            "video-1?xsec_source=app_share&xsec_token=token-1"
                                        )
                                    },
                                }
                            ]
                        }
                    ]
                }
            },
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

    assert content.likeCount == 46
    assert content.commentCount == 1
    assert content.collectCount == 12
    assert "xsec_token=token-1" in content.contentUrl
    assert [operation for _, operation, _ in client.calls] == [
        "get_image_note_detail",
        "get_video_note_detail",
    ]


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


class DetailHydrationProvider:
    provider_name = "tikhub"

    def __init__(self) -> None:
        self.detail_calls: list[str] = []

    async def search_contents(self, request: TikHubSearchRequest) -> TikHubContentPage:
        return TikHubContentPage(
            platform=request.platform,
            contents=[
                TikHubContent(
                    platform=request.platform,
                    contentId=f"content-{index}",
                    authorId=f"author-{index}",
                    authorName=f"作者{index}",
                    authorUrl=f"https://www.douyin.com/user/author-{index}",
                )
                for index in range(3)
            ],
        )

    async def get_account(self, request: TikHubAccountDetailRequest) -> TikHubAccount:
        self.detail_calls.append(request.userId)
        index = int(request.userId.rsplit("-", 1)[-1])
        return TikHubAccount(
            platform=request.platform,
            accountId=request.userId,
            userId=request.userId,
            name=f"详情作者{index}",
            avatarUrl=f"https://example.com/avatar-{index}.jpg",
            followers=10_000 + index,
            contentCount=100 + index,
            totalLikes=200_000 + index,
        )


def test_account_report_hydrates_only_bounded_douyin_creator_details():
    provider = DetailHydrationProvider()
    service = TikHubCrawlService(provider=provider)  # type: ignore[arg-type]

    result = asyncio.run(
        service.crawl_by_keyword(
            keywords=["护肤"],
            platform="dy",
            hydrate_douyin_creator_details=True,
            max_creator_details=2,
        )
    )

    assert provider.detail_calls == ["author-0", "author-1"]
    creators = {item["user_id"]: item for item in result.creators}
    assert creators["author-0"]["avatar_url"] == "https://example.com/avatar-0.jpg"
    assert creators["author-0"]["fans_count"] == 10_000
    assert creators["author-0"]["works_count"] == 100
    assert creators["author-0"]["liked_count"] == 200_000
    assert creators["author-2"]["fans_count"] == 0
    assert result.source_operations == ["search_contents:default", "get_account"]


def test_xiaohongshu_never_hydrates_creator_details():
    provider = DetailHydrationProvider()
    service = TikHubCrawlService(provider=provider)  # type: ignore[arg-type]

    asyncio.run(
        service.crawl_by_keyword(
            keywords=["护肤"],
            platform="xhs",
            hydrate_douyin_creator_details=True,
        )
    )

    assert provider.detail_calls == []


def test_reference_discovery_uses_only_keyword_content_search_cards():
    author = {"sec_uid": "sec-peer", "nickname": "露营作者"}
    client = FakeTikHubSDK(
        [
            {
                "data": {
                    "business_data": [
                        {
                            "data": {
                                "aweme_info": {
                                    "aweme_id": "keyword-hit-1",
                                    "desc": "露营装备清单",
                                    "author": author,
                                    "statistics": {
                                        "digg_count": 50_000,
                                        "comment_count": 800,
                                        "share_count": 600,
                                        "collect_count": 2_000,
                                        "play_count": 900_000,
                                    },
                                }
                            }
                        }
                    ],
                    "has_more": False,
                }
            },
            {"data": {"business_data": [], "has_more": False}},
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
    hit = next(item for item in result.contents if item["aweme_id"] == "keyword-hit-1")
    assert peer["profile_url"] == "https://www.douyin.com/user/sec-peer"
    assert peer["matched_queries"] == ["露营"]
    assert hit["liked_count"] == 50_000
    assert hit["comment_count"] == 800
    assert hit["share_count"] == 600
    assert hit["collected_count"] == 2_000
    assert hit["view_count"] == 900_000
    assert hit["source_operation"] == "search_contents"
    assert hit["source_keyword"] == "露营"
    assert {
        (resource, operation) for resource, operation, _ in client.calls
    } == {("douyin_search", "fetch_video_search_v2")}


def test_all_current_social_platforms_are_supported():
    assert set(TikHubPlatform) == {
        TikHubPlatform.DOUYIN,
        TikHubPlatform.XIAOHONGSHU,
        TikHubPlatform.KUAISHOU,
    }
