"""平台登录方式守卫。"""

from collections.abc import Awaitable, Callable

from ..models import CrawlerAuthenticationError

AsyncAction = Callable[[], Awaitable[None]]
AsyncProbe = Callable[[], Awaitable[bool]]


def raise_for_cookie_auth_failure(platform: str, login_type: str) -> None:
    """Cookie 验证失败时终止流程，避免降级为交互登录。"""

    if login_type == "cookie":
        error = CrawlerAuthenticationError(platform)
        raise error


async def ensure_authenticated(
    *,
    platform: str,
    login_type: str,
    probe: AsyncProbe,
    login: AsyncAction,
    refresh: AsyncAction,
) -> None:
    """按固定顺序执行登录、刷新与 Cookie 二次认证。"""

    if await probe():
        return
    await login()
    await refresh()
    if login_type == "cookie" and not await probe():
        raise_for_cookie_auth_failure(platform, login_type)
