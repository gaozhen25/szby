import asyncio

import httpx

from app.services.tikhub_service.rate_limit import TikHubRateLimiter
from app.services.tikhub_service.transport import TikHubTransport


class FakeRedis:
    def __init__(self) -> None:
        self.counts = {}

    async def incr(self, key):
        self.counts[key] = self.counts.get(key, 0) + 1
        return self.counts[key]

    async def expire(self, key, seconds):
        return True


def test_distributed_rate_limiter_records_tikhub_bucket():
    redis = FakeRedis()
    limiter = TikHubRateLimiter(qps=8, redis_url="redis://unused", redis_client=redis)

    asyncio.run(limiter.acquire())

    assert len(redis.counts) == 1
    assert next(iter(redis.counts)).startswith("starx:tikhub:qps:")


class FakeLimiter:
    def __init__(self) -> None:
        self.acquire_count = 0
        self.closed = False

    async def acquire(self) -> None:
        self.acquire_count += 1

    async def aclose(self) -> None:
        self.closed = True


class FakeTransport(httpx.AsyncBaseTransport):
    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.closed = False

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return httpx.Response(200, request=request, json={"ok": True})

    async def aclose(self) -> None:
        self.closed = True


def test_tikhub_transport_applies_policy_without_wrapping_sdk_methods():
    limiter = FakeLimiter()
    inner = FakeTransport()
    transport = TikHubTransport(
        qps=8,
        redis_url="redis://unused",
        max_connections=16,
        rate_limiter=limiter,
        inner=inner,
    )
    request = httpx.Request("GET", "https://api.tikhub.test/health")

    response = asyncio.run(transport.handle_async_request(request))
    asyncio.run(transport.aclose())

    assert response.status_code == 200
    assert limiter.acquire_count == 1
    assert limiter.closed is True
    assert inner.requests == [request]
    assert inner.closed is True
