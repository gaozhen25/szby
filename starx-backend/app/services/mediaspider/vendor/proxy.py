"""MediaSpider 三种代理提供器的内嵌实现。"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import urlparse

import httpx

from app.core.config import settings

from ..runtime import crawler_config


@dataclass
class IpInfoModel:
    ip: str
    port: int
    user: str = ""
    password: str = ""
    protocol: str = "http://"
    expired_time_ts: int = 0

    def is_expired(self, buffer_seconds=30):
        return bool(
            self.expired_time_ts
            and self.expired_time_ts <= time.time() + buffer_seconds
        )


class ProxyPool:
    def __init__(self, count, provider):
        self.count = count
        self.provider = provider
        self.proxy_list = []
        self.current_proxy = None

    async def load_proxies(self):
        self.proxy_list = await self.provider(self.count)

    async def get_proxy(self):
        if not self.proxy_list:
            await self.load_proxies()
        if not self.proxy_list:
            raise RuntimeError("代理服务未返回可用地址")
        self.current_proxy = self.proxy_list.pop(0)
        return self.current_proxy

    def is_current_proxy_expired(self):
        return self.current_proxy is None or self.current_proxy.is_expired()

    async def get_or_refresh_proxy(self):
        if self.is_current_proxy_expired():
            return await self.get_proxy()
        return self.current_proxy


async def _static_provider(count):
    parsed = urlparse(crawler_config.STATIC_PROXY_URL)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("静态代理地址无效")
    return [
        IpInfoModel(
            ip=parsed.hostname,
            port=parsed.port or (443 if parsed.scheme == "https" else 80),
            user=parsed.username or "",
            password=parsed.password or "",
            protocol=f"{parsed.scheme}://",
            expired_time_ts=int(time.time()) + 99_999_999,
        )
    ]


def _parse_kdl_proxy_line(
    value: str,
    *,
    username: str,
    password: str,
) -> IpInfoModel | None:
    """解析快代理返回的一行（官方为 ip:port；兼容 ttl / f_auth 扩展格式）。"""
    text = (value or "").strip()
    if not text:
        return None

    ttl = 3600
    ttl_match = re.fullmatch(r"(.+),(\d+)", text)
    if ttl_match:
        text = ttl_match.group(1)
        ttl = int(ttl_match.group(2))

    # 若接口误带 f_auth，仍解析，但鉴权以配置的用户名密码为准（官方写法）
    auth = re.fullmatch(r"([^:\s]+):(\d+):([^:]+):(.+)", text)
    if auth:
        return IpInfoModel(
            ip=auth.group(1),
            port=int(auth.group(2)),
            user=username or auth.group(3),
            password=password or auth.group(4),
            expired_time_ts=int(time.time()) + ttl - 5,
        )

    plain = re.fullmatch(r"([^:\s]+):(\d+)", text)
    if plain:
        return IpInfoModel(
            ip=plain.group(1),
            port=int(plain.group(2)),
            user=username,
            password=password,
            expired_time_ts=int(time.time()) + ttl - 5,
        )
    return None


async def fetch_kuaidaili_proxies(count: int) -> list[IpInfoModel]:
    """按快代理官方示例提取 IP，再用用户名密码拼 proxies。

    官方流程：
      1) GET getdps → 返回纯文本 ip:port
      2) proxies = http://user:pwd@ip:port/

    配置（Settings / .env，勿再读 os.environ）：
      KDL_SECERT_ID / KDL_SIGNATURE
      KDL_USER_NAME / KDL_USER_PWD   私密代理鉴权（必填）
      KDL_AREA                       可选
      KDL_GETDPS_URL                 可选，完整提取 URL
    """
    username = (settings.KDL_USER_NAME or "").strip()
    password = (settings.KDL_USER_PWD or "").strip()
    if not username or not password:
        raise RuntimeError("快代理用户名密码未配置（KDL_USER_NAME / KDL_USER_PWD）")

    override_url = (settings.KDL_GETDPS_URL or "").strip()
    area = (settings.KDL_AREA or "").strip()

    async with httpx.AsyncClient(follow_redirects=True) as client:
        if override_url:
            # 完整提取链接若未带 area，则附加 KDL_AREA（例如 苏州）
            if area and "area=" not in override_url.lower():
                from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

                parsed = urlparse(override_url)
                query = dict(parse_qsl(parsed.query, keep_blank_values=True))
                query["area"] = area
                override_url = urlunparse(
                    parsed._replace(query=urlencode(query))
                )
            response = await client.get(override_url, timeout=30)
        else:
            secret_id, signature = _kdl_api_credentials()
            params = {
                "secret_id": secret_id,
                "signature": signature,
                "num": max(1, count),
                "sep": 1,
            }
            if area:
                params["area"] = area
            response = await client.get(
                "https://dps.kdlapi.com/api/getdps/",
                params=params,
                timeout=30,
            )
        response.raise_for_status()

    raw = response.text.strip()
    if not raw:
        raise RuntimeError("快代理返回空响应")
    if raw.upper().startswith("ERROR"):
        raise RuntimeError(f"快代理服务返回错误: {raw}")

    values: list[str] = []
    if raw.startswith("{"):
        payload = response.json()
        if payload.get("code") != 0:
            raise RuntimeError(
                f"快代理服务返回错误: code={payload.get('code')} msg={payload.get('msg')}"
            )
        values = [
            str(item) for item in payload.get("data", {}).get("proxy_list", [])
        ]
    else:
        values = [line.strip() for line in re.split(r"[\r\n]+", raw) if line.strip()]

    result: list[IpInfoModel] = []
    for value in values:
        item = _parse_kdl_proxy_line(value, username=username, password=password)
        if item is not None:
            result.append(item)
        if len(result) >= max(1, count):
            break
    if not result:
        raise RuntimeError("快代理未返回可用 IP")
    return result


async def _wandou_provider(count):
    app_key = os.getenv("WANDOU_APP_KEY") or os.getenv("wandou_app_key", "")
    async with httpx.AsyncClient(follow_redirects=True) as client:
        response = await client.get(
            "https://api.wandouapp.com/",
            params={"app_key": app_key, "num": min(count, 100)},
            timeout=30,
        )
        response.raise_for_status()
    payload = response.json()
    if payload.get("code") != 200:
        raise RuntimeError("豌豆代理服务返回错误")
    result = []
    for item in payload.get("data", []):
        expire_time = item.get("expire_time")
        try:
            expires = int(datetime.fromisoformat(expire_time).timestamp())
        except (TypeError, ValueError):
            expires = 0
        result.append(
            IpInfoModel(
                ip=item.get("ip", ""),
                port=int(item.get("port", 0)),
                expired_time_ts=expires,
            )
        )
    return result


PROVIDERS = {
    "kuaidaili": fetch_kuaidaili_proxies,
    "wandouhttp": _wandou_provider,
    "static": _static_provider,
}


def _kdl_api_credentials() -> tuple[str, str]:
    secret_id = (settings.KDL_SECERT_ID or "").strip()
    signature = (settings.KDL_SIGNATURE or "").strip()
    if not secret_id or not signature:
        raise RuntimeError("快代理凭证未配置（KDL_SECERT_ID / KDL_SIGNATURE）")
    return secret_id, signature


async def fetch_kuaidaili_ip_balance() -> int:
    """查询私密代理订单剩余 IP 提取额度。

    GET https://dps.kdlapi.com/api/getipbalance
    文档: https://www.kuaidaili.com/doc/api/getipbalance/
    """
    secret_id, signature = _kdl_api_credentials()
    async with httpx.AsyncClient(follow_redirects=True) as client:
        response = await client.get(
            "https://dps.kdlapi.com/api/getipbalance",
            params={"secret_id": secret_id, "signature": signature},
            timeout=20,
        )
        response.raise_for_status()
    payload = response.json()
    if payload.get("code") != 0:
        raise RuntimeError(
            f"快代理余额查询失败: code={payload.get('code')} msg={payload.get('msg')}"
        )
    data = payload.get("data") or {}
    try:
        return int(data.get("balance"))
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"快代理余额字段异常: {data!r}") from exc


def fetch_kuaidaili_ip_balance_sync() -> int:
    """同步版 IP 余量查询（脚本 / 巡检用）。"""
    secret_id, signature = _kdl_api_credentials()
    with httpx.Client(follow_redirects=True, timeout=20) as client:
        response = client.get(
            "https://dps.kdlapi.com/api/getipbalance",
            params={"secret_id": secret_id, "signature": signature},
        )
        response.raise_for_status()
    payload = response.json()
    if payload.get("code") != 0:
        raise RuntimeError(
            f"快代理余额查询失败: code={payload.get('code')} msg={payload.get('msg')}"
        )
    data = payload.get("data") or {}
    try:
        return int(data.get("balance"))
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"快代理余额字段异常: {data!r}") from exc


async def create_ip_pool(ip_pool_count: int, enable_validate_ip: bool):
    """创建代理池并取出当前要用的 IP。

    快代理：进程内 3 分钟复用同一 IP，过期后再提取（避免短时并发重复扣额度）。
    """
    del enable_validate_ip
    provider_name = crawler_config.IP_PROXY_PROVIDER_NAME
    if provider_name == "kuaidaili":
        proxy = await get_sticky_kdl_proxy()
        pool = ProxyPool(1, PROVIDERS["kuaidaili"])
        pool.proxy_list = [proxy]
        pool.current_proxy = proxy
        return pool

    provider = PROVIDERS.get(provider_name)
    if provider is None:
        raise ValueError("未知代理提供器")
    pool = ProxyPool(max(1, int(ip_pool_count)), provider)
    await pool.load_proxies()
    await pool.get_proxy()
    return pool


# ---- 快代理短时复用（默认 180 秒）----

DEFAULT_KDL_REUSE_SECONDS = 180


def _kdl_reuse_seconds() -> int:
    try:
        return max(1, int(settings.KDL_PROXY_REUSE_SECONDS or DEFAULT_KDL_REUSE_SECONDS))
    except (TypeError, ValueError):
        return DEFAULT_KDL_REUSE_SECONDS


class _StickyKdlProxyCache:
    """进程内复用：未满复用窗口内多次请求共用同一 IP。"""

    def __init__(self) -> None:
        self._async_lock = asyncio.Lock()
        self._thread_lock = threading.Lock()
        self._proxy: IpInfoModel | None = None
        self._leased_at: float = 0.0
        self._last_was_new: bool = False

    def _reuse_seconds(self) -> int:
        return _kdl_reuse_seconds()

    def _remaining(self) -> float:
        return self._reuse_seconds() - (time.time() - self._leased_at)

    def _is_fresh(self) -> bool:
        return self._proxy is not None and self._remaining() > 0

    def _store(self, proxy: IpInfoModel) -> IpInfoModel:
        reuse = self._reuse_seconds()
        # 本地复用窗口覆盖供应商默认 TTL，便于 is_expired 判断
        proxy.expired_time_ts = int(time.time()) + reuse
        self._proxy = proxy
        self._leased_at = time.time()
        self._last_was_new = True
        return proxy

    def status(self) -> dict | None:
        if self._proxy is None:
            return None
        return {
            "ip": self._proxy.ip,
            "port": self._proxy.port,
            "remaining_sec": max(0, int(self._remaining())),
            "is_new": self._last_was_new,
            "reuse_seconds": self._reuse_seconds(),
        }

    async def get(self) -> tuple[IpInfoModel, bool]:
        """返回 (proxy, is_new)。"""
        async with self._async_lock:
            if self._is_fresh():
                assert self._proxy is not None
                self._last_was_new = False
                return self._proxy, False
            fresh = await fetch_kuaidaili_proxies(1)
            if not fresh:
                raise RuntimeError("快代理未返回可用 IP")
            return self._store(fresh[0]), True

    def get_sync(self) -> tuple[IpInfoModel, bool]:
        with self._thread_lock:
            if self._is_fresh():
                assert self._proxy is not None
                self._last_was_new = False
                return self._proxy, False
            try:
                fresh = asyncio.run(fetch_kuaidaili_proxies(1))
            except RuntimeError:
                loop = asyncio.new_event_loop()
                try:
                    fresh = loop.run_until_complete(fetch_kuaidaili_proxies(1))
                finally:
                    loop.close()
            if not fresh:
                raise RuntimeError("快代理未返回可用 IP")
            return self._store(fresh[0]), True


_STICKY_KDL = _StickyKdlProxyCache()


def sticky_kdl_status() -> dict | None:
    return _STICKY_KDL.status()


async def get_sticky_kdl_proxy() -> IpInfoModel:
    proxy, is_new = await _STICKY_KDL.get()
    remaining = max(0, int(_STICKY_KDL._remaining()))
    if is_new:
        logging.getLogger(__name__).info(
            "kdl leased new proxy %s:%s reuse=%ss",
            proxy.ip,
            proxy.port,
            _kdl_reuse_seconds(),
        )
    else:
        logging.getLogger(__name__).info(
            "kdl reuse proxy %s:%s remaining=%ss",
            proxy.ip,
            proxy.port,
            remaining,
        )
    return proxy


def get_sticky_kdl_proxy_sync() -> IpInfoModel:
    proxy, is_new = _STICKY_KDL.get_sync()
    remaining = max(0, int(_STICKY_KDL._remaining()))
    logger = logging.getLogger(__name__)
    if is_new:
        logger.info(
            "kdl leased new proxy %s:%s reuse=%ss",
            proxy.ip,
            proxy.port,
            _kdl_reuse_seconds(),
        )
    else:
        logger.info(
            "kdl reuse proxy %s:%s remaining=%ss",
            proxy.ip,
            proxy.port,
            remaining,
        )
    return proxy


async def get_sticky_requests_proxies() -> dict[str, str]:
    from .tools import format_proxy_info

    proxy = await get_sticky_kdl_proxy()
    _, url = format_proxy_info(proxy)
    if not url:
        raise RuntimeError("代理地址格式无效")
    return {"http": url, "https": url}


def get_sticky_requests_proxies_sync() -> dict[str, str]:
    from .tools import format_proxy_info

    proxy = get_sticky_kdl_proxy_sync()
    _, url = format_proxy_info(proxy)
    if not url:
        raise RuntimeError("代理地址格式无效")
    return {"http": url, "https": url}


class ProxyRefreshMixin:
    _proxy_ip_pool = None

    def init_proxy_pool(self, proxy_ip_pool):
        self._proxy_ip_pool = proxy_ip_pool

    async def _refresh_proxy_if_expired(self):
        if self._proxy_ip_pool and self._proxy_ip_pool.is_current_proxy_expired():
            proxy = await self._proxy_ip_pool.get_or_refresh_proxy()
            auth = (
                f"{proxy.user}:{proxy.password}@"
                if proxy.user and proxy.password
                else ""
            )
            self.proxy = f"http://{auth}{proxy.ip}:{proxy.port}"
