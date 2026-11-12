from __future__ import annotations

import pytest

from message_adapter.platforms.douyin.credentials import (
    load_douyin_cookie,
    load_im_cred,
    save_douyin_cookie,
    save_im_cred,
)
from message_adapter.storage import CredentialStore


@pytest.fixture
def vault(tmp_path):
    store = CredentialStore(tmp_path / "credentials.sqlite3")
    yield store
    store.close()


def test_load_douyin_cookie_from_env(monkeypatch, vault):
    monkeypatch.setenv("DY_COOKIE", "sessionid=abc; ttwid=1")
    credential = load_douyin_cookie(store=vault)
    assert credential.name == "douyin"
    assert credential.source == "env:DY_COOKIE"
    assert credential.sessionid == "abc"


def test_cookie_round_trip_uses_single_device_slot(monkeypatch, vault):
    monkeypatch.delenv("DY_COOKIE", raising=False)
    save_douyin_cookie(
        "sessionid=file123",
        store=vault,
        name="门店 A",
        uid="12345",
    )
    credential = load_douyin_cookie(store=vault)
    assert credential.name == "门店 A"
    assert credential.source == "manual"
    assert credential.uid == "12345"


def test_different_uid_cannot_overwrite_bound_slot(monkeypatch, vault):
    monkeypatch.delenv("DY_COOKIE", raising=False)
    save_douyin_cookie(
        "sessionid=aaa111",
        store=vault,
        name="账号A",
        uid="1001",
        browser_profile="/private/profiles/douyin/a",
    )
    with pytest.raises(RuntimeError, match="bound to platform_actor_id=1001"):
        save_douyin_cookie("sessionid=bbb222", store=vault, name="账号B", uid="2002")

    assert load_douyin_cookie(store=vault).sessionid == "aaa111"
    assert load_douyin_cookie(store=vault).browser_profile == "/private/profiles/douyin/a"


def test_send_credentials_are_bound_to_cookie_session(monkeypatch, vault):
    monkeypatch.delenv("DY_COOKIE", raising=False)
    save_douyin_cookie("sessionid=aaa111", store=vault, name="账号A")
    send_credential = {
        "DY_TICKET": "ticket",
        "DY_TS_SIGN": "signature",
        "DY_CLIENT_CERT": "certificate",
        "DY_PRIVATE_KEY": "private-key",
    }
    save_im_cred(send_credential, store=vault, sessionid="aaa111")

    assert load_im_cred(store=vault, sessionid="aaa111") == send_credential
    assert load_im_cred(store=vault, sessionid="different") == {}


def test_missing_device_slot_does_not_scan_historical_files(monkeypatch, vault):
    monkeypatch.delenv("DY_COOKIE", raising=False)
    with pytest.raises(RuntimeError, match="凭证不存在"):
        load_douyin_cookie(store=vault)
