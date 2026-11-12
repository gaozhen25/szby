"""Unit tests for geek-side MQTT protobuf encoding and chat lookup."""

import json

from boss_cli.index_cache import find_chat, save_chat_index
from boss_cli.mqtt_chat import build_text_message, encode_body, encode_user


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
    from boss_cli.mqtt_chat import decode_chat_protocol, encode_presence

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
    from boss_cli.mqtt_chat import FLAG_BOSS_SENT, decode_chat_protocol

    payload = build_text_message(
        11, "fromEnc", 22, "toEnc", "hello-boss", temp_id=1700000000000, flag=1,
    )
    decoded = decode_chat_protocol(payload)
    assert decoded["messages"][0]["flag"] == 1
    boss = build_text_message(
        11, "fromEnc", 22, "toEnc", "hello-boss", temp_id=1700000000000, flag=FLAG_BOSS_SENT,
    )
    assert decode_chat_protocol(boss)["messages"][0]["flag"] == 65537
    geek = build_text_message(
        11, "fromEnc", 22, "toEnc", "hello-boss", temp_id=1700000000000, flag=0,
    )
    assert decode_chat_protocol(geek)["messages"][0]["flag"] == 0


def test_parse_action_body_uses_extend_text():
    from boss_cli.mqtt_chat import _field_bytes, _field_string, _field_varint, parse_body

    extend = json.dumps({"text": "看过你的简历"}, ensure_ascii=False)
    action = _field_varint(1, 30) + _field_string(2, extend)
    body = parse_body(_field_varint(1, 4) + _field_varint(2, 1) + _field_bytes(6, action))
    assert body["type"] == 4
    assert body["text"] == "看过你的简历"


def test_find_chat_by_index_and_encrypt(tmp_path, monkeypatch):
    cache_dir = tmp_path / "cfg"
    cache_dir.mkdir()
    monkeypatch.setattr("boss_cli.index_cache.CONFIG_DIR", cache_dir)
    monkeypatch.setattr("boss_cli.index_cache.CHAT_INDEX_FILE", cache_dir / "chat_index.json")
    save_chat_index([
        {
            "name": "A",
            "brandName": "Co",
            "jobName": "Dev",
            "encryptBossId": "enc-1",
            "uid": 1001,
        },
        {
            "name": "B",
            "encryptFriendId": "enc-2",
            "friendId": 2002,
        },
    ])
    by_index = find_chat("1")
    assert by_index is not None
    assert by_index["encryptBossId"] == "enc-1"
    assert by_index["uid"] == 1001
    by_enc = find_chat("enc-2")
    assert by_enc is not None
    assert by_enc["uid"] == 2002
    by_uid = find_chat("2002")
    # 2002 is larger than list length, so uid lookup is used
    assert by_uid is not None
    assert by_uid["encryptBossId"] == "enc-2"
    assert find_chat("missing") is None


def test_find_recruiter_by_index_and_encrypt(tmp_path, monkeypatch):
    from boss_cli.index_cache import find_recruiter, find_recruiter_by_uid, save_recruiter_index

    cache_dir = tmp_path / "cfg"
    cache_dir.mkdir()
    monkeypatch.setattr("boss_cli.index_cache.CONFIG_DIR", cache_dir)
    monkeypatch.setattr("boss_cli.index_cache.RECRUITER_INDEX_FILE", cache_dir / "recruiter_index.json")
    save_recruiter_index([
        {
            "name": "GeekA",
            "jobName": "Python",
            "uid": 3001,
            "friendId": 3001,
            "encryptGeekId": "enc-geek-1",
        },
        {
            "name": "GeekB",
            "encryptUid": "enc-geek-2",
            "friendId": 4002,
            "uid": 4002,
        },
    ])
    by_index = find_recruiter("1")
    assert by_index is not None
    assert by_index["encryptGeekId"] == "enc-geek-1"
    assert by_index["uid"] == 3001
    by_enc = find_recruiter("enc-geek-2")
    assert by_enc is not None
    assert by_enc["friendId"] == 4002
    by_uid = find_recruiter("4002")
    assert by_uid is not None
    assert by_uid["encryptGeekId"] == "enc-geek-2"
    assert find_recruiter_by_uid(3001)["name"] == "GeekA"
    assert find_recruiter("missing") is None
