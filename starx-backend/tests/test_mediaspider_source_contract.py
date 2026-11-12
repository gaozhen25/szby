import pytest
from pydantic import ValidationError

from app.services.mediaspider.http_platforms.adapter import _dict_to_partial
from app.services.mediaspider.http_platforms.douyin.normalize import normalize_aweme
from app.services.mediaspider.models import (
    CrawlerRunConfig,
    InvalidCrawlRequestError,
)


def _config(platform: str, crawl_type: str) -> CrawlerRunConfig:
    values = {
        "platform": platform,
        "crawl_type": crawl_type,
        "cookies": "session=secret",
    }
    if crawl_type == "search":
        values["keywords"] = ["测试"]
    elif crawl_type == "creator":
        values["creator_url"] = "https://example.com/creator"
    else:
        values["content_url"] = "https://example.com/content"
    return CrawlerRunConfig(**values)


@pytest.mark.parametrize(
    ("crawl_type", "expected_operation", "expected_operations"),
    [
        ("search", "search_contents", ["search_contents"]),
        (
            "creator",
            "list_account_contents",
            ["get_account", "list_account_contents"],
        ),
        ("detail", "get_content", ["get_content"]),
    ],
)
def test_http_adapter_adds_uniform_source_metadata(
    crawl_type,
    expected_operation,
    expected_operations,
):
    result = _dict_to_partial(
        _config("xhs", crawl_type),
        {
            "contents": [
                {
                    "note_id": "note-1",
                    "note_url": "https://www.xiaohongshu.com/explore/note-1",
                    "user_id": "author-1",
                }
            ],
            "creators": [{"creator_hash": "creator-1"}],
            "comments": [{"comment_id": "comment-1"}],
        },
    )

    assert result.source_operations == expected_operations
    assert result.contents[0] == {
        "note_id": "note-1",
        "note_url": "https://www.xiaohongshu.com/explore/note-1",
        "user_id": "author-1",
        "content_id": "note-1",
        "public_url": "https://www.xiaohongshu.com/explore/note-1",
        "author_id": "author-1",
        "source_provider": "mediaspider",
        "source_operation": expected_operation,
    }
    assert result.creators[0]["source_provider"] == "mediaspider"
    assert result.creators[0]["source_operations"] == expected_operations
    assert result.comments[0]["source_provider"] == "mediaspider"


def test_douyin_normalizer_keeps_public_author_identity_for_evidence_linking():
    content = normalize_aweme(
        {
            "aweme_id": "aweme-1",
            "desc": "测试作品",
            "author": {
                "sec_uid": "MS4wLjABAAAA-public",
                "nickname": "公开作者",
                "avatar_thumb": {
                    "url_list": [
                        "https://p3.douyinpic.com/avatar-large.jpeg",
                        "https://p3.douyinpic.com/avatar-large.heic",
                    ]
                },
            },
            "statistics": {},
        }
    )

    assert content is not None
    assert content["author_id"] == "MS4wLjABAAAA-public"
    assert content["profile_url"].endswith("/MS4wLjABAAAA-public")
    assert content["avatar"] == "https://p3.douyinpic.com/avatar-large.jpeg"


def test_http_runtime_rejects_silently_ignored_options_and_comments():
    with pytest.raises(ValidationError):
        CrawlerRunConfig(
            platform="dy",
            crawl_type="search",
            keywords=["测试"],
            cookies="session=secret",
            recent_since="2026-07-30",
        )

    with pytest.raises(InvalidCrawlRequestError, match="暂不支持评论采集"):
        CrawlerRunConfig(
            platform="dy",
            crawl_type="search",
            keywords=["测试"],
            cookies="session=secret",
            enable_comments=True,
        )
