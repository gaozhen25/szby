from __future__ import annotations

import asyncio
import json

import httpx

from message_adapter.gateway.account_alert import (
    ACCOUNT_ALERT_SOURCE,
    AccountAlertClient,
    alert_transitions,
    online_alert_accounts,
)


def test_online_accounts_skip_host_platforms_and_offline_slots():
    accounts = online_alert_accounts(
        {
            "boss": {"online": True, "platform_actor_id": "1001"},
            "douyin": {"online": False, "platform_actor_id": "dy-1"},
            "rednote": {"online": True, "platform_actor_id": ""},
            "wechat": {"online": True, "platform_actor_id": "wxid"},
        }
    )
    assert accounts == [{"platform": "boss", "platform_id": "1001"}]


def test_alert_transitions_heartbeat_online_and_drop_offline():
    reported: dict[tuple[str, str], float] = {}
    first = alert_transitions(reported, (("boss", "1001"),), now=100)
    assert first == [("boss", "1001", "online")]
    reported[("boss", "1001")] = 100
    assert alert_transitions(reported, (("boss", "1001"),), now=139) == []
    assert alert_transitions(reported, (("boss", "1001"),), now=140) == [("boss", "1001", "online")]
    assert alert_transitions(reported, (), now=141) == [("boss", "1001", "offline")]


def test_alert_client_posts_adapter_source_and_alert_type():
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["secret"] = request.headers.get("X-Internal-Secret")
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"ok": True})

    client = AccountAlertClient(
        "http://alert.test/api/v1/lightreply/account_monitor/internal/alert",
        "test-secret",
        transport=httpx.MockTransport(handler),
    )
    asyncio.run(client.send("rednote", "note-1", "offline"))
    body = seen["body"]
    assert isinstance(body, dict)
    assert seen["secret"] == "test-secret"
    assert body["platform"] == "rednote"
    assert body["platform_id"] == "note-1"
    assert body["source_service"] == ACCOUNT_ALERT_SOURCE == "adapter"
    assert body["alert_type"] == "offline"
    assert str(body["event_id"]).startswith("alert-")
