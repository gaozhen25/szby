from __future__ import annotations

import asyncio
import json
import logging
import uuid
from pathlib import Path

from message_adapter.platforms.douyin.protocol import ImAuth
from message_adapter.core.models import Actor, Audience, Conversation
from message_adapter.platforms.boss import BossPlatformAdapter
from message_adapter.platforms.douyin import DouyinPlatformAdapter
from message_adapter.storage import CredentialStore


FIXTURES = Path(__file__).parent / "fixtures" / "adapter"


def load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_boss_receive_does_not_scan_history():
    assert BossPlatformAdapter.capabilities.automatic_catch_up is False


def test_boss_live_message_does_not_block_on_friend_lookup():
    from unittest.mock import patch

    adapter = BossPlatformAdapter()
    adapter._actor = Actor("boss", "1001", "招聘者")
    payload = load_fixture("boss_live_text.json")
    payload["uid"] = 503956637

    with patch("message_adapter.platforms.boss.adapter.BossClient") as client:
        message = adapter._message_from_live(payload)

    assert message is not None
    assert message.conversation.audience.platform_audience_id == "503956637"
    client.assert_not_called()


def test_boss_send_uses_fresh_encrypt_id_when_saved_conversation_lacks_one():
    from unittest.mock import MagicMock, patch

    from message_adapter.platforms.boss.auth import Credential

    adapter = BossPlatformAdapter()
    adapter._actor = Actor("boss", "1001", "招聘者")
    adapter._credential = Credential({"wt2": "redacted", "zp_at": "redacted"})
    adapter._user_info = {"encryptUserId": "self-enc", "userId": 1001}
    chat = MagicMock()
    chat.dropped = False
    adapter._live_chat = chat
    client = MagicMock()
    client.get_boss_friend_details.return_value = {
        "friendList": [{"uid": 503956637, "encryptUid": "encrypt-from-detail", "name": "覃先生"}]
    }
    client.send_boss_message.return_value = {"ok": True, "mid": "9001"}
    context = MagicMock()
    context.__enter__.return_value = client
    conversation = Conversation(
        "boss",
        "1001",
        Audience("503956637", "覃先生"),
        "503956637",
        {"uid": "503956637", "friend_id": "503956637", "encrypt_geek_id": ""},
    )

    with patch("message_adapter.platforms.boss.adapter.BossClient", return_value=context):
        result = asyncio.run(adapter.send_text(conversation, "你好"))

    client.send_boss_message.assert_not_called()
    chat.send.assert_called_once_with(
        from_uid=1001,
        from_encrypt_uid="self-enc",
        to_uid=503956637,
        to_encrypt_uid="encrypt-from-detail",
        text="你好",
    )
    assert result.success is True


def test_boss_live_golden_fixture_maps_stable_ids_and_direction():
    adapter = BossPlatformAdapter()
    adapter._actor = Actor("boss", "1001", "招聘者")
    adapter._peers["2002"] = {
        "uid": "2002",
        "friendId": "friend_77",
        "name": "候选人甲",
        "encryptGeekId": "redacted-encrypt-id",
    }

    message = adapter._message_from_live(load_fixture("boss_live_text.json"))

    assert message is not None
    assert message.message_id == "9001"
    assert str(uuid.UUID(message.event_id)) == message.event_id
    assert message.is_send is False
    assert message.conversation.audience.platform_audience_id == "2002"
    assert message.conversation.platform_conversation_id == "friend_77"
    assert message.conversation.platform_data["encrypt_geek_id"] == "redacted-encrypt-id"


def test_boss_dual_identity_echo_is_still_outgoing():
    adapter = BossPlatformAdapter()
    adapter._actor = Actor("boss", "1001", "招聘者")
    adapter._user_info = {"encryptUserId": "actor-encrypted"}
    adapter._peers["2002"] = {
        "uid": "2002",
        "friendId": "friend_77",
        "name": "候选人甲",
        "encryptGeekId": "candidate-encrypted",
    }
    payload = load_fixture("boss_live_text.json")
    payload.update(
        {
            "uid": 9988,
            "to_uid": 2002,
            "from_name": "actor-encrypted",
            "flag": 65537,
            "direction": "对方",
        }
    )

    message = adapter._message_from_live(payload)

    assert message is not None
    assert message.is_send is True
    assert message.conversation.audience.platform_audience_id == "2002"


def test_boss_history_direction_does_not_trust_received_flag():
    adapter = BossPlatformAdapter()
    adapter._actor = Actor("boss", "1001", "招聘者")
    peer = {"uid": "2002", "friendId": "friend_77", "name": "候选人甲"}
    raw = {
        "mid": 7001,
        "time": 1788926500,
        "received": True,
        "flag": 65537,
        "from": {"uid": 9988},
        "to": {"uid": 2002},
        "body": {"type": 1, "text": "招聘者发出的消息"},
    }

    message = adapter._history_message(raw, peer)

    assert message is not None
    assert message.is_send is True


def test_boss_recovery_enqueues_messages_missed_while_disconnected():
    from unittest.mock import MagicMock, patch

    from message_adapter.platforms.boss.auth import Credential

    adapter = BossPlatformAdapter()
    adapter._actor = Actor("boss", "1001", "招聘者")
    adapter._credential = Credential({"wt2": "redacted", "zp_at": "redacted"})
    adapter._listen_started_ms = 1_700_000_050_000
    adapter._peers_ready.set()
    adapter._peers["2002"] = {"uid": "2002", "friendId": "2002", "name": "李勤超"}
    adapter._loop = MagicMock()
    adapter._loop.is_closed.return_value = False
    queued: list = []
    adapter._enqueue_threadsafe = queued.append
    client = MagicMock()
    client.get_boss_friend_list.return_value = {"result": [{"friendId": 2002}]}
    client.get_boss_last_messages.return_value = [
        {
            "uid": 2002,
            "lastTS": 1_700_000_100_000,
            "lastMsgInfo": {"msgId": 9002, "msgTime": 1_700_000_100_000, "fromId": 2002},
        }
    ]
    client.get_boss_chat_history.return_value = {
        "messages": [
            {
                "mid": 9001,
                "time": 1_700_000_000_000,
                "from": {"uid": 2002},
                "to": {"uid": 1001},
                "body": {"type": 1, "text": "旧消息"},
            },
            {
                "mid": 9002,
                "time": 1_700_000_100_000,
                "from": {"uid": 2002},
                "to": {"uid": 1001},
                "body": {"type": 1, "text": "都有什么岗位"},
            },
        ]
    }
    context = MagicMock()
    context.__enter__.return_value = client

    with patch("message_adapter.platforms.boss.adapter.BossClient", return_value=context):
        adapter._recover_missed_messages()
        adapter._recover_missed_messages()

    assert [item.text for item in queued] == ["都有什么岗位"]
    assert queued[0].message_id == "9002"
    assert queued[0].is_send is False
    client.get_boss_chat_history.assert_called_once()


def test_boss_live_message_is_not_recovered_again():
    from unittest.mock import MagicMock, patch

    from message_adapter.platforms.boss.auth import Credential

    adapter = BossPlatformAdapter()
    adapter._actor = Actor("boss", "1001", "招聘者")
    adapter._credential = Credential({"wt2": "redacted", "zp_at": "redacted"})
    adapter._listen_started_ms = 1_700_000_050_000
    adapter._peers_ready.set()
    adapter._peers["2002"] = {"uid": "2002", "friendId": "2002", "name": "李勤超"}
    adapter._loop = MagicMock()
    adapter._loop.is_closed.return_value = False
    queued: list = []
    adapter._enqueue_threadsafe = queued.append
    assert adapter._claim_message("9002") is True
    client = MagicMock()
    client.get_boss_friend_list.return_value = {"result": [{"friendId": 2002}]}
    client.get_boss_last_messages.return_value = [
        {"uid": 2002, "lastTS": 1_700_000_100_000, "lastMsgInfo": {"msgId": 9002, "msgTime": 1_700_000_100_000}}
    ]
    context = MagicMock()
    context.__enter__.return_value = client

    with patch("message_adapter.platforms.boss.adapter.BossClient", return_value=context):
        adapter._recover_missed_messages()

    assert queued == []
    client.get_boss_chat_history.assert_not_called()


def test_douyin_golden_fixture_prefers_server_message_id(monkeypatch):
    adapter = DouyinPlatformAdapter()
    adapter._actor = Actor("douyin", "1001", "店铺")
    adapter._auth = ImAuth(cookie={"sessionid": "redacted"}, uid="1001", account_name="shop")
    monkeypatch.setattr(
        "message_adapter.platforms.douyin.adapter.peer_profile_for_conversation",
        lambda auth, cid, messages: {"nickname": "买家甲", "avatar": "https://example.test/avatar.jpg"},
    )
    raw = load_fixture("douyin_text.json")
    adapter._conversation_from_raw(raw, [raw])

    message = adapter._message_from_raw(raw)

    assert message is not None
    assert message.message_id == "88001234"
    assert str(uuid.UUID(message.event_id)) == message.event_id
    assert message.is_send is False
    assert message.text == "请问今天能发货吗"
    assert message.conversation.audience.platform_audience_id == "2002"
    assert message.conversation.platform_conversation_id == "0:1:1001:2002"
    assert message.content_type == 101
    assert message.content == {"text": "请问今天能发货吗"}


def _douyin_raw(**overrides):
    raw = load_fixture("douyin_text.json")
    raw.update(overrides)
    return raw


def test_douyin_media_types_use_qkserver_content(monkeypatch):
    adapter = DouyinPlatformAdapter()
    adapter._actor = Actor("douyin", "1001", "店铺")
    adapter._auth = ImAuth(cookie={"sessionid": "redacted"}, uid="1001", account_name="shop")
    monkeypatch.setattr(
        "message_adapter.platforms.douyin.adapter.peer_profile_for_conversation",
        lambda auth, cid, messages: {},
    )

    image = adapter._message_from_raw(
        _douyin_raw(
            message_type=27,
            server_message_id="img-1",
            content=json.dumps(
                {
                    "resource_url": {
                        "url_list": ["https://example.test/photo.jpg"],
                        "width": 1080,
                        "height": 1440,
                    },
                    "size": 245812,
                }
            ),
        )
    )
    assert image is not None
    assert image.content_type == 102
    picture = image.content["picture"]["sourcePicture"]
    assert picture["type"] == "image"
    assert picture["url"] == "https://example.test/photo.jpg"
    assert picture["width"] == 1080
    assert picture["height"] == 1440
    assert picture["size"] == 245812

    emoji = adapter._message_from_raw(
        _douyin_raw(
            message_type=5,
            server_message_id="emoji-1",
            content=json.dumps({"emoji_url": "https://example.test/a.gif"}),
        )
    )
    assert emoji is not None
    assert emoji.content["picture"]["sourcePicture"]["type"] == "emoji"

    voice = adapter._message_from_raw(
        _douyin_raw(
            message_type=17,
            server_message_id="voice-1",
            content=json.dumps(
                {"resource_url": {"url_list": ["https://example.test/voice.m4a"]}, "duration": 3.8, "size": 58120}
            ),
        )
    )
    assert voice is not None
    assert voice.content_type == 103
    assert voice.content["voice"]["sourceUrl"] == "https://example.test/voice.m4a"
    assert voice.content["voice"]["duration"] == 3800
    assert voice.content["voice"]["dataSize"] == 58120

    video = adapter._message_from_raw(
        _douyin_raw(
            message_type=8,
            server_message_id="video-1",
            content=json.dumps(
                {
                    "itemId": "7123456789012345678",
                    "content_title": "发货实拍",
                    "cover_url": {"url_list": ["https://example.test/cover.jpg"]},
                }
            ),
        )
    )
    assert video is not None
    assert video.content_type == 104
    assert video.content["video"]["videoUrl"] == "https://www.douyin.com/video/7123456789012345678"
    assert video.content["video"]["snapshotUrl"] == "https://example.test/cover.jpg"

    quoted = adapter._message_from_raw(
        _douyin_raw(
            message_type=7,
            server_message_id="quote-1",
            content=json.dumps({"text": "好的，我确认一下", "quote_content": "「明天发货」"}),
        )
    )
    assert quoted is not None
    assert quoted.content_type == 114
    assert quoted.content["quote"]["text"] == "好的，我确认一下"
    assert quoted.content["quote"]["quoteMessage"] == {"text": "明天发货"}

    assert adapter._message_from_raw(_douyin_raw(message_type=50001, content='{"read_index":1}')) is None


def test_douyin_conversation_index_fallback_is_namespaced(monkeypatch):
    adapter = DouyinPlatformAdapter()
    adapter._actor = Actor("douyin", "1001", "店铺")
    adapter._auth = ImAuth(cookie={"sessionid": "redacted"}, uid="1001", account_name="shop")
    monkeypatch.setattr(
        "message_adapter.platforms.douyin.adapter.peer_profile_for_conversation",
        lambda auth, cid, messages: {},
    )
    raw = load_fixture("douyin_text.json")
    raw["server_message_id"] = ""

    message = adapter._message_from_raw(raw)

    assert message is not None
    assert message.message_id == "0:1:1001:2002:42"


def test_douyin_lifecycle_never_reads_history():
    async def scenario():
        adapter = DouyinPlatformAdapter()

        baseline = await adapter.bootstrap()
        recovered = await adapter.catch_up("1700000000000")

        assert baseline.conversations == ()
        assert baseline.baseline_message_ids == frozenset()
        assert recovered == []
        assert adapter.capabilities.history_backfill is False

    asyncio.run(scenario())


def test_douyin_send_logs_target_and_result(monkeypatch, caplog):
    async def scenario():
        adapter = DouyinPlatformAdapter()
        adapter._actor = Actor("douyin", "1001", "店铺")
        adapter._auth = ImAuth(cookie={"sessionid": "redacted"}, uid="1001", account_name="shop")
        conversation = Conversation(
            "douyin",
            "1001",
            Audience("2002", "买家甲"),
            "0:1:1001:2002",
            {"conversation_short_id": 99, "conversation_ticket": "ticket"},
        )
        monkeypatch.setattr(
            "message_adapter.platforms.douyin.adapter.send_text",
            lambda *args, **kwargs: {"ok": True, "server_message_id": "message-88"},
        )

        with caplog.at_level(logging.INFO, logger="message_adapter.platforms.douyin.adapter"):
            result = await adapter.send_text(conversation, "你好")

        assert result.success is True
        assert "Douyin send started platform_actor_id=1001 platform_audience_id=2002" in caplog.text
        assert "conversation_id=0:1:1001:2002 content_length=2" in caplog.text
        assert "Douyin send completed" in caplog.text
        assert "success=True platform_message_id=message-88" in caplog.text

    asyncio.run(scenario())


def test_boss_protobuf_golden_bytes_are_unchanged():
    from message_adapter.platforms.boss.mqtt import build_text_message

    encoded = build_text_message(
        11,
        "fromEnc",
        22,
        "toEnc",
        "hello-boss",
        temp_id=1700000000000,
        flag=65537,
    )
    assert encoded.hex() == (
        "08011a450a0b080b120766726f6d456e63120908161205746f456e631801"
        "2080d095ffbc312880d095ffbc313210080110011a0a68656c6c6f2d626f"
        "73735880d095ffbc3178818004"
    )


def test_platform_adapters_prefer_sqlite_credentials(tmp_path):
    store = CredentialStore(tmp_path / "credentials.sqlite3")
    store.save("boss", {"cookies": {"wt2": "redacted", "zp_at": "redacted"}})
    store.save(
        "douyin",
        {
            "cookie": {
                "name": "shop",
                "cookie": "sessionid=redacted",
                "sessionid": "redacted",
                "uid": "1001",
            },
            "im": {"DY_TICKET": "redacted-ticket"},
        },
    )

    boss = BossPlatformAdapter(credentials=store)
    douyin = DouyinPlatformAdapter(credentials=store)
    stored_boss = boss._stored_credential()
    stored_douyin = douyin._stored_credential()

    assert stored_boss is not None and stored_boss.cookies["wt2"] == "redacted"
    assert stored_douyin is not None
    assert stored_douyin[0].uid == "1001"
    assert stored_douyin[1]["DY_TICKET"] == "redacted-ticket"
    store.close()
