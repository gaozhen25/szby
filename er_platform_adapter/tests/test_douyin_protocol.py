"""Tests for Douyin uid inference when profile API is blocked."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock

from message_adapter.platforms.douyin import protocol
from message_adapter.platforms.douyin.protocol import ImAuth, infer_self_uid


def test_infer_self_uid_from_conversations():
    auth = MagicMock()
    auth.cookie = {}
    auth.cookie_str = ""
    convs = [
        {"conversation_id": "0:1:111:222"},
        {"conversation_id": "0:1:111:333"},
        {"conversation_id": "0:1:111:444"},
    ]
    assert infer_self_uid(auth, convs=convs) == "111"


def test_infer_self_uid_from_cookie_jar():
    auth = MagicMock()
    auth.cookie = {"uid_tt": "9876543210"}
    auth.cookie_str = "uid_tt=9876543210"
    assert infer_self_uid(auth, convs=[]) == "9876543210"


def test_send_response_accepts_server_id_without_ok_text():
    body = protocol._enc_bytes(100, protocol._enc_varint_field(1, 7351234567890123456))
    packet = b"".join(
        [
            protocol._enc_varint_field(1, 100),
            protocol._enc_varint_field(3, 0),
            protocol._enc_bytes(6, body),
        ]
    )

    parsed = protocol._parse_send_response(packet)

    assert parsed["ok"] is True
    assert parsed["server_message_id"] == "7351234567890123456"
    assert parsed["error_desc"] == ""


def test_send_response_reports_numeric_rejection():
    parsed = protocol._parse_send_response(protocol._enc_varint_field(3, 4))

    assert parsed["ok"] is False
    assert parsed["status_code"] == 4
    assert "status_code=4" in parsed["error_desc"]


def test_send_response_still_rejects_relogin_payload():
    payload = json.dumps({"status_code": 7911, "tips": "重新登录后可以正常使用私信"}, ensure_ascii=False).encode()
    body = protocol._enc_bytes(100, protocol._enc_bytes(6, payload))
    packet = b"".join([protocol._enc_bytes(4, "OK"), protocol._enc_bytes(6, body)])

    parsed = protocol._parse_send_response(packet)

    assert parsed["ok"] is False
    assert "重新登录" in parsed["error_desc"]


def test_send_response_keeps_message_body_server_id():
    message = protocol._enc_bytes(3, b"7351234567890123456")
    body = protocol._enc_bytes(100, protocol._enc_bytes(6, message))
    packet = b"".join([protocol._enc_bytes(4, "OK"), protocol._enc_bytes(6, body)])

    parsed = protocol._parse_send_response(packet)

    assert parsed["ok"] is True
    assert parsed["server_message_id"] == "7351234567890123456"


def test_send_success_does_not_fetch_conversation_history(monkeypatch):
    auth = ImAuth(
        cookie={"sessionid": "session", "s_v_web_id": "fingerprint"},
        ticket="ticket",
        ts_sign="signature",
        client_cert="certificate",
        private_key="private-key",
        uid="1001",
        _client=SimpleNamespace(user_agent="test-agent"),
    )
    requests = []

    class Response:
        status_code = 200
        content = b"response"

    def post(url, **kwargs):
        requests.append((url, kwargs))
        return Response()

    def history_forbidden(*args, **kwargs):
        raise AssertionError("send_text must not read conversation history")

    monkeypatch.setattr(protocol, "_generate_req_sign", lambda *args, **kwargs: "request-sign")
    monkeypatch.setattr(protocol, "_build_request_envelope", lambda *args, **kwargs: b"payload")
    monkeypatch.setattr(protocol, "get_a_bogus", lambda *args, **kwargs: "a-bogus")
    monkeypatch.setattr(protocol, "_protobuf_headers", lambda *args, **kwargs: {})
    monkeypatch.setattr(
        protocol,
        "_parse_send_response",
        lambda payload: {"ok": True, "server_message_id": "message-1"},
    )
    monkeypatch.setattr(protocol.requests, "post", post)
    monkeypatch.setattr(protocol, "get_messages_by_conversation", history_forbidden)

    result = protocol.send_text(
        auth,
        "你好",
        conversation_id="0:1:1001:2002",
        conversation_short_id=123,
        conversation_ticket="conversation-ticket",
    )

    assert result["ok"] is True
    assert result["server_message_id"] == "message-1"
    assert "delivered" not in result
    assert len(requests) == 1
