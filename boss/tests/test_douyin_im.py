"""Tests for Douyin uid inference when profile API is blocked."""

from __future__ import annotations

from unittest.mock import MagicMock

from boss_cli.douyin.im import infer_self_uid


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
