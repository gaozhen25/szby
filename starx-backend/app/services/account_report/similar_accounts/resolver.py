"""解析待添加的相似账号，支持平台号值和公开主页链接。"""

from typing import Any

from app.core.config import settings
from app.services.mediaspider.account_lookup import MediaSpiderAccountLookup
from app.services.mediaspider.cookie_pool import (
    CookiePoolConfigurationError,
    load_cookie_pool,
    run_with_cookie_candidates,
)
from app.services.mediaspider.failure_catalog import public_crawler_failure
from app.services.mediaspider.models import (
    CrawlResult,
    CrawlerExecutionError,
    InvalidCrawlRequestError,
)
from app.services.mediaspider.platform_resolver import (
    normalize_platform,
    resolve_creator_platform,
)
from app.services.social_retrieval import RetrievalBackend, backend_for_platform
from app.services.tikhub_service import (
    TikHubAccountDetailRequest,
    TikHubPlatform,
    TikHubProvider,
)


PLATFORM_DETAILS = {
    "xhs": (TikHubPlatform.XIAOHONGSHU, "小红书"),
    "dy": (TikHubPlatform.DOUYIN, "抖音"),
    "ks": (TikHubPlatform.KUAISHOU, "快手"),
}


class SimilarAccountResolver:
    def __init__(
        self,
        provider: TikHubProvider | None = None,
        *,
        mediaspider_lookup: MediaSpiderAccountLookup | None = None,
        cookie_pool_loader=load_cookie_pool,
        runtime_settings: Any = settings,
    ) -> None:
        self.provider = provider or TikHubProvider()
        self.mediaspider_lookup = mediaspider_lookup or MediaSpiderAccountLookup()
        self.cookie_pool_loader = cookie_pool_loader
        self.runtime_settings = runtime_settings

    async def resolve(
        self,
        profile_url: str = "",
        *,
        platform: str = "",
        account_id: str = "",
    ) -> dict[str, Any]:
        requested_url = str(profile_url or "").strip()
        requested_id = str(account_id or "").strip()
        if bool(requested_url) == bool(requested_id):
            raise InvalidCrawlRequestError(
                "accountId 和 profileUrl 必须且只能提供一个"
            )

        if requested_id:
            if not str(platform or "").strip():
                raise InvalidCrawlRequestError("使用 accountId 时必须提供 platform")
            platform_code = normalize_platform(platform)
        else:
            platform_code = resolve_creator_platform(requested_url)
            if platform and normalize_platform(platform) != platform_code:
                raise InvalidCrawlRequestError("platform 与主页链接平台不一致")

        if (
            backend_for_platform(self.runtime_settings, platform_code)
            == RetrievalBackend.MEDIASPIDER
        ):
            creator = await self._resolve_with_mediaspider(
                platform_code,
                requested_id or requested_url,
            )
            return _creator_to_resolved_account(platform_code, creator)

        return await self._resolve_with_tikhub(
            platform_code,
            account_id=requested_id,
            profile_url=requested_url,
        )

    async def _resolve_with_mediaspider(
        self,
        platform: str,
        target: str,
    ) -> dict[str, Any]:
        try:
            pool = self.cookie_pool_loader()
        except CookiePoolConfigurationError as exc:
            raise _credentials_missing_error(platform, exc) from exc
        if not pool.has_cookies(platform):
            raise _credentials_missing_error(
                platform,
                ValueError("cookie pool empty"),
            )
        return await run_with_cookie_candidates(
            pool,
            platform,
            lambda cookie: self.mediaspider_lookup.resolve(
                platform=platform,
                target=target,
                cookies=cookie,
            ),
        )

    async def _resolve_with_tikhub(
        self,
        platform_code: str,
        *,
        account_id: str,
        profile_url: str,
    ) -> dict[str, Any]:
        platform, platform_name = PLATFORM_DETAILS[platform_code]
        account = await self.provider.get_account(
            TikHubAccountDetailRequest(
                platform=platform,
                accountId=account_id or profile_url,
                authorUrl=profile_url,
            )
        )
        if not account.name.strip():
            raise ValueError("未能识别账号名称")
        if not account.profileUrl.strip():
            raise ValueError("未能识别公开账号主页")
        return {
            "name": account.name.strip(),
            "platform": platform_name,
            "profileUrl": account.profileUrl.strip(),
            "avatarUrl": account.avatarUrl.strip(),
            "description": account.description.strip(),
            "followers": account.followers,
            "follows": account.follows,
            "contentCount": account.contentCount,
            "totalLikes": account.totalLikes,
            "ipLocation": account.ipLocation.strip(),
        }


def _public_count(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    try:
        return max(int(value), 0)
    except (TypeError, ValueError):
        return 0


def _credentials_missing_error(
    platform: str,
    cause: BaseException,
) -> CrawlerExecutionError:
    return CrawlerExecutionError(
        platform,
        cause,
        CrawlResult(platform=platform, crawl_type="creator"),
        failure=public_crawler_failure("credentials_missing"),
    )


def _creator_to_resolved_account(
    platform_code: str,
    creator: dict[str, Any],
) -> dict[str, Any]:
    name = str(creator.get("display_name") or creator.get("nickname") or "").strip()
    profile_url = str(creator.get("profile_url") or "").strip()
    if not name:
        raise ValueError("未能识别账号名称")
    if not profile_url:
        raise ValueError("未能识别公开账号主页")
    return {
        "name": name,
        "platform": PLATFORM_DETAILS[platform_code][1],
        "profileUrl": profile_url,
        "avatarUrl": str(
            creator.get("avatar") or creator.get("avatar_url") or ""
        ).strip(),
        "description": str(
            creator.get("bio") or creator.get("desc") or ""
        ).strip(),
        "followers": _public_count(creator.get("fans_count")),
        "follows": _public_count(creator.get("following_count")),
        "contentCount": _public_count(creator.get("works_count")),
        "totalLikes": _public_count(
            creator.get("liked_count") or creator.get("interaction_count")
        ),
        "ipLocation": str(creator.get("ip_location") or "").strip(),
    }
