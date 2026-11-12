"""TikHub 全局进程内及 Redis 分布式限流。"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from typing import Any

from redis.asyncio import Redis

logger = logging.getLogger(__name__)


class TikHubRateLimiter:
    def __init__(
        self,
        *,
        qps: int,
        redis_url: str,
        redis_client: Any | None = None,
        key_prefix: str = "starx:tikhub:qps",
    ) -> None:
        self.qps = max(int(qps), 1)
        self._events: deque[float] = deque()
        self._lock = asyncio.Lock()
        self._redis = redis_client or Redis.from_url(
            redis_url,
            decode_responses=True,
            socket_connect_timeout=0.2,
            socket_timeout=0.2,
        )
        self._owns_redis = redis_client is None
        self._key_prefix = key_prefix
        self._redis_disabled_until = 0.0

    async def acquire(self) -> None:
        await self._acquire_local()
        if time.monotonic() < self._redis_disabled_until:
            return
        try:
            await self._acquire_distributed()
        except Exception as exc:  # Redis 故障不能阻断 TikHub 主链路。
            self._redis_disabled_until = time.monotonic() + 30
            logger.warning(
                "TikHub distributed rate limiter unavailable; using local limiter: %s",
                type(exc).__name__,
            )

    async def _acquire_local(self) -> None:
        while True:
            async with self._lock:
                now = time.monotonic()
                while self._events and now - self._events[0] >= 1:
                    self._events.popleft()
                if len(self._events) < self.qps:
                    self._events.append(now)
                    return
                delay = max(1 - (now - self._events[0]), 0.001)
            await asyncio.sleep(delay)

    async def _acquire_distributed(self) -> None:
        while True:
            bucket = int(time.time())
            key = f"{self._key_prefix}:{bucket}"
            count = int(await self._redis.incr(key))
            if count == 1:
                await self._redis.expire(key, 2)
            if count <= self.qps:
                return
            await asyncio.sleep(max((bucket + 1) - time.time(), 0.01))

    async def aclose(self) -> None:
        if self._owns_redis:
            close = getattr(self._redis, "aclose", None)
            if callable(close):
                await close()
