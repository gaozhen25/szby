"""Tests for boss-only Douyin cookie storage."""

from __future__ import annotations

import pytest

from boss_cli.douyin.credentials import (
    import_im_cred_from_spider,
    list_douyin_accounts,
    load_douyin_cookie,
    load_im_cred,
    save_douyin_cookie,
    save_im_cred,
    set_active_douyin_account,
)


def test_load_douyin_cookie_from_env(monkeypatch):
    monkeypatch.setenv("DY_COOKIE", "sessionid=abc; ttwid=1")
    cred = load_douyin_cookie()
    assert cred.name == "env"
    assert cred.source == "env:DY_COOKIE"
    assert "sessionid=abc" in cred.cookie


def test_load_douyin_cookie_from_boss_file(tmp_path, monkeypatch):
    monkeypatch.delenv("DY_COOKIE", raising=False)
    monkeypatch.setattr("boss_cli.douyin.credentials.DOUYIN_DIR", tmp_path)
    monkeypatch.setattr("boss_cli.douyin.credentials.DOUYIN_COOKIE_FILE", tmp_path / "cookies.json")
    monkeypatch.setattr("boss_cli.douyin.credentials.DOUYIN_IM_CRED_FILE", tmp_path / "im_cred.json")
    save_douyin_cookie("sessionid=file123", name="main")
    cred = load_douyin_cookie()
    assert cred.name == "main"
    assert "sessionid=file123" in cred.cookie
    assert str(tmp_path / "cookies.json") in cred.source or cred.source == ""


def test_append_second_account_keeps_first(tmp_path, monkeypatch):
    monkeypatch.delenv("DY_COOKIE", raising=False)
    monkeypatch.setattr("boss_cli.douyin.credentials.DOUYIN_DIR", tmp_path)
    monkeypatch.setattr("boss_cli.douyin.credentials.DOUYIN_COOKIE_FILE", tmp_path / "cookies.json")
    monkeypatch.setattr("boss_cli.douyin.credentials.DOUYIN_IM_CRED_FILE", tmp_path / "im_cred.json")

    save_douyin_cookie("sessionid=aaa111", name="账号A")
    save_douyin_cookie("sessionid=bbb222", name="账号B", append=True)

    rows = list_douyin_accounts()
    assert len(rows) == 2
    names = {row["name"] for row in rows}
    assert names == {"账号A", "账号B"}
    assert load_douyin_cookie().name == "账号B"

    set_active_douyin_account("账号A")
    assert load_douyin_cookie().name == "账号A"


def test_append_im_cred_per_account(tmp_path, monkeypatch):
    monkeypatch.delenv("DY_COOKIE", raising=False)
    monkeypatch.setattr("boss_cli.douyin.credentials.DOUYIN_DIR", tmp_path)
    monkeypatch.setattr("boss_cli.douyin.credentials.DOUYIN_COOKIE_FILE", tmp_path / "cookies.json")
    monkeypatch.setattr("boss_cli.douyin.credentials.DOUYIN_IM_CRED_FILE", tmp_path / "im_cred.json")

    save_douyin_cookie("sessionid=aaa111", name="账号A")
    save_douyin_cookie("sessionid=bbb222", name="账号B", append=True)

    cred_a = {
        "DY_TICKET": "ta",
        "DY_TS_SIGN": "sa",
        "DY_CLIENT_CERT": "ca",
        "DY_PRIVATE_KEY": "pa",
    }
    cred_b = {
        "DY_TICKET": "tb",
        "DY_TS_SIGN": "sb",
        "DY_CLIENT_CERT": "cb",
        "DY_PRIVATE_KEY": "pb",
    }
    save_im_cred(cred_a, account_name="账号A", sessionid="aaa111", append=True)
    save_im_cred(cred_b, account_name="账号B", sessionid="bbb222", append=True)

    set_active_douyin_account("账号A")
    assert load_im_cred().get("DY_TICKET") == "ta"
    set_active_douyin_account("账号B")
    assert load_im_cred().get("DY_TICKET") == "tb"


def test_import_im_cred_from_spider(tmp_path, monkeypatch):
    src = tmp_path / "dy_im_cred.json"
    src.write_text(
        '{"DY_TICKET":"t","DY_TS_SIGN":"s","DY_CLIENT_CERT":"c","DY_PRIVATE_KEY":"p"}',
        encoding="utf-8",
    )
    monkeypatch.setattr("boss_cli.douyin.credentials.DOUYIN_DIR", tmp_path / "douyin")
    monkeypatch.setattr("boss_cli.douyin.credentials.DOUYIN_COOKIE_FILE", tmp_path / "douyin" / "cookies.json")
    monkeypatch.setattr("boss_cli.douyin.credentials.DOUYIN_IM_CRED_FILE", tmp_path / "douyin" / "im_cred.json")
    save_douyin_cookie("sessionid=abc123", name="main")
    out = import_im_cred_from_spider(source=src, account_name="main")
    assert out.is_file()
    data = out.read_text(encoding="utf-8")
    assert "DY_TICKET" in data and "DY_PRIVATE_KEY" in data
    assert load_im_cred(account_name="main").get("DY_TICKET") == "t"


def test_no_legacy_spider_fallback(tmp_path, monkeypatch):
    monkeypatch.delenv("DY_COOKIE", raising=False)
    monkeypatch.setattr("boss_cli.douyin.credentials.DOUYIN_DIR", tmp_path / "douyin")
    monkeypatch.setattr("boss_cli.douyin.credentials.DOUYIN_COOKIE_FILE", tmp_path / "douyin" / "cookies.json")
    legacy_dir = tmp_path / "spider" / "js" / "cookies"
    legacy_dir.mkdir(parents=True)
    (legacy_dir / "cookies.json").write_text('{"dy": ["sessionid=legacy"]}', encoding="utf-8")
    monkeypatch.setenv("HOME", str(tmp_path))
    with pytest.raises(RuntimeError, match="未找到抖音 cookie"):
        load_douyin_cookie()
