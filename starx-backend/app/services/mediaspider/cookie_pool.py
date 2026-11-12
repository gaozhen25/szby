"""MediaSpider workflow 局部 Cookie 池。"""

from __future__ import annotations

import json
import asyncio
import hashlib
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from threading import Lock
from typing import TypeVar

from app.core.config import BASE_DIR

from .models import CrawlerExecutionError

PLATFORMS = ("xhs", "dy", "ks")
COOKIE_POOL_PATH = BASE_DIR / "cookies" / "cookies.json"
ResultT = TypeVar("ResultT")

# 这些失败可能与当前 Cookie 的登录态、平台对该会话的风控状态，或一次性
# 网络抖动有关。轮换候选 Cookie 可以在不扩大单个 Cookie 并发的前提下恢复。
# 参数、运行时兼容性、额度等全局错误不在此列，避免无意义地重试整池。
ROTATABLE_FAILURE_CODES = frozenset(
    {
        "credentials_expired",
        "platform_blocked",
        "browser_timeout",
        "provider_rate_limited",
        "provider_unavailable",
        "crawler_failed",
    }
)


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


class CookieLeaseRegistry:
    """跨事件循环的进程内 Cookie 独占租约，不在内存索引中保留原文。"""

    def __init__(self) -> None:
        self._leased: set[str] = set()
        self._lock = Lock()

    @staticmethod
    def _key(platform: str, cookie: str) -> str:
        digest = hashlib.sha256(cookie.encode("utf-8")).hexdigest()
        return f"{platform}:{digest}"

    @asynccontextmanager
    async def lease(self, platform: str, cookie: str):
        key = self._key(platform, cookie)
        delay = 0.001
        while True:
            with self._lock:
                if key not in self._leased:
                    self._leased.add(key)
                    break
            await asyncio.sleep(delay)
            delay = min(delay * 2, 0.05)
        try:
            yield
        finally:
            with self._lock:
                self._leased.discard(key)


PROCESS_COOKIE_LEASES = CookieLeaseRegistry()


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

    def cookie_count(self, platform: str) -> int:
        """返回平台可调度凭证数，不暴露 Cookie 内容。"""

        return len(self._platform_cookies(platform))

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
    """从磁盘创建新快照；合并 cookies.json 与所有用户绑定，采集使用全部登录态。"""

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise CookiePoolConfigurationError() from None

    if not isinstance(raw, dict):
        raise CookiePoolConfigurationError()

    try:
        from app.services.mediaspider.http_platforms.common.cookies import (
            iter_bound_cookie_strings,
        )
    except Exception:  # noqa: BLE001
        iter_bound_cookie_strings = None  # type: ignore[assignment]

    parsed: dict[str, tuple[str, ...]] = {}
    for platform in PLATFORMS:
        values = raw.get(platform, [])
        if not isinstance(values, list) or any(
            not isinstance(item, str) for item in values
        ):
            raise CookiePoolConfigurationError()
        merged: list[str] = []
        seen: set[str] = set()
        for item in values:
            text = item.strip()
            if text and text not in seen:
                seen.add(text)
                merged.append(text)
        if iter_bound_cookie_strings is not None:
            for text in iter_bound_cookie_strings(platform):
                if text and text not in seen:
                    seen.add(text)
                    merged.append(text)
        parsed[platform] = tuple(merged)

    return WorkflowCookiePool(parsed, cursor)


async def run_with_cookie_candidates(
    cookie_pool: WorkflowCookiePool,
    platform: str,
    operation: Callable[[str], Awaitable[ResultT]],
    *,
    lease_registry: CookieLeaseRegistry = PROCESS_COOKIE_LEASES,
) -> ResultT:
    """每个 Cookie 同时只服务一个任务；遇到可恢复失败时轮换候选。"""

    last_recoverable_error: CrawlerExecutionError | None = None
    for cookie in cookie_pool.candidates(platform):
        async with lease_registry.lease(platform, cookie):
            try:
                return await operation(cookie)
            except CrawlerExecutionError as exc:
                if exc.failure.code not in ROTATABLE_FAILURE_CODES:
                    raise
                last_recoverable_error = exc
    if last_recoverable_error is not None:
        raise last_recoverable_error
    raise ValueError("平台 Cookie 池为空")
