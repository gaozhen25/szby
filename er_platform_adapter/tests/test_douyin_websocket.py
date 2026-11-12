"""Tests for Douyin frontier-im WebSocket helpers."""

from __future__ import annotations

import hashlib
from types import SimpleNamespace

from message_adapter.platforms.douyin.websocket import (
    build_ws_url,
    compute_access_key,
    decode_push_frame,
    resolve_device_id,
)


def test_compute_access_key_matches_protocol_formula():
    device_id = "75604715923"
    expected = hashlib.md5(f"9e1bd35ec9db7b8d846de66ed140b1ad9{device_id}f8a69f1719916z".encode()).hexdigest()
    assert compute_access_key(device_id) == expected


def test_build_ws_url_contains_device_and_access_key():
    url = build_ws_url("12345678901", token="sess-token")
    assert "frontier-im.douyin.com/ws/v2" in url
    assert "device_id=12345678901" in url
    assert "token=sess-token" in url
    assert f"access_key={compute_access_key('12345678901')}" in url


def test_decode_push_frame_empty_returns_empty():
    assert decode_push_frame(b"") == []
    assert decode_push_frame(b"\x08\x01") == []


def test_resolve_device_id_uses_uid_only():
    auth = SimpleNamespace(
        cookie={"tt_webid": "1111111111111111111"},
        uid="75604715923",
        client=SimpleNamespace(webid="9999999999999999999"),
    )
    assert resolve_device_id(auth) == "75604715923"


def test_resolve_device_id_falls_back_to_cookie_when_uid_missing():
    auth = SimpleNamespace(
        cookie={"tt_webid": "1111111111111111111"},
        uid="",
        client=SimpleNamespace(webid="9999999999999999999"),
    )
    assert resolve_device_id(auth) == "1111111111111111111"
