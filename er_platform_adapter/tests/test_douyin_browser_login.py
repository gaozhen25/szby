"""Tests for Douyin browser login helpers."""

from __future__ import annotations

import asyncio
import json

from message_adapter.platforms.douyin.grab_ticket import export_douyin_cookie_str, parse_web_protect


class _FakeContext:
    def __init__(self, cookies):
        self._cookies = cookies

    async def cookies(self):
        return self._cookies


def test_export_douyin_cookie_str_requires_sessionid():
    ctx = _FakeContext([{"name": "ttwid", "value": "1", "domain": ".douyin.com"}])
    assert asyncio.run(export_douyin_cookie_str(ctx)) == ""


def test_export_douyin_cookie_str_ok():
    ctx = _FakeContext(
        [
            {"name": "sessionid", "value": "abc", "domain": ".douyin.com"},
            {"name": "ttwid", "value": "1", "domain": ".douyin.com"},
            {"name": "other", "value": "x", "domain": ".example.com"},
        ]
    )
    out = asyncio.run(export_douyin_cookie_str(ctx))
    assert "sessionid=abc" in out
    assert "ttwid=1" in out
    assert "other=" not in out


def test_parse_web_protect_roundtrip():
    web = json.dumps({"data": json.dumps({"ticket": "t1", "ts_sign": "s1", "client_cert": "c1"})})
    keys = json.dumps({"data": json.dumps({"ec_privateKey": "p1"})})
    parsed = parse_web_protect(web, keys)
    assert parsed["DY_TICKET"] == "t1"
    assert parsed["DY_PRIVATE_KEY"] == "p1"
