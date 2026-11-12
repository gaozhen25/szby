"""固定大小的进程内代理租约池：一个爬虫占用一个 IP，互不冲突。

池内 IP 来自快代理（kuaidaili），默认保持 3 个可用地址。
"""

from __future__ import annotations

import asyncio
import time

from .proxy import IpInfoModel

DEFAULT_POOL_SIZE = 3
DEFAULT_ACQUIRE_TIMEOUT_SEC = 120.0


def _proxy_key(proxy: IpInfoModel) -> str:
    return f"{proxy.ip}:{proxy.port}"


async def fetch_proxies(count: int) -> list[IpInfoModel]:
    """从快代理提取 count 个 IP（可在测试中 monkeypatch）。"""
    from .proxy import fetch_kuaidaili_proxies

    return await fetch_kuaidaili_proxies(count)


class FixedSizeProxyPool:
    """保持 size 个可用 IP；acquire 独占，release 归还。"""

    def __init__(self, size: int = DEFAULT_POOL_SIZE):
        if size < 1:
            raise ValueError("代理池大小至少为 1")
        self.size = size
        self._lock = asyncio.Lock()
        self._condition = asyncio.Condition(self._lock)
        self._free: list[IpInfoModel] = []
        self._leased: dict[str, IpInfoModel] = {}

    @property
    def free_count(self) -> int:
        return len(self._free)

    @property
    def leased_count(self) -> int:
        return len(self._leased)

    async def ensure_ready(self) -> None:
        async with self._lock:
            await self._refill_locked()

    async def acquire(
        self,
        *,
        timeout_sec: float = DEFAULT_ACQUIRE_TIMEOUT_SEC,
    ) -> IpInfoModel:
        deadline = time.monotonic() + timeout_sec
        async with self._condition:
            while True:
                await self._refill_locked()
                if self._free:
                    proxy = self._free.pop(0)
                    self._leased[_proxy_key(proxy)] = proxy
                    return proxy
                if not self._leased:
                    raise RuntimeError("代理池无法获取可用 IP")
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("代理池暂无空闲 IP")
                try:
                    await asyncio.wait_for(self._condition.wait(), timeout=remaining)
                except TimeoutError as exc:
                    raise TimeoutError("代理池暂无空闲 IP") from exc

    async def release(self, proxy: IpInfoModel | None, *, discard: bool = False) -> None:
        if proxy is None:
            return
        key = _proxy_key(proxy)
        async with self._condition:
            leased = self._leased.pop(key, None)
            if leased is None:
                return
            if not discard and not leased.is_expired():
                self._free.append(leased)
            await self._refill_locked()
            self._condition.notify_all()

    async def _refill_locked(self) -> None:
        need = self.size - (len(self._free) + len(self._leased))
        if need <= 0:
            return
        owned = {_proxy_key(item) for item in self._free}
        owned.update(self._leased)
        fresh = await fetch_proxies(max(need * 2, need))
        for item in fresh:
            if need <= 0:
                break
            key = _proxy_key(item)
            if key in owned:
                continue
            self._free.append(item)
            owned.add(key)
            need -= 1


_PROCESS_POOL: FixedSizeProxyPool | None = None
_PROCESS_POOL_LOCK = asyncio.Lock()


async def get_shared_lease_pool(size: int = DEFAULT_POOL_SIZE) -> FixedSizeProxyPool:
    global _PROCESS_POOL
    async with _PROCESS_POOL_LOCK:
        if _PROCESS_POOL is None or _PROCESS_POOL.size != size:
            _PROCESS_POOL = FixedSizeProxyPool(size=size)
            await _PROCESS_POOL.ensure_ready()
        return _PROCESS_POOL


class LeasedProxyPool:
    """兼容现有 ProxyPool 接口：get_proxy / release。"""

    def __init__(self, lease_pool: FixedSizeProxyPool):
        self._lease_pool = lease_pool
        self.current_proxy: IpInfoModel | None = None
        self.proxy_list: list[IpInfoModel] = []

    async def load_proxies(self) -> None:
        await self._lease_pool.ensure_ready()

    async def get_proxy(self) -> IpInfoModel:
        if self.current_proxy is not None:
            return self.current_proxy
        self.current_proxy = await self._lease_pool.acquire()
        self.proxy_list = [self.current_proxy]
        return self.current_proxy

    def is_current_proxy_expired(self) -> bool:
        return self.current_proxy is None or self.current_proxy.is_expired()

    async def get_or_refresh_proxy(self) -> IpInfoModel:
        if self.is_current_proxy_expired():
            old = self.current_proxy
            self.current_proxy = None
            if old is not None:
                await self._lease_pool.release(old, discard=True)
            return await self.get_proxy()
        return self.current_proxy

    async def release(self, *, discard: bool = False) -> None:
        proxy = self.current_proxy
        self.current_proxy = None
        self.proxy_list = []
        await self._lease_pool.release(proxy, discard=discard)
