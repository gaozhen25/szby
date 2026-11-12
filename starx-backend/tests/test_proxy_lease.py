import asyncio
import time

from app.services.mediaspider.vendor import proxy_lease
from app.services.mediaspider.vendor.proxy import IpInfoModel
from app.services.mediaspider.vendor.proxy_lease import FixedSizeProxyPool, LeasedProxyPool


def _fake_proxies(n: int) -> list[IpInfoModel]:
    return [
        IpInfoModel(
            ip=f"1.1.1.{i}",
            port=8080,
            user="u",
            password="p",
            expired_time_ts=int(time.time()) + 3600,
        )
        for i in range(1, n + 1)
    ]


def test_fixed_size_pool_acquire_is_exclusive(monkeypatch):
    async def fake_fetch(n: int):
        return _fake_proxies(n)

    monkeypatch.setattr(proxy_lease, "fetch_proxies", fake_fetch)

    async def run():
        pool = FixedSizeProxyPool(size=3)
        first = await pool.acquire()
        second = await pool.acquire()
        third = await pool.acquire()

        assert {f"{p.ip}:{p.port}" for p in (first, second, third)} == {
            "1.1.1.1:8080",
            "1.1.1.2:8080",
            "1.1.1.3:8080",
        }
        assert pool.free_count == 0
        assert pool.leased_count == 3

        try:
            await pool.acquire(timeout_sec=0.05)
            raise AssertionError("expected TimeoutError")
        except TimeoutError:
            pass

        await pool.release(second)
        reused = await pool.acquire(timeout_sec=1)
        assert f"{reused.ip}:{reused.port}" == f"{second.ip}:{second.port}"

    asyncio.run(run())


def test_leased_proxy_pool_release_returns_ip(monkeypatch):
    async def fake_fetch(n: int):
        return [
            IpInfoModel(
                ip=host,
                port=3128,
                user="u",
                password="p",
                expired_time_ts=int(time.time()) + 3600,
            )
            for host in ("8.8.8.8", "8.8.4.4", "1.0.0.1")
        ]

    monkeypatch.setattr(proxy_lease, "fetch_proxies", fake_fetch)

    async def run():
        shared = FixedSizeProxyPool(size=3)
        a = LeasedProxyPool(shared)
        b = LeasedProxyPool(shared)

        proxy_a = await a.get_proxy()
        proxy_b = await b.get_proxy()
        assert isinstance(proxy_a, IpInfoModel)
        assert f"{proxy_a.ip}:{proxy_a.port}" != f"{proxy_b.ip}:{proxy_b.port}"
        assert shared.leased_count == 2
        assert shared.free_count == 1

        await a.release()
        assert shared.leased_count == 1
        assert shared.free_count == 2

        c = LeasedProxyPool(shared)
        proxy_c = await c.get_proxy()
        assert f"{proxy_c.ip}:{proxy_c.port}" != f"{proxy_b.ip}:{proxy_b.port}"
        assert shared.leased_count == 2

    asyncio.run(run())
