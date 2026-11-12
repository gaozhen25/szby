"""Tests for Rednote browser login helpers."""

from __future__ import annotations

import asyncio

from message_adapter.platforms.rednote.browser_login import (
    RednoteBrowserLoginResult,
    export_rednote_cookie_str,
    save_browser_login_result,
)
from message_adapter.platforms.rednote.credentials import load_rednote_cookie
from message_adapter.storage import CredentialStore


class _FakeContext:
    def __init__(self, cookies):
        self._cookies = cookies

    async def cookies(self):
        return self._cookies


def test_export_rednote_cookie_str_requires_web_session():
    ctx = _FakeContext([{"name": "a1", "value": "1", "domain": ".xiaohongshu.com"}])
    assert asyncio.run(export_rednote_cookie_str(ctx)) == ""


def test_export_rednote_cookie_str_keeps_platform_domains_only():
    ctx = _FakeContext(
        [
            {"name": "web_session", "value": "abc", "domain": ".xiaohongshu.com"},
            {"name": "a1", "value": "1", "domain": ".xiaohongshu.com"},
            {"name": "other", "value": "x", "domain": ".example.com"},
        ]
    )
    out = asyncio.run(export_rednote_cookie_str(ctx))
    assert "web_session=abc" in out
    assert "a1=1" in out
    assert "other=" not in out


def test_save_browser_login_result_writes_cookie_slot(tmp_path):
    store = CredentialStore(tmp_path / "credentials.sqlite3")
    try:
        save_browser_login_result(
            RednoteBrowserLoginResult(
                cookie="web_session=abc; a1=1",
                web_session="abc",
                user_id="100",
                device_id="fixed-device",
                nickname="小红",
                red_id="red1",
            ),
            store=store,
            browser_profile=str(tmp_path / "profiles" / "rednote" / "device"),
        )
        credential = load_rednote_cookie(store=store)
        assert credential.user_id == "100"
        assert credential.nickname == "小红"
        assert credential.device_id == "fixed-device"
        assert "web_session=abc" in credential.cookie
        assert store.get_bound_actor_id("rednote") == "100"
    finally:
        store.close()


def test_logged_in_requires_non_guest_user_id():
    from message_adapter.platforms.rednote.browser_login import _logged_in

    assert _logged_in({"user_id": "100", "guest": ""}) is True
    assert _logged_in({"user_id": "100", "guest": "1"}) is False
    assert _logged_in({"user_id": "", "guest": ""}) is False
    assert _logged_in({"user_id": "", "guest": "1"}) is False


def test_stable_device_id_is_fixed_for_the_same_uid():
    from message_adapter.platforms.rednote.im_ws import stable_device_id

    first = stable_device_id("664ccbee000000000700743b")
    second = stable_device_id("664ccbee000000000700743b")
    other = stable_device_id("6a4717b5000000000e03dc02")
    assert first == second
    assert first != other
    assert len(first) == 36
