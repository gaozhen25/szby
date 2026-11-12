"""MediaSpider workflow 局部 Cookie 池。"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from pathlib import Path
from threading import Lock

from app.core.config import BASE_DIR

from .models import CrawlResult, CrawlerExecutionError

PLATFORMS = ("xhs", "dy", "ks")
COOKIE_POOL_PATH = BASE_DIR / "cookies" / "cookies.json"


class CookiePoolConfigurationError(Exception):
    """Cookie 池文件不可用，异常信息不得包含路径或文件内容。"""

    def __init__(self):
        super().__init__("Cookie 池配置不可用")


class RoundRobinCursor:
    """仅保存平台轮询位置，不保存任何 Cookie 内容。"""

    def __init__(self):
        self._next_by_platform: dict[str, int] = {}
        self._lock = Lock()

    def candidates(
        self,
        platform: str,
        cookies: tuple[str, ...],
    ) -> tuple[str, ...]:
        if not cookies:
            return ()
        with self._lock:
            start = self._next_by_platform.get(platform, 0) % len(cookies)
            self._next_by_platform[platform] = (start + 1) % len(cookies)
        return cookies[start:] + cookies[:start]


PROCESS_COOKIE_CURSOR = RoundRobinCursor()


class WorkflowCookiePool:
    """一次 workflow 独享的 Cookie 快照。"""

    __slots__ = ("_cookies", "_cursor")

    def __init__(
        self,
        cookies: dict[str, tuple[str, ...]],
        cursor: RoundRobinCursor,
    ):
        self._cookies = cookies
        self._cursor = cursor

    def __repr__(self) -> str:
        return "WorkflowCookiePool(<redacted>)"

    def has_cookies(self, platform: str) -> bool:
        return bool(self._platform_cookies(platform))

    def candidates(self, platform: str) -> tuple[str, ...]:
        return self._cursor.candidates(platform, self._platform_cookies(platform))

    def _platform_cookies(self, platform: str) -> tuple[str, ...]:
        if platform not in PLATFORMS:
            raise ValueError("unsupported MediaSpider platform")
        return self._cookies[platform]


def load_cookie_pool(
    path: Path = COOKIE_POOL_PATH,
    *,
    cursor: RoundRobinCursor = PROCESS_COOKIE_CURSOR,
) -> WorkflowCookiePool:
    """从磁盘创建新快照；不缓存文件内容或解析结果。"""

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise CookiePoolConfigurationError() from None

    if not isinstance(raw, dict) or set(raw) - set(PLATFORMS):
        raise CookiePoolConfigurationError()

    parsed: dict[str, tuple[str, ...]] = {}
    for platform in PLATFORMS:
        values = raw.get(platform, [])
        if not isinstance(values, list) or any(
            not isinstance(item, str) for item in values
        ):
            raise CookiePoolConfigurationError()
        parsed[platform] = tuple(
            dict.fromkeys(item.strip() for item in values if item.strip())
        )

    return WorkflowCookiePool(parsed, cursor)


async def run_with_cookie_candidates(
    cookie_pool: WorkflowCookiePool,
    platform: str,
    operation: Callable[[str], Awaitable[CrawlResult]],
) -> CrawlResult:
    """认证失效时轮换 Cookie，其他错误保持原有失败语义。"""

    last_authentication_error: CrawlerExecutionError | None = None
    for cookie in cookie_pool.candidates(platform):
        try:
            return await operation(cookie)
        except CrawlerExecutionError as exc:
            if exc.failure.code != "credentials_expired":
                raise
            last_authentication_error = exc
    if last_authentication_error is not None:
        raise last_authentication_error
    raise ValueError("平台 Cookie 池为空")
