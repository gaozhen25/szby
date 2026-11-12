"""TikHub SDK 的 HTTP 传输治理层。"""

from __future__ import annotations

from typing import Any

import httpx

from app.services.tikhub_service.rate_limit import TikHubRateLimiter


class TikHubTransport(httpx.AsyncBaseTransport):
    """在不包装 SDK 方法的前提下统一执行 QPS 和连接并发控制。"""

    def __init__(
        self,
        *,
        qps: int,
        redis_url: str,
        max_connections: int,
        rate_limiter: TikHubRateLimiter | None = None,
        inner: httpx.AsyncBaseTransport | None = None,
        redis_client: Any | None = None,
    ) -> None:
        connection_limit = max(int(max_connections), 1)
        self._rate_limiter = rate_limiter or TikHubRateLimiter(
            qps=qps,
            redis_url=redis_url,
            redis_client=redis_client,
        )
        self._inner = inner or httpx.AsyncHTTPTransport(
            limits=httpx.Limits(
                max_connections=connection_limit,
                max_keepalive_connections=connection_limit,
            )
        )

    async def handle_async_request(
        self,
        request: httpx.Request,
    ) -> httpx.Response:
        await self._rate_limiter.acquire()
        return await self._inner.handle_async_request(request)

    async def aclose(self) -> None:
        try:
            await self._inner.aclose()
        finally:
            await self._rate_limiter.aclose()
