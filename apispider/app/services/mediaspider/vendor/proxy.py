"""MediaSpider 三种代理提供器的内嵌实现。"""

from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import urlparse

import httpx

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


async def _kuaidaili_provider(count):
    params = {
        "secret_id": os.getenv("KDL_SECERT_ID") or os.getenv("kdl_secret_id", ""),
        "signature": os.getenv("KDL_SIGNATURE") or os.getenv("kdl_signature", ""),
        "num": count,
        "pt": 1,
        "format": "json",
        "sep": 1,
        "f_et": 1,
    }
    username = os.getenv("KDL_USER_NAME") or os.getenv("kdl_user_name", "")
    password = os.getenv("KDL_USER_PWD") or os.getenv("kdl_user_pwd", "")
    async with httpx.AsyncClient(follow_redirects=True) as client:
        response = await client.get(
            "https://dps.kdlapi.com/api/getdps/", params=params, timeout=30
        )
        response.raise_for_status()
    payload = response.json()
    if payload.get("code") != 0:
        raise RuntimeError("快代理服务返回错误")
    result = []
    for value in payload.get("data", {}).get("proxy_list", []):
        match = re.fullmatch(r"([^:]+):(\d+),(\d+)", value)
        if match:
            result.append(
                IpInfoModel(
                    ip=match.group(1),
                    port=int(match.group(2)),
                    user=username,
                    password=password,
                    expired_time_ts=int(time.time()) + int(match.group(3)) - 5,
                )
            )
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
    "kuaidaili": _kuaidaili_provider,
    "wandouhttp": _wandou_provider,
    "static": _static_provider,
}


async def create_ip_pool(ip_pool_count: int, enable_validate_ip: bool):
    provider = PROVIDERS.get(crawler_config.IP_PROXY_PROVIDER_NAME)
    if provider is None:
        raise ValueError("未知代理提供器")
    pool = ProxyPool(ip_pool_count, provider)
    await pool.load_proxies()
    return pool


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
