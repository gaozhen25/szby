from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import os
from pathlib import Path
import sys
from types import ModuleType

import pytest

from message_adapter.browser_profiles import BrowserProfile, migrate_legacy_browser_profile
from message_adapter.config import AdapterConfig
from message_adapter.core.models import Actor
from message_adapter.platforms.boss.browser import login_with_profile
from message_adapter.storage import CredentialStore, SQLiteStore, migrate_legacy_state_database


def test_config_uses_one_fixed_state_path_per_platform(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    missing = str(tmp_path / "missing.env")

    first = AdapterConfig.load(platform="douyin", dotenv=missing)
    second = AdapterConfig.load(platform="douyin", dotenv=missing)

    assert first.state_db == second.state_db
    assert first.state_db.as_posix() == "adapter_data/douyin.sqlite3"


def test_profile_prepare_creates_private_device_directory(tmp_path):
    profile = BrowserProfile(tmp_path / "profiles", "boss")

    path = profile.prepare()

    assert path == profile.path
    assert path.name == "device"
    assert path.is_dir()
    if os.name == "posix":
        assert path.stat().st_mode & 0o777 == 0o700
        assert profile.lock_path.parent.stat().st_mode & 0o777 == 0o700


def test_profile_rejects_unsafe_platform_path(tmp_path):
    profile = BrowserProfile(tmp_path / "profiles", "../boss")

    with pytest.raises(ValueError, match="invalid browser-profile platform"):
        profile.prepare()


def test_profile_launch_uses_installed_visible_google_chrome(tmp_path, monkeypatch):
    calls = []

    class FakeContext:
        async def close(self):
            calls.append(("close", {}))

    class FakeChromium:
        async def launch_persistent_context(self, **kwargs):
            calls.append(("launch", kwargs))
            return FakeContext()

    class FakePlaywright:
        chromium = FakeChromium()

        async def stop(self):
            calls.append(("stop", {}))

    class FakeStarter:
        async def start(self):
            return FakePlaywright()

    async_api = ModuleType("playwright.async_api")
    async_api.async_playwright = lambda: FakeStarter()
    monkeypatch.setitem(sys.modules, "playwright", ModuleType("playwright"))
    monkeypatch.setitem(sys.modules, "playwright.async_api", async_api)
    profile = BrowserProfile(tmp_path / "profiles", "douyin")

    async def run():
        async with profile.launch() as context:
            assert isinstance(context, FakeContext)

    asyncio.run(run())

    launch = calls[0][1]
    assert launch["channel"] == "chrome"
    assert launch["headless"] is False
    assert launch["user_data_dir"] == str(profile.path)
    assert [name for name, _ in calls] == ["launch", "close", "stop"]


def test_cdp_launch_attaches_to_local_chrome_without_automation_flag(tmp_path, monkeypatch):
    from message_adapter import browser_profiles as profiles

    chrome = tmp_path / "Google Chrome"
    chrome.write_text("")
    monkeypatch.setattr(profiles, "chrome_executable", lambda: chrome)
    commands = []

    class FakeProc:
        def poll(self):
            return None

        def terminate(self):
            commands.append("terminate")

        def wait(self, timeout=None):
            return 0

        def kill(self):
            commands.append("kill")

    monkeypatch.setattr(profiles.subprocess, "Popen", lambda cmd, **kwargs: commands.append(cmd) or FakeProc())

    class FakeResponse:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(profiles.urllib.request, "urlopen", lambda *args, **kwargs: FakeResponse())

    calls = []

    class FakeContext:
        pass

    class FakeBrowser:
        contexts = [FakeContext()]

        async def close(self):
            calls.append("browser.close")

    class FakeChromium:
        async def connect_over_cdp(self, endpoint):
            calls.append(endpoint)
            return FakeBrowser()

    class FakePlaywright:
        chromium = FakeChromium()

        async def stop(self):
            calls.append("stop")

    class FakeStarter:
        async def start(self):
            return FakePlaywright()

    async_api = ModuleType("playwright.async_api")
    async_api.async_playwright = lambda: FakeStarter()
    monkeypatch.setitem(sys.modules, "playwright", ModuleType("playwright"))
    monkeypatch.setitem(sys.modules, "playwright.async_api", async_api)
    profile = BrowserProfile(tmp_path / "profiles", "boss")

    async def run():
        async with profile.launch_over_cdp() as context:
            assert isinstance(context, FakeContext)

    asyncio.run(run())

    command = commands[0]
    assert "--enable-automation" not in command
    assert any(str(arg).startswith("--remote-debugging-port=") for arg in command)
    assert f"--user-data-dir={profile.path}" in command
    assert str(calls[0]).startswith("http://127.0.0.1:")
    assert "terminate" in commands


def test_legacy_state_migration_requires_one_platform_slot(tmp_path):
    source = tmp_path / "douyin-old.sqlite3"
    destination = tmp_path / "douyin.sqlite3"
    store = SQLiteStore(source)
    store.save_actor(Actor("douyin", "1001"))
    store.close()
    config = AdapterConfig(
        platform="douyin",
        rabbitmq_host="rabbit.test",
        rabbitmq_user="adapter",
        rabbitmq_password="secret",
        state_db=destination,
        legacy_state_dbs=(source,),
    )

    assert migrate_legacy_state_database(config) is True
    assert destination.exists()
    assert not source.exists()
    migrated = SQLiteStore(destination)
    assert migrated.get_bootstrap("douyin") == (False, "")
    migrated.close()


def test_legacy_state_migration_accepts_relative_candidate_paths(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    source = Path("adapter_data/boss-old.sqlite3")
    store = SQLiteStore(source)
    store.save_actor(Actor("boss", "1001"))
    store.close()
    credentials = CredentialStore(Path("adapter_data/credentials.sqlite3"))
    credentials.save("boss", {"cookies": {"wt2": "one"}}, platform_actor_id="1001")
    credentials.close()
    config = AdapterConfig(
        platform="boss",
        rabbitmq_host="rabbit.test",
        rabbitmq_user="adapter",
        rabbitmq_password="secret",
        state_db=Path("adapter_data/boss.sqlite3"),
        credential_db=Path("adapter_data/credentials.sqlite3"),
        legacy_state_dbs=(source,),
    )

    assert migrate_legacy_state_database(config) is True
    assert config.state_db.exists()


def test_boss_cdp_login_reads_cookies_without_opening_another_page(monkeypatch):
    from message_adapter.platforms.boss import browser as boss_browser
    from message_adapter.platforms.boss.constants import WEB_BOSS_LOGIN_URL

    opened: list[str] = []

    async def instant_sleep(_seconds: float) -> None:
        return None

    async def cookies(_endpoint: str) -> dict[str, str]:
        return {"wt2": "fresh", "zp_at": "fresh", "__zp_stoken__": "token"}

    async def reveal(_endpoint: str) -> None:
        return None

    monkeypatch.setattr(boss_browser.asyncio, "sleep", instant_sleep)
    monkeypatch.setattr(boss_browser, "_read_zhipin_cookies", cookies)
    monkeypatch.setattr(boss_browser, "_reveal_login_qr", reveal)

    class FakeProfile:
        path = "profile"

        def clear(self) -> bool:
            return True

        @asynccontextmanager
        async def open_chrome(self, *, start_url: str):
            opened.append(start_url)
            yield "http://127.0.0.1:9"

        @asynccontextmanager
        async def launch_over_cdp(self, **_kwargs: object):
            raise AssertionError("login must not attach Playwright to the page")
            yield

    credential = asyncio.run(login_with_profile(FakeProfile(), timeout_s=30))

    assert opened == [WEB_BOSS_LOGIN_URL]
    assert credential.cookies == {"wt2": "fresh", "zp_at": "fresh", "__zp_stoken__": "token"}


def test_boss_login_clears_chrome_profile_before_scan(tmp_path):
    cleared = []

    class FakePage:
        url = "https://www.zhipin.com/web/user/?ka=header-login"

        async def goto(self, *args, **kwargs):
            return None

        async def wait_for_timeout(self, milliseconds):
            return None

    class FakeContext:
        pages = [FakePage()]

        async def clear_cookies(self):
            return None

        async def cookies(self):
            return [
                {"domain": ".zhipin.com", "name": "wt2", "value": "one"},
                {"domain": ".zhipin.com", "name": "zp_at", "value": "two"},
            ]

    class FakeProfile:
        path = tmp_path / "device"

        def clear(self):
            cleared.append("clear")
            return True

        @asynccontextmanager
        async def launch(self):
            assert cleared == ["clear"]
            yield FakeContext()

    asyncio.run(login_with_profile(FakeProfile(), timeout_s=30))
    assert cleared == ["clear"]


def test_boss_browser_login_returns_profile_association(tmp_path):
    class FakePage:
        url = "https://www.zhipin.com/web/user/?ka=header-login"

        async def goto(self, *args, **kwargs):
            return None

        async def wait_for_timeout(self, milliseconds):
            return None

        async def evaluate(self, *args, **kwargs):
            return None

    class FakeContext:
        pages = [FakePage()]

        async def clear_cookies(self):
            return None

        async def cookies(self):
            return [
                {"domain": ".zhipin.com", "name": "wt2", "value": "one"},
                {"domain": ".zhipin.com", "name": "zp_at", "value": "two"},
                {"domain": ".example.com", "name": "ignored", "value": "three"},
            ]

    profile_path = tmp_path / "profiles" / "boss" / "account-key"

    class FakeProfile:
        path = profile_path

        @asynccontextmanager
        async def launch(self):
            yield FakeContext()

    credential = asyncio.run(login_with_profile(FakeProfile(), timeout_s=30))

    assert credential.cookies == {"wt2": "one", "zp_at": "two"}
    assert credential.browser_profile == str(profile_path)


def test_boss_login_drops_stale_session_and_stays_on_login_page():
    from message_adapter.platforms.boss.constants import WEB_BOSS_CHAT_URL, WEB_BOSS_LOGIN_URL

    class FakePage:
        def __init__(self):
            self.url = WEB_BOSS_CHAT_URL
            self.visits: list[str] = []

        async def goto(self, url, *args, **kwargs):
            self.visits.append(url)
            self.url = url

        async def wait_for_timeout(self, milliseconds):
            return None

        async def evaluate(self, *args, **kwargs):
            return None

    class FakeContext:
        def __init__(self, page):
            self.pages = [page]
            self.cleared = 0

        async def clear_cookies(self):
            self.cleared += 1

        async def cookies(self):
            if self.cleared and any("/web/user/" in url for url in page.visits):
                return [
                    {"domain": ".zhipin.com", "name": "wt2", "value": "fresh"},
                    {"domain": ".zhipin.com", "name": "zp_at", "value": "fresh"},
                ]
            return [{"domain": ".zhipin.com", "name": "wt2", "value": "stale"}]

    page = FakePage()
    context = FakeContext(page)

    class FakeProfile:
        path = "profile"

        @asynccontextmanager
        async def launch(self):
            yield context

    credential = asyncio.run(login_with_profile(FakeProfile(), timeout_s=30))

    assert context.cleared >= 1
    assert page.visits == [WEB_BOSS_LOGIN_URL, WEB_BOSS_CHAT_URL]
    assert "about:blank" not in page.visits
    assert credential.cookies == {"wt2": "fresh", "zp_at": "fresh"}


def test_boss_login_replaces_blank_tab_with_login_page():
    from message_adapter.platforms.boss.constants import WEB_BOSS_CHAT_URL, WEB_BOSS_LOGIN_URL

    class FakePage:
        def __init__(self):
            self.url = "about:blank"
            self.visits: list[str] = []

        async def goto(self, url, *args, **kwargs):
            self.visits.append(url)
            self.url = url

        async def wait_for_timeout(self, milliseconds):
            return None

    class FakeContext:
        def __init__(self, page):
            self.pages = [page]
            self.cleared = 0

        async def clear_cookies(self):
            self.cleared += 1

        async def cookies(self):
            if self.cleared and WEB_BOSS_LOGIN_URL in page.visits:
                return [
                    {"domain": ".zhipin.com", "name": "wt2", "value": "fresh"},
                    {"domain": ".zhipin.com", "name": "zp_at", "value": "fresh"},
                ]
            return []

    page = FakePage()

    class FakeProfile:
        path = "profile"

        @asynccontextmanager
        async def launch(self):
            yield FakeContext(page)

    credential = asyncio.run(login_with_profile(FakeProfile(), timeout_s=30))

    assert page.visits == [WEB_BOSS_LOGIN_URL, WEB_BOSS_CHAT_URL]
    assert "about:blank" not in page.visits
    assert credential.cookies["wt2"] == "fresh"


def test_single_legacy_profile_moves_to_device_slot(tmp_path):
    root = tmp_path / "profiles"
    old = root / "boss" / "default-legacy"
    old.mkdir(parents=True)
    (old / "marker").write_text("ok")
    profile = BrowserProfile(root, "boss")

    assert migrate_legacy_browser_profile(profile) is True
    assert (profile.path / "marker").read_text() == "ok"
    assert not old.exists()


def test_profile_clear_removes_device_directory(tmp_path):
    profile = BrowserProfile(tmp_path / "profiles", "douyin")
    path = profile.prepare()
    (path / "Cookies").write_text("stale")

    assert profile.clear() is True
    assert not path.exists()
    assert profile.clear() is False


def test_logout_platform_deletes_credentials_and_chrome_profile(tmp_path, monkeypatch):
    from message_adapter.services.accounts import logout_platform

    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("DY_COOKIE", raising=False)
    config = AdapterConfig.load(platform="douyin", dotenv=str(tmp_path / "missing.env"))
    config.credential_db.parent.mkdir(parents=True, exist_ok=True)
    store = CredentialStore(config.credential_db)
    try:
        store.save(
            "douyin",
            {"cookie": {"cookie": "sessionid=abc", "sessionid": "abc"}},
            platform_actor_id="75604715923",
        )
    finally:
        store.close()
    profile = BrowserProfile(config.browser_profile_root, "douyin")
    (profile.prepare() / "Cookies").write_text("stale")

    assert logout_platform("douyin", config) is True

    store = CredentialStore(config.credential_db, read_only=True)
    try:
        assert store.get("douyin") is None
    finally:
        store.close()
    assert not profile.path.exists()


def test_boss_logout_deletes_credentials_and_chrome_profile(tmp_path, monkeypatch):
    from message_adapter.services.accounts import logout_platform

    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("BOSS_COOKIES", raising=False)
    config = AdapterConfig.load(platform="boss", dotenv=str(tmp_path / "missing.env"))
    config.credential_db.parent.mkdir(parents=True, exist_ok=True)
    store = CredentialStore(config.credential_db)
    try:
        store.save("boss", {"cookies": {"wt2": "stale", "zp_at": "stale"}}, platform_actor_id="1001")
    finally:
        store.close()
    profile = BrowserProfile(config.browser_profile_root, "boss")
    (profile.prepare() / "Cookies").write_text("stale")

    assert logout_platform("boss", config) is True

    store = CredentialStore(config.credential_db, read_only=True)
    try:
        assert store.get("boss") is None
    finally:
        store.close()
    assert not profile.path.exists()


def test_rednote_logout_clears_legacy_xiaohongshu_slot(tmp_path, monkeypatch):
    from message_adapter.services.accounts import logout_platform

    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("REDNOTE_COOKIE", raising=False)
    config = AdapterConfig.load(platform="rednote", dotenv=str(tmp_path / "missing.env"))
    config.credential_db.parent.mkdir(parents=True, exist_ok=True)
    store = CredentialStore(config.credential_db)
    try:
        store.save(
            "rednote",
            {"cookie": {"cookie": "web_session=new", "user_id": "uid-new"}},
            platform_actor_id="uid-new",
        )
        store.save(
            "xiaohongshu",
            {"cookie": {"cookie": "web_session=legacy", "user_id": "uid-legacy"}},
            platform_actor_id="uid-legacy",
        )
    finally:
        store.close()
    rednote_profile = BrowserProfile(config.browser_profile_root, "rednote")
    legacy_profile = BrowserProfile(config.browser_profile_root, "xiaohongshu")
    (rednote_profile.prepare() / "Cookies").write_text("stale-rednote")
    (legacy_profile.prepare() / "Cookies").write_text("stale-legacy")

    assert logout_platform("rednote", config) is True

    store = CredentialStore(config.credential_db, read_only=True)
    try:
        assert store.get("rednote") is None
        assert store.get("xiaohongshu") is None
    finally:
        store.close()
    assert not rednote_profile.path.exists()
    assert not legacy_profile.path.exists()


def test_purge_browser_credentials_preserves_state_binding_for_relogin(tmp_path, monkeypatch):
    from message_adapter.services.accounts import purge_browser_credentials
    from message_adapter.storage import SQLiteStore, inspect_actor_binding
    from message_adapter.core.models import Actor

    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("REDNOTE_COOKIE", raising=False)
    config = AdapterConfig.load(platform="rednote", dotenv=str(tmp_path / "missing.env"))
    config.credential_db.parent.mkdir(parents=True, exist_ok=True)
    store = CredentialStore(config.credential_db)
    try:
        store.save(
            "rednote",
            {"cookie": {"cookie": "web_session=old", "user_id": "uid-old"}},
            platform_actor_id="uid-old",
        )
    finally:
        store.close()
    state = SQLiteStore(config.state_db)
    try:
        state.save_actor(Actor(platform="rednote", platform_actor_id="uid-old", username="old", avatar=""))
    finally:
        state.close()
    assert inspect_actor_binding(config.state_db, "rednote") == "uid-old"

    assert purge_browser_credentials("rednote", config) is True
    assert inspect_actor_binding(config.state_db, "rednote") == "uid-old"


def test_rejected_scanned_uid_clears_profile_but_preserves_binding(tmp_path, monkeypatch):
    from message_adapter.core.models import Actor
    from message_adapter.services.accounts import _validate_scanned_uid
    from message_adapter.storage import SQLiteStore, inspect_actor_binding

    monkeypatch.chdir(tmp_path)
    config = AdapterConfig.load(platform="rednote", dotenv="missing.env")
    state = SQLiteStore(config.state_db)
    state.save_actor(Actor("rednote", "uid-old"))
    state.close()
    profile = BrowserProfile(config.browser_profile_root, "rednote")
    profile.prepare()
    (profile.path / "Cookies").write_text("new-account")

    with pytest.raises(RuntimeError, match="另一个平台 UID"):
        _validate_scanned_uid(config, profile, "uid-new")

    assert not profile.path.exists()
    assert inspect_actor_binding(config.state_db, "rednote") == "uid-old"
