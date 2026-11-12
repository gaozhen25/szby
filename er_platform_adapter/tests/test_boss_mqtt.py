"""Golden tests for the BOSS MQTT protobuf engine."""

import json
import threading
from unittest.mock import patch

from message_adapter.platforms.boss.mqtt import build_text_message, encode_body, encode_user, run_mqtt_listen


def test_encode_body_contains_text():
    payload = encode_body("你好")
    assert "你好".encode("utf-8") in payload


def test_encode_user_contains_encrypt_id():
    payload = encode_user(123, "enc-boss")
    assert b"enc-boss" in payload


def test_build_text_message_round_fields():
    payload = build_text_message(11, "fromEnc", 22, "toEnc", "hello-boss", temp_id=1700000000000)
    assert b"hello-boss" in payload
    assert b"fromEnc" in payload
    assert b"toEnc" in payload
    assert payload.startswith(b"\x08\x01")  # type = 1


def test_decode_roundtrip_text_message():
    from message_adapter.platforms.boss.mqtt import decode_chat_protocol, encode_presence

    payload = build_text_message(11, "fromEnc", 22, "toEnc", "hello-boss", temp_id=1700000000000)
    decoded = decode_chat_protocol(payload)
    assert decoded["type"] == 1
    assert len(decoded["messages"]) == 1
    msg = decoded["messages"][0]
    assert msg["from"]["uid"] == 11
    assert msg["from"]["name"] == "fromEnc"
    assert msg["to"]["uid"] == 22
    assert msg["body"]["text"] == "hello-boss"
    assert msg["mid"] == 1700000000000
    assert msg["time"] == 1700000000000

    presence = encode_presence(123456, presence_type=1)
    assert presence[:2] == b"\x08\x02"


def test_build_text_message_includes_recruiter_flag():
    from message_adapter.platforms.boss.mqtt import FLAG_BOSS_SENT, decode_chat_protocol

    payload = build_text_message(
        11,
        "fromEnc",
        22,
        "toEnc",
        "hello-boss",
        temp_id=1700000000000,
        flag=1,
    )
    decoded = decode_chat_protocol(payload)
    assert decoded["messages"][0]["flag"] == 1
    boss = build_text_message(
        11,
        "fromEnc",
        22,
        "toEnc",
        "hello-boss",
        temp_id=1700000000000,
        flag=FLAG_BOSS_SENT,
    )
    assert decode_chat_protocol(boss)["messages"][0]["flag"] == 65537
    geek = build_text_message(
        11,
        "fromEnc",
        22,
        "toEnc",
        "hello-boss",
        temp_id=1700000000000,
        flag=0,
    )
    assert decode_chat_protocol(geek)["messages"][0]["flag"] == 0


def test_parse_action_body_uses_extend_text():
    from message_adapter.platforms.boss.mqtt import _field_bytes, _field_string, _field_varint, parse_body

    extend = json.dumps({"text": "看过你的简历"}, ensure_ascii=False)
    action = _field_varint(1, 30) + _field_string(2, extend)
    body = parse_body(_field_varint(1, 4) + _field_varint(2, 1) + _field_bytes(6, action))
    assert body["type"] == 4
    assert body["text"] == "看过你的简历"


def test_mqtt_listen_recovers_history_before_reading_frames():
    calls: list[str] = []
    stop = threading.Event()

    class FakeChat:
        dropped = False

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def announce_online(self, uid):
            calls.append(f"online:{uid}")

        def poll_protocol(self, timeout=0.5):
            calls.append("poll")
            stop.set()
            return None

    with patch("message_adapter.platforms.boss.mqtt.BossMQTTChat", return_value=FakeChat()):
        run_mqtt_listen(
            page_token="token",
            wt2="wt2",
            cookies={},
            my_uid=1001,
            poll_seconds=8,
            poll_once=lambda: calls.append("recover"),
            on_message=lambda payload: None,
            stop_event=stop,
        )

    assert calls == ["online:1001", "recover", "poll"]
