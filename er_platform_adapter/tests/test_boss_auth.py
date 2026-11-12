"""BOSS credential-loading tests."""

from __future__ import annotations

import os
from unittest.mock import patch

from message_adapter.platforms.boss.auth import load_from_env


def test_load_from_env_valid():
    with patch.dict(os.environ, {"BOSS_COOKIES": "wt2=abc; wbg=def; zp_at=ghi; __zp_stoken__=jkl"}):
        credential = load_from_env()

    assert credential is not None
    assert credential.cookies == {
        "wt2": "abc",
        "wbg": "def",
        "zp_at": "ghi",
        "__zp_stoken__": "jkl",
    }


def test_load_from_env_empty():
    with patch.dict(os.environ, {"BOSS_COOKIES": ""}):
        assert load_from_env() is None


def test_load_from_env_unset():
    environment = os.environ.copy()
    environment.pop("BOSS_COOKIES", None)
    with patch.dict(os.environ, environment, clear=True):
        assert load_from_env() is None


def test_load_from_env_malformed():
    with patch.dict(os.environ, {"BOSS_COOKIES": "no-equals-here; also-bad"}):
        assert load_from_env() is None
