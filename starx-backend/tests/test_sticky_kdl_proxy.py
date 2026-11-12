import asyncio
import time

from app.services.mediaspider.vendor import proxy as proxy_mod
from app.services.mediaspider.vendor.proxy import (
    IpInfoModel,
    get_sticky_kdl_proxy,
    sticky_kdl_status,
)


def test_sticky_proxy_reuses_within_window(monkeypatch):
    calls = {"n": 0}

    async def fake_fetch(count):
        calls["n"] += 1
        return [
            IpInfoModel(
                ip=f"1.2.3.{calls['n']}",
                port=8000 + calls["n"],
                user="u",
                password="p",
            )
        ]

    monkeypatch.setattr(proxy_mod, "fetch_kuaidaili_proxies", fake_fetch)
    monkeypatch.setattr(proxy_mod.settings, "KDL_PROXY_REUSE_SECONDS", 180)
    proxy_mod._STICKY_KDL = proxy_mod._StickyKdlProxyCache()

    async def run():
        a = await get_sticky_kdl_proxy()
        b = await get_sticky_kdl_proxy()
        assert a.ip == b.ip == "1.2.3.1"
        assert calls["n"] == 1

        proxy_mod._STICKY_KDL._leased_at = time.time() - 999
        c = await get_sticky_kdl_proxy()
        assert c.ip == "1.2.3.2"
        assert calls["n"] == 2
        assert sticky_kdl_status()["is_new"] is True

    asyncio.run(run())
