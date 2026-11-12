"""Tests for Douyin web chat payload helpers."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from boss_cli.douyin_web.payload import (
    allowed_media_url,
    avatar_from_user,
    conversation_item,
    history_message,
    live_message,
    media_url_fallbacks,
    public_me,
)


def test_allowed_media_url_douyin_hosts():
    assert allowed_media_url("https://p3-sign.douyinpic.com/a.jpg")
    assert allowed_media_url("https://p16-sign.tiktokcdn-us.com/a.jpeg")
    assert allowed_media_url("https://127.0.0.1/x") is None
    assert allowed_media_url("https://evil.example/douyinpic.com") is None


def test_avatar_from_user_prefers_jpeg_over_heic():
    url = avatar_from_user(
        {
            "avatar_thumb": {
                "url_list": [
                    "https://p3.douyinpic.com/a.webp",
                    "https://p3-sign.douyinpic.com/a.heic?x-signature=1",
                    "https://p11.douyinpic.com/a.jpeg",
                ]
            }
        }
    )
    assert url.endswith("a.jpeg")


def test_media_url_fallbacks_heic_and_sign_host():
    urls = media_url_fallbacks("https://p3-sign.douyinpic.com/aweme/a.heic?from=1")
    assert urls[0] == "https://p3-sign.douyinpic.com/aweme/a.jpeg?from=1"
    assert "https://p3.douyinpic.com/aweme/a.jpeg?from=1" in urls
    assert "https://p3-sign.douyinpic.com/aweme/a.heic?from=1" in urls


def test_conversation_item_uses_string_friend_id():
    item = conversation_item(
        index=1,
        conversation_id="0:1:111:222",
        conversation_short_id=999,
        peer_uid="222",
        peer_unique_id="dy_user",
        name="测试用户",
        avatar="https://p3-sign.douyinpic.com/a.jpg",
        last_text="你好",
        last_time="12:00",
    )
    assert item["friendId"] == "0:1:111:222"
    assert item["uid"] == "222"
    assert item["name"] == "测试用户"
    assert item["job"] == "dy_user"
    assert item["_meta"]["conversation_short_id"] == 999


def test_history_message_text_and_mine():
    auth = MagicMock()
    raw = {
        "message_type": 7,
        "sender": "111",
        "content": '{"text":"你好"}',
        "server_message_id": "mid-1",
        "create_time_ms": 1_700_000_000_000,
    }
    with patch("boss_cli.douyin.im.resolve_user_profile", return_value={"nickname": "对方"}):
        view = history_message(auth, raw, my_uid="111", peer_name="对方")
    assert view is not None
    assert view["mine"] is True
    assert view["text"] == "你好"
    assert view["mid"] == "mid-1"


def test_history_message_skips_read_receipt():
    auth = MagicMock()
    skipped = history_message(auth, {"message_type": 50001}, my_uid="1")
    assert skipped is None


def test_live_message_keeps_conversation_id():
    event = live_message(
        conversation_id="0:1:1:2",
        peer_uid="2",
        text="hi",
        mine=True,
        from_uid="1",
        avatar="https://p3-sign.douyinpic.com/a.jpg",
    )
    assert event["friendId"] == "0:1:1:2"
    assert event["type"] == "message"
    assert event["mine"] is True
    assert event["fromUid"] == "1"
    assert event["avatar"].startswith("https://")


def test_public_me():
    me = public_me({"uid": "9", "nickname": "Me", "unique_id": "abc"}, avatar="https://x/a.jpg")
    assert me["uid"] == "9"
    assert me["name"] == "Me"
    assert me["uniqueId"] == "abc"
