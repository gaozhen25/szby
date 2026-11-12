"""根据公开主页链接解析待添加的相似账号。"""

from typing import Any

from app.services.mediaspider.platform_resolver import resolve_creator_platform
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
    def __init__(self, provider: TikHubProvider | None = None) -> None:
        self.provider = provider or TikHubProvider()

    async def resolve(self, profile_url: str) -> dict[str, Any]:
        requested_url = str(profile_url or "").strip()
        platform_code = resolve_creator_platform(requested_url)
        platform, platform_name = PLATFORM_DETAILS[platform_code]
        account = await self.provider.get_account(
            TikHubAccountDetailRequest(
                platform=platform,
                accountId=requested_url,
                authorUrl=requested_url,
            )
        )
        if not account.name.strip():
            raise ValueError("未能从该链接识别账号名称")
        if not account.profileUrl.strip():
            raise ValueError("未能从该链接识别公开账号主页")
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
