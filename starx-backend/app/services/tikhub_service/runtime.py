"""TikHub 官方 SDK 的进程级生命周期容器。"""

from __future__ import annotations

from collections.abc import Callable
import httpx
from tikhub import AsyncTikHub

from app.core.config import settings
from app.services.tikhub_service.transport import TikHubTransport


class TikHubRuntime:
    """延迟创建并关闭唯一的官方 AsyncTikHub 客户端。"""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout_seconds: int | None = None,
        max_retries: int | None = None,
        max_in_flight: int | None = None,
        client_factory: Callable[..., AsyncTikHub] = AsyncTikHub,
        transport: httpx.AsyncBaseTransport | None = None,
        client: AsyncTikHub | None = None,
    ) -> None:
        self.api_key = settings.tikhub_api_key if api_key is None else api_key
        self.base_url = settings.tikhub_base_url if base_url is None else base_url
        self.timeout_seconds = (
            settings.tikhub_timeout if timeout_seconds is None else timeout_seconds
        )
        self.max_retries = (
            settings.tikhub_max_retries if max_retries is None else max_retries
        )
        self.max_in_flight = max(
            max_in_flight or settings.tikhub_max_in_flight,
            1,
        )
        self._client_factory = client_factory
        self._transport = transport
        self._client = client
        self._owns_client = client is None

    @property
    def client(self) -> AsyncTikHub:
        if self._client is None:
            transport = self._transport or TikHubTransport(
                qps=settings.tikhub_qps,
                redis_url=settings.redis_url,
                max_connections=self.max_in_flight,
            )
            self._client = self._client_factory(
                api_key=self.api_key,
                base_url=self.base_url,
                timeout=self.timeout_seconds,
                max_retries=self.max_retries,
                transport=transport,
            )
        return self._client

    async def aclose(self) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None


default_tikhub_runtime = TikHubRuntime()
