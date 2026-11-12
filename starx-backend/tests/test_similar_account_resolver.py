import asyncio
from types import SimpleNamespace

from app.services.account_report.similar_accounts.resolver import SimilarAccountResolver


class FakeCookiePool:
    def has_cookies(self, platform):
        return platform in {"xhs", "dy"}

    def candidates(self, platform):
        return (f"{platform}-cookie",)


class RecordingLookup:
    def __init__(self):
        self.requests = []

    async def resolve(self, *, platform, target, cookies):
        self.requests.append((platform, target, cookies))
        return {
            "display_name": "精确账号",
            "profile_url": "https://www.xiaohongshu.com/user/profile/user-id",
            "avatar": "https://example.test/avatar.png",
            "bio": "公开简介",
            "fans_count": 100,
            "following_count": 8,
            "works_count": 12,
            "interaction_count": 900,
            "ip_location": "上海",
        }


class FailingTikHubProvider:
    async def get_account(self, _request):
        raise AssertionError("hybrid 模式的小红书账号不应调用 TikHub")


def test_similar_account_id_uses_mediaspider_in_hybrid_mode():
    lookup = RecordingLookup()
    resolver = SimilarAccountResolver(
        provider=FailingTikHubProvider(),
        mediaspider_lookup=lookup,
        cookie_pool_loader=FakeCookiePool,
        runtime_settings=SimpleNamespace(social_retrieval_provider="hybrid"),
    )

    resolved = asyncio.run(
        resolver.resolve(platform="小红书", account_id="red-id-001")
    )

    assert lookup.requests == [("xhs", "red-id-001", "xhs-cookie")]
    assert resolved == {
        "name": "精确账号",
        "platform": "小红书",
        "profileUrl": "https://www.xiaohongshu.com/user/profile/user-id",
        "avatarUrl": "https://example.test/avatar.png",
        "description": "公开简介",
        "followers": 100,
        "follows": 8,
        "contentCount": 12,
        "totalLikes": 900,
        "ipLocation": "上海",
    }


def test_similar_account_profile_url_uses_mediaspider_in_hybrid_mode():
    lookup = RecordingLookup()
    resolver = SimilarAccountResolver(
        provider=FailingTikHubProvider(),
        mediaspider_lookup=lookup,
        cookie_pool_loader=FakeCookiePool,
        runtime_settings=SimpleNamespace(social_retrieval_provider="hybrid"),
    )

    asyncio.run(
        resolver.resolve(
            profile_url="https://www.xiaohongshu.com/user/profile/user-id"
        )
    )

    assert lookup.requests == [
        (
            "xhs",
            "https://www.xiaohongshu.com/user/profile/user-id",
            "xhs-cookie",
        )
    ]
