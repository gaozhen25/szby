from __future__ import annotations

import asyncio
import json

from message_adapter.core.models import Actor
from message_adapter.platforms.rednote.adapter import RednotePlatformAdapter
from message_adapter.platforms.rednote.im import parse_message_content, uplink_content
from message_adapter.platforms.rednote.im_ws import (
    _complete_send_ack,
    _is_incoming_push,
    _is_send_ack,
    build_send_message_proto,
)


def test_nested_text_content_is_unwrapped():
    text, content_type = parse_message_content('{"content":"你好","content_type":1}')
    assert text == "你好"
    assert content_type == 1


def test_rednote_history_is_manual_only():
    capabilities = RednotePlatformAdapter.capabilities
    assert capabilities.history_backfill is True
    assert capabilities.automatic_catch_up is False


def test_http_text_uses_the_same_uplink_content_type_as_douyin():
    adapter = RednotePlatformAdapter()
    adapter._actor = Actor(platform="rednote", platform_actor_id="100", username="我")
    message = adapter._message_from_http(
        {
            "id": "9",
            "sender_id": "200",
            "content": '{"content":"你好","content_type":1}',
            "created_at": 1_700_000_000_000,
        },
        {"chat_user_id": "200", "info": {"nickname": "对方", "avatar": ""}},
    )
    assert message is not None
    assert message.content_type == 101
    assert message.content == {"text": "你好"}
    assert message.is_send is False
    assert message.conversation.audience.platform_audience_id == "200"
    assert message.conversation.audience.username == "对方"


def _history_content(inner: dict, **extra) -> str:
    payload = {"content": json.dumps(inner, ensure_ascii=False), **extra}
    return json.dumps(payload, ensure_ascii=False)


def test_image_voice_video_and_emoji_use_the_existing_uplink_types():
    adapter = RednotePlatformAdapter()
    adapter._actor = Actor(platform="rednote", platform_actor_id="100", username="我")
    chat = {"chat_user_id": "200", "info": {"nickname": "对方", "avatar": ""}}

    image = adapter._message_from_http(
        {
            "id": "img-1",
            "sender_id": "200",
            "content": _history_content(
                {"link": "https://msg-img.xhscdn.com/a.jpg", "width": 1080, "height": 1440, "size": 245812},
                content_type=9,
                front_chain="[图片]",
            ),
            "created_at": 1_700_000_000_000,
        },
        chat,
    )
    assert image is not None
    assert image.content_type == 102
    assert image.text == "[图片]"
    picture = image.content["picture"]["sourcePicture"]
    assert picture["type"] == "image"
    assert picture["url"] == "https://msg-img.xhscdn.com/a.jpg"
    assert picture["width"] == 1080
    assert picture["height"] == 1440
    assert picture["size"] == 245812

    voice = adapter._message_from_push(
        {
            "message_id": "voice-1",
            "sender": "200",
            "receiver": "100",
            "timestamp_ms": 1_700_000_000_000,
            "message_type": 9,
            "raw_info": {"front_chain": "[语音]", "content_type": 9},
            "raw_inner": {
                "duration": 3.8,
                "link": "https://msg-video.xhscdn.com/audio/a.m4a",
                "size": 58120,
            },
        }
    )
    assert voice is not None
    assert voice.content_type == 103
    assert voice.is_send is False
    assert voice.content["voice"]["sourceUrl"] == "https://msg-video.xhscdn.com/audio/a.m4a"
    assert voice.content["voice"]["duration"] == 3800
    assert voice.content["voice"]["dataSize"] == 58120

    live = uplink_content(
        _history_content(
            {
                "link": "https://msg-img.xhscdn.com/live.jpg",
                "width": 720,
                "height": 1280,
                "livePhotoVideo": {"videoLink": "https://msg-video.xhscdn.com/chat_livephoto/a.mp4", "duration": 2},
            },
            content_type=9,
            front_chain="[视频]",
        )
    )
    assert live is not None
    assert live["content_type"] == 104
    assert live["content"]["video"]["videoUrl"] == "https://msg-video.xhscdn.com/chat_livephoto/a.mp4"
    assert live["content"]["video"]["snapshotUrl"] == "https://msg-img.xhscdn.com/live.jpg"
    assert live["content"]["video"]["duration"] == 2000
    assert live["content"]["video"]["snapshotWidth"] == 720

    emoji = uplink_content('{"content":"[微笑R]","content_type":1}')
    assert emoji == {"content_type": 101, "text": "[微笑R]", "content": {"text": "[微笑R]"}}

    revoked = adapter._message_from_push(
        {
            "message_id": "gone",
            "sender": "200",
            "receiver": "100",
            "revoked": True,
            "text": "已撤回",
        }
    )
    assert revoked is None


def test_send_text_uses_the_live_socket_and_requires_a_server_message_id():
    adapter = RednotePlatformAdapter()
    adapter._actor = Actor(platform="rednote", platform_actor_id="100", username="我")
    adapter._credential = type("Cred", (), {"cookie": "web_session=abc", "device_id": "device-1"})()
    calls = {}

    def fake_send(from_uid, to_uid, content, nickname, **kwargs):
        calls["args"] = (from_uid, to_uid, content, nickname)
        return {"ok": True, "message_id": ""}

    adapter._im.send_text = fake_send
    conversation = adapter._conversation("200", nickname="对方")

    result = asyncio.run(adapter.send_text(conversation, "在吗"))
    assert result.success is False
    assert calls["args"] == ("100", "200", "在吗", "我")

    def confirmed(from_uid, to_uid, content, nickname, **kwargs):
        return {"ok": True, "message_id": "mid-1"}

    adapter._im.send_text = confirmed
    result = asyncio.run(adapter.send_text(conversation, "在吗"))
    assert result.success is True
    assert result.platform_message_id == "mid-1"


def test_send_waits_when_the_live_socket_is_down():
    adapter = RednotePlatformAdapter()
    adapter._actor = Actor(platform="rednote", platform_actor_id="100", username="我")
    adapter._credential = type("Cred", (), {"cookie": "web_session=abc", "device_id": "device-1"})()

    def offline(*args, **kwargs):
        return {"ok": False, "message_id": "", "error": "not connected"}

    adapter._im.send_text = offline
    result = asyncio.run(adapter.send_text(adapter._conversation("200"), "在吗"))
    assert result.success is False
    assert result.retryable is True


def test_incoming_push_is_not_treated_as_a_send_ack():
    push = {"t": 4, "m": "push-1", "b": {"d": {"b": [{"d": "abc"}]}}}
    ack = {"t": 3, "m": "send-1", "b": {"a": {"c": 0, "b": ""}}}
    assert _is_incoming_push(push) is True
    assert _is_send_ack(push) is False
    assert _is_send_ack(ack) is True
    pending = [{"event": type("E", (), {"set": lambda self: None, "is_set": lambda self: True})(), "frame_id": "send-1", "result": None}]
    _complete_send_ack(pending, ack)
    assert pending == []


def test_send_protobuf_carries_both_users_and_text():
    payload = build_send_message_proto("100", "200", "你好", "我")
    assert b"100" in payload
    assert b"200" in payload
    assert "你好".encode() in payload
