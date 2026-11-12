from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

from message_adapter.browser_profiles import BrowserProfile
from message_adapter.core.models import Audience, Conversation
from message_adapter.platforms.boss.adapter import BossPlatformAdapter
from message_adapter.platforms.boss.auth import Credential
from message_adapter.platforms.boss.client import BossClient
from message_adapter.platforms.boss.constants import (
    BOSS_EXCHANGE_ACCEPT_URL,
    BOSS_EXCHANGE_CONTENT_URL,
    BOSS_EXCHANGE_REQUEST_URL,
)
from message_adapter.platforms.boss.exchange import (
    ExchangeAcceptType,
    ExchangeType,
    find_pending_exchange_request,
)


def _conversation() -> Conversation:
    return Conversation(
        platform="boss",
        platform_actor_id="1001",
        audience=Audience("2002", "候选人甲"),
        platform_conversation_id="77",
        platform_data={"friend_id": "77", "uid": "2002"},
    )


def test_client_builds_native_wechat_exchange_request(monkeypatch):
    client = BossClient()
    post = MagicMock(return_value={"mid": 9001})
    monkeypatch.setattr(client, "_post", post)

    result = client.request_exchange(
        security_id="fresh-security",
        unique_id="2002-7",
        exchange_type=ExchangeType.WECHAT,
        name="候选人甲",
    )

    assert result == {"mid": 9001}
    post.assert_called_once_with(
        BOSS_EXCHANGE_REQUEST_URL,
        data={
            "type": 2,
            "securityId": "fresh-security",
            "uniqueId": "2002-7",
            "name": "候选人甲",
        },
        action="发起交换",
    )


def test_client_builds_native_wechat_exchange_accept(monkeypatch):
    client = BossClient()
    post = MagicMock(return_value={"accepted": True})
    monkeypatch.setattr(client, "_post", post)

    result = client.accept_exchange(
        security_id="fresh-security",
        platform_message_id=9001,
        exchange_type=ExchangeAcceptType.WECHAT,
    )

    assert result == {"accepted": True}
    post.assert_called_once_with(
        BOSS_EXCHANGE_ACCEPT_URL,
        data={"securityId": "fresh-security", "mid": 9001, "type": 2},
        action="同意交换",
    )


def test_client_queries_exchange_content_by_audience_uid(monkeypatch):
    client = BossClient()
    post = MagicMock(return_value={"wechat": "masked"})
    monkeypatch.setattr(client, "_post", post)

    assert client.get_exchange_content(2002) == {"wechat": "masked"}
    post.assert_called_once_with(
        BOSS_EXCHANGE_CONTENT_URL,
        data={"uid": 2002},
        action="查看交换结果",
    )


def test_pending_parser_selects_newest_incoming_wechat_request():
    pending = find_pending_exchange_request(
        [
            {"mid": 10, "time": 100, "from": {"uid": 2002}, "pushText": "请求与您交换微信"},
            {"mid": 11, "time": 200, "from": {"uid": 2002}, "pushText": "请求与您交换手机号"},
            {"mid": 12, "time": 300, "from": {"uid": 1001}, "pushText": "请求与您交换微信"},
            {"mid": 13, "time": 400, "from": {"uid": 2002}, "pushText": "请求与您交换微信"},
        ],
        audience_id=2002,
        exchange_type=ExchangeAcceptType.WECHAT,
    )

    assert pending is not None
    assert pending.platform_message_id == "13"
    assert pending.exchange_type is ExchangeAcceptType.WECHAT


def test_adapter_refreshes_security_id_before_requesting_wechat_exchange():
    adapter = BossPlatformAdapter()
    adapter._credential = Credential({"wt2": "redacted", "zp_at": "redacted"})
    client = MagicMock()
    client.get_boss_friend_details.return_value = {
        "friendList": [
            {
                "friendId": 77,
                "uid": 2002,
                "friendSource": 7,
                "securityId": "fresh-security",
                "name": "候选人甲",
            }
        ]
    }
    client.request_exchange.return_value = {"mid": 9001}
    context = MagicMock()
    context.__enter__.return_value = client

    with patch("message_adapter.platforms.boss.adapter.BossClient", return_value=context):
        result = asyncio.run(adapter.request_wechat_exchange(_conversation()))

    client.get_boss_friend_details.assert_called_once_with([77])
    client.request_exchange.assert_called_once_with(
        security_id="fresh-security",
        unique_id="2002-7",
        exchange_type=ExchangeType.WECHAT,
        name="候选人甲",
    )
    assert result.action == "request"
    assert result.exchange_type == "wechat"
    assert result.platform_message_id == "9001"
    assert adapter.capabilities.wechat_exchange is True


def test_adapter_requests_phone_exchange_with_native_type():
    adapter = BossPlatformAdapter()
    adapter._credential = Credential({"wt2": "redacted", "zp_at": "redacted"})
    client = MagicMock()
    client.get_boss_friend_details.return_value = {
        "friendList": [
            {
                "friendId": 77,
                "uid": 2002,
                "friendSource": 7,
                "securityId": "fresh-security",
                "name": "候选人甲",
            }
        ]
    }
    client.request_exchange.return_value = {"mid": 9004}
    context = MagicMock()
    context.__enter__.return_value = client

    with patch("message_adapter.platforms.boss.adapter.BossClient", return_value=context):
        result = asyncio.run(adapter.request_phone_exchange(_conversation()))

    client.request_exchange.assert_called_once_with(
        security_id="fresh-security",
        unique_id="2002-7",
        exchange_type=ExchangeType.PHONE,
        name="候选人甲",
    )
    assert result.action == "request"
    assert result.exchange_type == "phone"
    assert result.platform_message_id == "9004"


def test_adapter_can_discover_and_accept_pending_wechat_exchange():
    adapter = BossPlatformAdapter()
    adapter._credential = Credential({"wt2": "redacted", "zp_at": "redacted"})
    client = MagicMock()
    client.get_boss_friend_details.return_value = {
        "friendList": [
            {
                "friendId": 77,
                "uid": 2002,
                "friendSource": 7,
                "securityId": "fresh-security",
                "name": "候选人甲",
            }
        ]
    }
    client.get_boss_chat_history.return_value = {
        "messages": [
            {
                "mid": 9002,
                "time": 1789000000,
                "from": {"uid": 2002},
                "pushText": "候选人请求与您交换微信",
            }
        ]
    }
    client.accept_exchange.return_value = {"accepted": True}
    context = MagicMock()
    context.__enter__.return_value = client

    with patch("message_adapter.platforms.boss.adapter.BossClient", return_value=context):
        result = asyncio.run(adapter.accept_wechat_exchange(_conversation(), "9002"))

    client.get_boss_chat_history.assert_not_called()
    client.accept_exchange.assert_called_once_with(
        security_id="fresh-security",
        platform_message_id=9002,
        exchange_type=ExchangeAcceptType.WECHAT,
    )
    assert result.action == "accept"
    assert result.platform_message_id == "9002"


def test_exchange_uses_http_session_even_when_a_browser_profile_is_bound(tmp_path):
    profile = BrowserProfile(tmp_path / "profiles", "boss")
    adapter = BossPlatformAdapter(browser_profile=profile)
    adapter._credential = Credential(
        {"wt2": "redacted", "zp_at": "redacted"},
        browser_profile=str(profile.path),
    )
    client = MagicMock()
    client.get_boss_friend_details.return_value = {
        "friendList": [
            {
                "friendId": 77,
                "uid": 2002,
                "friendSource": 7,
                "securityId": "fresh-security",
                "name": "候选人甲",
            }
        ]
    }
    client.request_exchange.return_value = {"mid": 9003}
    context = MagicMock()
    context.__enter__.return_value = client

    with patch("message_adapter.platforms.boss.adapter.BossClient", return_value=context):
        result = asyncio.run(adapter.request_wechat_exchange(_conversation()))

    client.get_boss_friend_details.assert_called_once_with([77])
    client.request_exchange.assert_called_once_with(
        security_id="fresh-security",
        unique_id="2002-7",
        exchange_type=ExchangeType.WECHAT,
        name="候选人甲",
    )
    assert result.platform_message_id == "9003"
