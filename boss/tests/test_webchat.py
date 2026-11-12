"""Tests for the local recruiter web chat UI."""

from __future__ import annotations

import threading
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from unittest.mock import patch

from click.testing import CliRunner

from boss_cli.auth import Credential
from boss_cli.cli import cli
from boss_cli.webchat.payload import (
    allowed_avatar_url,
    chronological,
    conversation_item,
    history_message,
    mqtt_is_mine,
    pick_avatar,
    public_me,
    query_param,
    safe_peer_name,
)
from boss_cli.webchat.server import RecruiterWebApp, is_client_gone, make_handler


def test_pick_avatar_and_allowlist():
    assert pick_avatar({"tinyAvatar": "https://img.bosszhipin.com/a.png"}) == "https://img.bosszhipin.com/a.png"
    assert pick_avatar({"headImg": "//img.zhipin.com/b.png"}) == "https://img.zhipin.com/b.png"
    assert allowed_avatar_url("https://img.bosszhipin.com/x.jpg")
    assert allowed_avatar_url("https://127.0.0.1/secret") is None
    assert allowed_avatar_url("https://evil.example/zhipin.com") is None
    assert allowed_avatar_url("file:///tmp/x") is None


def test_conversation_item_omits_nothing_required_and_has_name():
    item = conversation_item(
        {
            "uid": 11,
            "friendId": 22,
            "name": "张三",
            "jobName": "Python",
            "tinyAvatar": "https://img.bosszhipin.com/a.png",
            "encryptGeekId": "enc",
            "securityId": "should-stay-in-source-only",
        },
        index=3,
        last_text="你好",
        last_time="10:00",
    )
    assert item["index"] == 3
    assert item["name"] == "张三"
    assert item["job"] == "Python"
    assert item["friendId"] == 22
    assert item["lastMessage"] == "你好"
    assert "securityId" not in item


def test_history_message_sides():
    mine = history_message({"received": False, "body": {"text": "hi"}, "mid": 1, "time": 0}, my_uid=9)
    theirs = history_message({"received": True, "body": {"text": "yo"}, "mid": 2}, my_uid=9)
    by_uid = history_message({"from": {"uid": 9}, "body": {"text": "me"}}, my_uid=9)
    assert mine["mine"] is True
    assert theirs["mine"] is False
    assert by_uid["mine"] is True
    assert public_me({"userId": 9, "name": "Boss"})["name"] == "Boss"


def test_recruiter_history_ignores_received_true():
    """Boss historyMsg marks both sides received=true; align by from.uid instead."""
    peer = 22
    me = 9
    sent = history_message(
        {"received": True, "flag": 65537, "from": {"uid": me}, "to": {"uid": peer}, "body": {"text": "我发的"}},
        my_uid=me,
        peer_uid=peer,
    )
    got = history_message(
        {"received": True, "flag": 1, "from": {"uid": peer}, "to": {"uid": me}, "body": {"text": "对方发的"}},
        my_uid=me,
        peer_uid=peer,
    )
    assert sent["mine"] is True
    assert got["mine"] is False
    via_peer_only = history_message(
        {"received": True, "from": {"uid": me}, "body": {"text": "我发的"}},
        my_uid=0,
        peer_uid=peer,
    )
    assert via_peer_only["mine"] is True


def test_messages_sorted_oldest_first():
    ordered = chronological([
        {"ts": 300, "mid": 3, "text": "new"},
        {"ts": 100, "mid": 1, "text": "old"},
        {"ts": 200, "mid": 2, "text": "mid"},
    ])
    assert [m["text"] for m in ordered] == ["old", "mid", "new"]


def test_image_and_resume_payload():
    image_msg = history_message(
        {
            "received": True,
            "time": 1_700_000_000_000,
            "mid": 8,
            "body": {
                "type": 3,
                "image": {
                    "tinyImage": {"url": "https://imgaz.bosszhipin.com/tiny.jpg"},
                    "originImage": {"url": "https://imgaz.bosszhipin.com/big.jpg?auth_key=1-0-HF+abc"},
                },
            },
        },
        my_uid=1,
    )
    assert image_msg["kind"] == "image"
    assert image_msg["image"]["origin"].endswith("HF+abc")
    assert allowed_avatar_url(image_msg["image"]["origin"])

    resume_msg = history_message(
        {
            "received": True,
            "mid": 9,
            "body": {
                "type": 9,
                "headTitle": "点击查看牛人简历",
                "resume": {
                    "securityId": "secret",
                    "education": "本科",
                    "workYear": "3年",
                    "content1": "求职期望  Python",
                    "user": {"name": "候选人甲", "avatar": "https://img.bosszhipin.com/a.png"},
                    "pdfUrl": "https://img.bosszhipin.com/resume.pdf",
                },
            },
        },
        my_uid=1,
    )
    assert resume_msg["kind"] == "resume"
    assert resume_msg["resume"]["name"] == "候选人甲"
    assert "securityId" not in resume_msg["resume"]
    assert resume_msg["file"]["url"].endswith("resume.pdf")


def test_emoji_voice_and_office_files_become_text():
    from boss_cli.webchat.payload import history_message, render_emoticons

    assert render_emoticons("你好[狗头]") == "你好🐶"
    emoji = history_message({"body": {"type": 1, "text": "[狗头]"}}, my_uid=1)
    assert emoji["kind"] == "text"
    assert emoji["text"] == "🐶"

    voice = history_message(
        {
            "body": {
                "type": 2,
                "sound": {"url": "https://imgaz.bosszhipin.com/a.amr", "duration": 8},
            }
        },
        my_uid=1,
    )
    assert voice["kind"] == "voice"
    assert voice["text"] == "[语音 8秒]"
    assert voice["audio"]["url"].endswith("a.amr")

    docx = history_message(
        {
            "body": {
                "type": 12,
                "file": {
                    "url": "https://imgaz.bosszhipin.com/resume.docx",
                    "name": "简历.docx",
                },
            }
        },
        my_uid=1,
    )
    assert docx["kind"] == "file"
    assert docx["file"]["name"] == "简历.docx"
    assert "wordprocessingml" in docx["file"]["mime"]
    assert "[文件]" in docx["text"]

    pdf = history_message(
        {
            "body": {
                "file": {
                    "url": "https://imgaz.bosszhipin.com/a.pdf",
                    "name": "附件.pdf",
                }
            }
        },
        my_uid=1,
    )
    assert pdf["kind"] == "pdf"
    assert pdf["file"]["mime"] == "application/pdf"


def test_query_param_keeps_plus():
    raw = "u=" + "https%3A%2F%2Fimgaz.bosszhipin.com%2Fx%3Fauth_key%3D1-0-HF%2B2969"
    assert query_param(raw, "u").endswith("HF+2969")


def test_web_command_help():
    result = CliRunner().invoke(cli, ["recruiter", "web", "--help"])
    assert result.exit_code == 0
    assert "--port" in result.output
    assert "头像" in result.output or "网页" in result.output


def test_is_client_gone_swallows_browser_disconnects():
    assert is_client_gone(ConnectionResetError(54, "Connection reset by peer"))
    assert is_client_gone(BrokenPipeError())
    assert not is_client_gone(ValueError("bad json"))
    assert not is_client_gone(None)


def test_http_serves_ui_and_rejects_bad_avatar():
    app = RecruiterWebApp(Credential(cookies={}), start_mqtt=False)
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(app))
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        conn = HTTPConnection("127.0.0.1", port, timeout=5)
        conn.request("GET", "/")
        resp = conn.getresponse()
        body = resp.read()
        assert resp.status == 200
        assert "沟通".encode("utf-8") in body
        conn.close()

        conn = HTTPConnection("127.0.0.1", port, timeout=5)
        conn.request("GET", "/app.css")
        css = conn.getresponse()
        assert css.status == 200
        css.read()
        conn.close()

        conn = HTTPConnection("127.0.0.1", port, timeout=5)
        conn.request("GET", "/app.js")
        js = conn.getresponse()
        assert js.status == 200
        js.read()
        conn.close()

        conn = HTTPConnection("127.0.0.1", port, timeout=5)
        conn.request("GET", "/api/avatar?u=http://127.0.0.1/x")
        av = conn.getresponse()
        assert av.status == 404
        av.read()
        conn.close()
    finally:
        server.shutdown()
        server.server_close()
        app.stop()


def test_api_send_rejects_empty_text():
    app = RecruiterWebApp(Credential(cookies={}), start_mqtt=False)
    result = app.api_send(1, "   ")
    assert result["ok"] is False
    assert result["error"]["code"] == "invalid_params"


def test_mqtt_is_mine_dual_identity_echo():
    assert mqtt_is_mine(from_uid=9, to_uid=22, my_uid=9) is True
    assert mqtt_is_mine(
        from_uid=888,
        to_uid=22,
        flag=65537,
        my_uid=9,
        from_name="招聘者甲",
        my_name="招聘者甲",
    ) is True
    assert mqtt_is_mine(
        from_uid=888,
        to_uid=22,
        my_uid=9,
        from_name="enc-me",
        my_encrypt="enc-me",
    ) is True
    assert mqtt_is_mine(from_uid=22, to_uid=9, flag=1, my_uid=9, from_name="候选人乙") is False


def test_api_send_returns_immediately_and_keeps_peer_name(monkeypatch):
    app = RecruiterWebApp(Credential(cookies={}), start_mqtt=False)
    app._me = {"uid": 9, "name": "招聘者甲", "avatar": ""}
    app._my_encrypt_uid = "enc-me"
    app._remember_peer({
        "uid": 22,
        "friendId": 22,
        "name": "候选人乙",
        "encryptGeekId": "enc-geek",
        "avatar": "",
    })
    events = []
    monkeypatch.setattr(app, "_broadcast", events.append)

    class FakeClient:
        def send_boss_message(self, **kwargs):
            return True

        def get_boss_chat_history(self, **kwargs):
            raise AssertionError("send should not wait for history")

    monkeypatch.setattr(app, "_with_client", lambda action: action(FakeClient()))
    result = app.api_send(22, "hello")
    assert result["ok"] is True
    assert result["data"]["mine"] is True
    assert result["data"]["name"] == "候选人乙"
    assert events[0]["name"] == "候选人乙"
    assert events[0]["uid"] == 22


def test_mqtt_own_echo_does_not_replace_peer_name():
    app = RecruiterWebApp(Credential(cookies={}), start_mqtt=False)
    app._me = {"uid": 9, "name": "招聘者甲", "avatar": ""}
    app._my_encrypt_uid = "enc-me"
    app._remember_peer({
        "uid": 22,
        "friendId": 22,
        "name": "候选人乙",
        "encryptGeekId": "enc-geek",
        "avatar": "https://img.bosszhipin.com/a.png",
    })
    events = []
    app._broadcast = events.append
    app._handle_mqtt_frame(
        {
            "type": 1,
            "messages": [
                {
                    "from": {"uid": 888, "name": "招聘者甲"},
                    "to": {"uid": 22, "name": "enc-geek"},
                    "flag": 65537,
                    "body": {"text": "hi"},
                    "time": 1_700_000_000_000,
                    "mid": 11,
                }
            ],
        },
        my_uid=9,
    )
    assert events[0]["mine"] is True
    assert events[0]["name"] == "候选人乙"
    assert events[0]["avatar"] == "https://img.bosszhipin.com/a.png"
    assert events[0]["uid"] == 22
    app._handle_mqtt_frame(
        {
            "type": 1,
            "messages": [
                {
                    "from": {"uid": 22, "name": "enc-geek"},
                    "to": {"uid": 9},
                    "flag": 1,
                    "body": {"text": "yo"},
                    "mid": 12,
                }
            ],
        },
        my_uid=9,
    )
    assert events[-1]["mine"] is False
    assert events[-1]["name"] == "候选人乙"
    assert events[-1]["avatar"] == "https://img.bosszhipin.com/a.png"


def test_safe_peer_name_drops_encrypt_and_self():
    assert safe_peer_name("李四") == "李四"
    assert safe_peer_name("招聘者甲", my_name="招聘者甲") == ""
    assert safe_peer_name("enc-me", my_encrypt="enc-me") == ""
    assert safe_peer_name("524186056") == ""
    assert safe_peer_name("a" * 20) == ""


def test_incoming_mqtt_uses_display_name_when_cache_empty():
    app = RecruiterWebApp(Credential(cookies={}), start_mqtt=False)
    app._me = {"uid": 9, "name": "招聘者甲", "avatar": ""}
    events = []
    app._broadcast = events.append
    app._handle_mqtt_frame(
        {
            "type": 1,
            "messages": [
                {
                    "from": {"uid": 33, "name": "李四"},
                    "to": {"uid": 9},
                    "flag": 1,
                    "body": {"text": "在吗"},
                    "mid": 21,
                }
            ],
        },
        my_uid=9,
    )
    assert events[0]["mine"] is False
    assert events[0]["name"] == "李四"


def test_web_requires_login():
    with patch("boss_cli.commands.recruiter.require_auth", side_effect=SystemExit(1)):
        result = CliRunner().invoke(cli, ["recruiter", "web", "--no-open"])
        assert result.exit_code != 0
