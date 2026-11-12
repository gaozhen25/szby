import asyncio

import pytest

from app.services.mediaspider.account_lookup import MediaSpiderAccountLookup
from app.services.mediaspider.models import InvalidCrawlRequestError


class FakeDouyinClient:
    def __init__(self, *, cookie):
        assert cookie == "dy-cookie"

    def get_profile_bundle(self, target):
        return {
            "exact_match": target == "douyin-id",
            "creators": [
                {
                    "display_name": "抖音账号",
                    "profile_url": (
                        "https://www.douyin.com/user/MS4wLjAB-resolved"
                        "?from_tab_name=main"
                    ),
                }
            ],
        }

    def get_creator_bundle(self, target, *, max_notes, with_posts):
        assert target == "https://www.douyin.com/user/MS4wLjAB-link"
        assert max_notes == 1
        assert with_posts is False
        return {
            "creators": [
                {
                    "display_name": "链接账号",
                    "profile_url": target,
                }
            ]
        }


class FakeXhsClient:
    def __init__(self, *, cookie):
        assert cookie == "xhs-cookie"

    def get_profile_bundle(self, target):
        return {
            "exact_match": target == "red-id",
            "creators": [
                {
                    "display_name": "小红书账号",
                    "profile_url": (
                        "https://www.xiaohongshu.com/user/profile/user-id"
                        "?xsec_token=private-token&xsec_source=pc_search"
                    ),
                }
            ],
        }

    def get_creator_info(self, user_id, *, xsec_token, xsec_source):
        assert user_id == "linked-user-id"
        assert xsec_token == "link-token"
        assert xsec_source == "pc_search"
        return {
            "basicInfo": {
                "nickname": "主页链接账号",
                "desc": "公开简介",
            },
            "interactions": [],
        }


def _lookup():
    return MediaSpiderAccountLookup(
        douyin_client_factory=FakeDouyinClient,
        xhs_client_factory=FakeXhsClient,
    )


@pytest.mark.parametrize(
    ("platform", "target", "cookie", "expected_url"),
    [
        (
            "抖音",
            "douyin-id",
            "dy-cookie",
            "https://www.douyin.com/user/MS4wLjAB-resolved",
        ),
        (
            "小红书",
            "red-id",
            "xhs-cookie",
            "https://www.xiaohongshu.com/user/profile/user-id",
        ),
    ],
)
def test_account_lookup_resolves_exact_platform_id(
    platform,
    target,
    cookie,
    expected_url,
):
    creator = asyncio.run(
        _lookup().resolve(platform=platform, target=target, cookies=cookie)
    )

    assert creator["profile_url"] == expected_url
    assert creator["source_provider"] == "mediaspider"
    assert creator["source_operations"] == ["get_account"]


def test_account_lookup_resolves_xhs_profile_url_without_persisting_token():
    creator = asyncio.run(
        _lookup().resolve(
            platform="小红书",
            target=(
                "https://www.xiaohongshu.com/user/profile/linked-user-id"
                "?xsec_token=link-token&xsec_source=pc_search"
            ),
            cookies="xhs-cookie",
        )
    )

    assert creator["display_name"] == "主页链接账号"
    assert creator["profile_url"] == (
        "https://www.xiaohongshu.com/user/profile/linked-user-id"
    )


def test_account_lookup_rejects_fuzzy_account_id_match():
    with pytest.raises(InvalidCrawlRequestError, match="精确匹配"):
        asyncio.run(
            _lookup().resolve(
                platform="小红书",
                target="similar-name",
                cookies="xhs-cookie",
            )
        )


def test_account_lookup_rejects_platform_url_mismatch():
    with pytest.raises(InvalidCrawlRequestError, match="平台不一致"):
        asyncio.run(
            _lookup().resolve(
                platform="抖音",
                target="https://www.xiaohongshu.com/user/profile/user-id",
                cookies="dy-cookie",
            )
        )
