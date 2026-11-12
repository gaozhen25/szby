"""平台展示账号号到 TikHub 稳定身份的解析。"""

from __future__ import annotations

from typing import Any

from app.services.tikhub_service import (
    TikHubAccount,
    TikHubAccountDetailRequest,
    TikHubPlatform,
    TikHubProvider,
    TikHubSearchRequest,
)

PLATFORM_MAP = {
    "抖音": TikHubPlatform.DOUYIN,
    "小红书": TikHubPlatform.XIAOHONGSHU,
}


def _normalized(value: Any) -> str:
    return str(value or "").strip().casefold()


async def resolve_platform_account(
    provider: TikHubProvider,
    *,
    platform_name: str,
    platform_account: str,
    cached: dict[str, Any] | None = None,
) -> tuple[TikHubAccount | None, dict[str, Any] | None]:
    """精确匹配展示账号号，拒绝把相似昵称静默绑定成当前账号。"""

    social_platform = PLATFORM_MAP.get(platform_name)
    handle = platform_account.strip()
    if social_platform is None or not handle:
        return None, None

    cached = cached or {}
    if (
        _normalized(cached.get("input")) == _normalized(handle)
        and str(cached.get("userId") or "").strip()
    ):
        account = await provider.get_account(
            TikHubAccountDetailRequest(
                platform=social_platform,
                userId=str(cached["userId"]),
                accountId=str(cached.get("accountId") or cached["userId"]),
            )
        )
    elif social_platform == TikHubPlatform.DOUYIN:
        account = await provider.get_account(
            TikHubAccountDetailRequest(
                platform=social_platform,
                accountId=handle,
            )
        )
        if _normalized(account.accountId) != _normalized(handle):
            return None, None
    else:
        page = await provider.search_accounts(
            TikHubSearchRequest(
                platform=social_platform,
                keyword=handle,
                pageSize=20,
            )
        )
        matches = [
            item
            for item in page.accounts
            if _normalized(item.accountId) == _normalized(handle)
        ]
        if len(matches) != 1:
            return None, None
        selected = matches[0]
        account = await provider.get_account(
            TikHubAccountDetailRequest(
                platform=social_platform,
                userId=selected.userId,
                accountId=selected.accountId or selected.userId,
            )
        )
        if not account.accountId:
            account.accountId = selected.accountId
        if not account.userId:
            account.userId = selected.userId

    identity = {
        "input": handle,
        "accountId": account.accountId,
        "userId": account.userId,
        "profileUrl": account.profileUrl,
        "displayName": account.name,
    }
    return account, identity
