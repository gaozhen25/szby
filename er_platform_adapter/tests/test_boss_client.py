from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx

from message_adapter.platforms.boss.auth import Credential
from message_adapter.platforms.boss.client import BossClient
from message_adapter.platforms.boss.stoken import generate_stoken


def test_friend_details_are_batched_without_losing_rows(monkeypatch):
    client = BossClient()
    calls: list[str] = []

    def fake_post(url, *, data, action):
        calls.append(data["friendIds"])
        return {"friendList": [{"friendId": value} for value in data["friendIds"].split(",")]}

    monkeypatch.setattr(client, "_post", fake_post)

    result = client.get_boss_friend_details([1, 2, 3], batch_size=2)

    assert calls == ["1,2", "3"]
    assert result == {"friendList": [{"friendId": "1"}, {"friendId": "2"}, {"friendId": "3"}]}


def test_ws_auth_uses_cookie_wt2_when_response_omits_it(monkeypatch):
    client = BossClient()
    client._http = httpx.Client(cookies={"wt2": "cookie-secret"})

    def fake_get(url, *, params=None, action):
        if action == "用户信息":
            return {"token": "page-token", "userId": 1001}
        return {}

    monkeypatch.setattr(client, "_get", fake_get)
    try:
        token, wt2, user = client.get_ws_auth()
    finally:
        client._http.close()

    assert (token, wt2) == ("page-token", "cookie-secret")
    assert user["userId"] == 1001


def test_send_boss_message_uses_recruiter_mqtt_identity(monkeypatch):
    client = BossClient()
    monkeypatch.setattr(
        client,
        "get_ws_auth",
        lambda: ("page-token", "wt2", {"userId": 1001, "encryptUserId": "actor-enc"}),
    )
    monkeypatch.setattr(client, "session_cookies", lambda: {"wt2": "wt2"})
    mqtt = MagicMock()
    context = MagicMock()
    context.__enter__.return_value = mqtt

    with patch("message_adapter.platforms.boss.mqtt.BossMQTTChat", return_value=context) as mqtt_class:
        result = client.send_boss_message(2002, "audience-enc", "你好")

    assert result == {"ok": True, "toUid": 2002, "identity": 1}
    assert mqtt_class.call_args.kwargs["identity"] == 1
    mqtt.send.assert_called_once_with(
        from_uid=1001,
        from_encrypt_uid="actor-enc",
        to_uid=2002,
        to_encrypt_uid="audience-enc",
        text="你好",
    )


def test_client_reuses_saved_stoken_without_generating(monkeypatch):
    credential = Credential({"wt2": "session", "zp_at": "session", "__zp_stoken__": "kept"})

    def fail(cookies, *, verify=True):
        raise AssertionError(cookies)

    monkeypatch.setattr("message_adapter.platforms.boss.stoken.generate_stoken", fail)
    with BossClient(credential, request_delay=0) as client:
        assert client.client.cookies.get("__zp_stoken__") == "kept"


def test_client_generates_and_saves_missing_stoken(monkeypatch):
    credential = Credential({"wt2": "session", "zp_at": "session"})
    saved: dict[str, str] = {}

    def fake_generate(cookies, *, verify=True):
        assert cookies["wt2"] == "session"
        assert verify is True
        return "fresh-token"

    def fake_save(value, **kwargs):
        saved.update(value.cookies)

    monkeypatch.setattr("message_adapter.platforms.boss.stoken.generate_stoken", fake_generate)
    monkeypatch.setattr("message_adapter.platforms.boss.auth.save_credential", fake_save)
    with BossClient(credential, request_delay=0) as client:
        assert client.client.cookies.get("__zp_stoken__") == "fresh-token"

    assert saved["__zp_stoken__"] == "fresh-token"
    assert credential.cookies["__zp_stoken__"] == "fresh-token"


def test_risk_code_refreshes_stoken_once_and_retries(monkeypatch):
    credential = Credential({"wt2": "session", "zp_at": "session", "__zp_stoken__": "old"})
    client = BossClient(credential, request_delay=0)
    client._http = httpx.Client(cookies={"wt2": "session", "__zp_stoken__": "old"})
    calls = {"n": 0}

    def fake_request(method, url, **kwargs):
        calls["n"] += 1
        code = 37 if calls["n"] == 1 else 0
        return httpx.Response(
            200,
            json={"code": code, "message": "环境异常", "zpData": {"ok": True}},
            request=httpx.Request(method, "https://www.zhipin.com" + url),
        )

    def fake_generate(cookies, *, verify=True):
        return "refreshed"

    monkeypatch.setattr(client._http, "request", fake_request)
    monkeypatch.setattr("message_adapter.platforms.boss.stoken.generate_stoken", fake_generate)
    monkeypatch.setattr("message_adapter.platforms.boss.auth.save_credential", lambda *args, **kwargs: None)
    try:
        assert client._post("/wapi/zpchat/exchange/request", data={"type": 2}, action="发起交换") == {"ok": True}
    finally:
        client._http.close()

    assert calls["n"] == 2
    assert client.client.cookies.get("__zp_stoken__") == "refreshed"


def test_generate_stoken_skips_browser_without_session(monkeypatch):
    def fail(*args, **kwargs):
        raise AssertionError("browser should not start")

    monkeypatch.setattr("playwright.sync_api.sync_playwright", fail)
    assert generate_stoken({}) == ""
    assert generate_stoken(None) == ""
