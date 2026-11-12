from __future__ import annotations

import asyncio
import io
import os
import sqlite3
import threading
import zipfile
from importlib import resources

import pytest

from message_adapter.async_tools import run_in_daemon_thread
from message_adapter.browser_profiles import BrowserProfile
from message_adapter.config import AdapterConfig
from message_adapter.core.models import Actor
from message_adapter.gateway.control import CONTROL_CREDENTIAL_SLOT, ControlGatewayError
from message_adapter.process_lock import SingleInstanceLock
from message_adapter.services import LocalAdapterService
from message_adapter.services.local import WECOM_DOC_NAME, HttpRequest, _safe_error
from message_adapter.services.reset import archive_platform_state
from message_adapter.storage import CredentialStore, SQLiteStore
from message_adapter.workspaces import WorkspaceRegistry


def make_config(tmp_path, platform="boss"):
    return AdapterConfig(
        platform=platform,
        rabbitmq_host="rabbit.test",
        rabbitmq_user="adapter",
        rabbitmq_password="secret",
        state_db=tmp_path / f"{platform}.sqlite3",
        credential_db=tmp_path / "credentials.sqlite3",
        browser_profile_root=tmp_path / "profiles",
    )


def seed_workspace(tmp_path, activation_code="local-code"):
    registry = WorkspaceRegistry(tmp_path / "adapter_data")
    workspace = registry.create(activation_code)
    registry.set_active(workspace.workspace_id)
    registry.close()
    return workspace


def test_health_ready_supports_partial_availability(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    seed_workspace(tmp_path)
    service = LocalAdapterService(dotenv="missing.env")
    code, payload = service.ready_payload()
    assert code == 503 and payload["status"] == "unavailable"

    service.workers["boss"].status.state = "ready"
    code, payload = service.ready_payload()
    assert code == 200 and payload["status"] == "partial"

    service.workers["douyin"].status.state = "ready"
    code, payload = service.ready_payload()
    assert code == 200 and payload["status"] == "partial"

    service.workers["rednote"].status.state = "ready"
    code, payload = service.ready_payload()
    assert code == 200 and payload["status"] == "ready"
    assert "password" not in str(payload).lower()
    assert service.live_payload()["version"]
    assert service.live_payload()["name"] == "轻回桌面连接器"


def test_cancelling_platform_io_does_not_wait_for_blocking_thread():
    async def scenario():
        blocker = threading.Event()
        task = asyncio.create_task(run_in_daemon_thread(blocker.wait, 30))
        await asyncio.sleep(0.01)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        blocker.set()

    asyncio.run(scenario())


def test_health_rejects_non_loopback_binding():
    with pytest.raises(ValueError, match="loopback"):
        LocalAdapterService(dotenv=".env", health_host="0.0.0.0")


def test_worker_errors_redact_connection_credentials():
    error = RuntimeError("failed amqp://admin:secret@rabbit/ws?token=top-secret&access_key=also-secret")
    rendered = _safe_error(error)
    assert "secret" not in rendered


def test_health_http_server_stays_available_when_workers_are_down(tmp_path):
    async def scenario():
        service = LocalAdapterService(dotenv=str(tmp_path / "missing.env"), health_port=0)
        reader = asyncio.StreamReader()
        reader.feed_data(b"GET /health/ready HTTP/1.1\r\nHost: localhost\r\n\r\n")
        reader.feed_eof()

        class Writer:
            def __init__(self):
                self.buffer = bytearray()

            def write(self, data):
                self.buffer.extend(data)

            async def drain(self):
                return None

            def close(self):
                return None

            async def wait_closed(self):
                return None

        writer = Writer()
        await service._handle_http(reader, writer)
        response = bytes(writer.buffer)
        assert response.startswith(b"HTTP/1.1 503 Service Unavailable")
        assert b'"status":"unavailable"' in response

    asyncio.run(scenario())


def test_control_page_exposes_state_but_protects_mutations(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    async def scenario():
        service = LocalAdapterService(dotenv=str(tmp_path / "missing.env"))

        page = await service.dispatch(HttpRequest("GET", "/", {}))
        state = await service.dispatch(HttpRequest("GET", "/api/state", {}))
        forbidden = await service.dispatch(
            HttpRequest("POST", "/api/platforms/boss/login", {}, b"{}")
        )

        assert page.status == 200
        assert "轻回桌面连接器".encode() in page.body
        assert b"activation-code" in page.body
        assert b"local-account-reset" in page.body
        assert b'type="text"' in page.body
        assert b'type="password"' not in page.body
        assert state.status == 200
        assert forbidden.status == 403

    asyncio.run(scenario())


def test_control_page_downloads_authorized_diagnostic_bundle(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    async def scenario():
        service = LocalAdapterService(dotenv=str(tmp_path / "missing.env"))
        response = await service.dispatch(
            HttpRequest(
                "POST",
                "/api/diagnostics/download",
                {"x-adapter-control": service._control_token},
                b"{}",
            )
        )
        assert response.status == 200
        assert response.content_type == "application/zip"
        with zipfile.ZipFile(io.BytesIO(response.body)) as archive:
            assert "diagnostics.json" in archive.namelist()

    asyncio.run(scenario())


def test_authorized_shutdown_requests_clean_service_stop(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    async def scenario():
        service = LocalAdapterService(dotenv=str(tmp_path / "missing.env"))
        response = await service.dispatch(
            HttpRequest(
                "POST",
                "/api/shutdown",
                {"x-adapter-control": service._control_token},
                b"{}",
            )
        )
        assert response.status == 200
        await asyncio.sleep(0.11)
        assert service.stop_event.is_set()

    asyncio.run(scenario())


def test_one_platform_can_login_without_the_other(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    seed_workspace(tmp_path)
    login_finished = asyncio.Event()

    async def fake_login(platform, config, on_status):
        assert platform == "douyin"
        assert config.platform == "douyin"
        on_status("请扫码")
        login_finished.set()
        return {"platform_actor_id": "douyin-1001", "nickname": "测试用户"}

    async def scenario():
        service = LocalAdapterService(
            dotenv=str(tmp_path / "missing.env"),
            login_handler=fake_login,
        )
        worker_task = asyncio.create_task(service.workers["douyin"].run(service.stop_event))
        try:
            for _ in range(100):
                if service.workers["douyin"]._owner_lock_held:
                    break
                await asyncio.sleep(0.01)
            assert service.workers["douyin"]._owner_lock_held
            assert await service.start_login("douyin") is True
            await login_finished.wait()
            await service._login_tasks["douyin"]

            assert service.login_states["douyin"].state == "success"
            assert service.login_states["douyin"].platform_actor_id == "douyin-1001"
            assert service.login_states["boss"].state == "idle"
        finally:
            service.stop_event.set()
            await worker_task

    asyncio.run(scenario())


def test_local_account_syncs_platforms_without_controlling_local_login(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    received: dict[str, object] = {}

    async def register(code, accounts):
        received.update(code=code, accounts=accounts)
        return {"actor_id": "im-actor-1"}

    async def scenario():
        service = LocalAdapterService(
            dotenv=str(tmp_path / "missing.env"),
            registration_handler=register,
        )
        workspace, created = await service.login_local_account("local-secret-code", create=True)
        assert created is True
        assert workspace.activation_code == "local-secret-code"
        credentials = CredentialStore(workspace.root / "credentials.sqlite3")
        credentials.save("douyin", {"nickname": "测试用户"}, platform_actor_id="douyin-1001")
        credentials.close()
        response = await service.sync_upstream()

        assert response.status == 200
        assert b"local-secret-code" not in response.body
        assert received == {
            "code": "local-secret-code",
            "accounts": [
                {
                    "platform": "douyin",
                    "platform_actor_id": "douyin-1001",
                    "nickname": "测试用户",
                    "avatar_url": "",
                    "profile": {},
                }
            ],
        }
        await service._stop_workers()
        service.workers["douyin"]._transition("starting")
        state = await service.control_payload()
        assert state["local_account"]["activation_code"] == "local-secret-code"
        assert state["upstream_sync"]["state"] == "synced"
        assert state["platforms"]["douyin"]["registered"] is True
        assert state["platforms"]["douyin"]["online"] is False
        service.workers["douyin"]._transition("ready")
        ready = await service.control_payload()
        assert ready["platforms"]["douyin"]["online"] is True
        assert ready["platforms"]["boss"]["online"] is False

    asyncio.run(scenario())


def test_rejected_sync_clears_the_previous_registration(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    async def register(code, accounts):
        return {
            "accounts": [
                {
                    "platform": item["platform"],
                    "platform_actor_id": item["platform_actor_id"],
                }
                for item in accounts
            ]
        }

    async def reject(code, accounts):
        raise ControlGatewayError(
            "控制服务请求失败: im_rejected operation=ActorAddAccount grpc_code=FAILED_PRECONDITION",
            retryable=False,
        )

    async def scenario():
        service = LocalAdapterService(
            dotenv=str(tmp_path / "missing.env"),
            registration_handler=register,
        )
        workspace, _ = await service.login_local_account("local-secret-code", create=True)
        credentials = CredentialStore(workspace.root / "credentials.sqlite3")
        credentials.save("douyin", {"nickname": "测试用户"}, platform_actor_id="douyin-1001")
        credentials.save(
            CONTROL_CREDENTIAL_SLOT,
            {
                "device_token": "dvc_previous",
                "accounts": [{"platform": "douyin", "platform_actor_id": "douyin-1001"}],
            },
        )
        credentials.close()
        assert (await service.sync_upstream()).status == 200
        service.workers["douyin"]._transition("ready")
        assert (await service.control_payload())["platforms"]["douyin"]["online"] is True

        service._registration_handler = reject
        response = await service.sync_upstream()
        state = await service.control_payload()

        assert response.status == 502
        assert state["upstream_sync"]["state"] == "error"
        assert state["upstream_sync"]["retryable"] is False
        assert state["upstream_sync"]["accounts"] == []
        assert state["platforms"]["douyin"]["registered"] is False
        assert state["platforms"]["douyin"]["online"] is False
        saved = CredentialStore(workspace.root / "credentials.sqlite3", read_only=True)
        try:
            assert saved.get(CONTROL_CREDENTIAL_SLOT)["accounts"] == []
        finally:
            saved.close()

        restarted = LocalAdapterService(dotenv=str(tmp_path / "missing.env"))
        restored = await restarted.control_payload()
        assert restored["upstream_sync"]["state"] != "synced"
        assert restored["platforms"]["douyin"]["registered"] is False
        assert restored["platforms"]["douyin"]["online"] is False

    asyncio.run(scenario())


def test_retryable_sync_failure_hides_online_until_it_recovers(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    async def register(code, accounts):
        return {"accounts": accounts}

    async def scenario():
        service = LocalAdapterService(
            dotenv=str(tmp_path / "missing.env"),
            registration_handler=register,
        )
        workspace, _ = await service.login_local_account("local-secret-code", create=True)
        credentials = CredentialStore(workspace.root / "credentials.sqlite3")
        credentials.save("douyin", {"nickname": "测试用户"}, platform_actor_id="douyin-1001")
        credentials.close()
        assert (await service.sync_upstream()).status == 200
        service.workers["douyin"]._transition("ready")
        assert (await service.control_payload())["platforms"]["douyin"]["online"] is True

        async def blip(code, accounts):
            raise ConnectionError("gateway is offline")

        service._registration_handler = blip
        response = await service.sync_upstream()
        state = await service.control_payload()
        assert response.status == 502
        assert state["upstream_sync"]["retryable"] is True
        assert state["platforms"]["douyin"]["registered"] is True
        assert state["platforms"]["douyin"]["online"] is False

        service._registration_handler = register
        assert (await service.sync_upstream()).status == 200
        assert (await service.control_payload())["platforms"]["douyin"]["online"] is True

    asyncio.run(scenario())


def test_active_local_account_is_restored_after_restart(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    workspace = seed_workspace(tmp_path, "saved-activation-code")

    async def scenario():
        service = LocalAdapterService(dotenv=str(tmp_path / "missing.env"))
        state = await service.control_payload()
        assert state["local_account"]["logged_in"] is True
        assert state["local_account"]["activation_code"] == "saved-activation-code"
        assert state["local_account"]["workspace_id"] == workspace.workspace_id

        await service.logout_local_account()
        restarted = LocalAdapterService(dotenv=str(tmp_path / "missing.env"))
        after = await restarted.control_payload()
        assert after["local_account"]["logged_in"] is False

    asyncio.run(scenario())


def test_reset_archives_state_credential_and_profile(tmp_path):
    config = make_config(tmp_path)
    state = SQLiteStore(config.state_db)
    state.save_actor(Actor("boss", "1001", "Display Name"))
    state.close()
    credentials = CredentialStore(config.credential_db)
    credentials.save("boss", {"cookies": {"wt2": "secret"}}, platform_actor_id="1001")
    credentials.close()
    profile = BrowserProfile(config.browser_profile_root, "boss")
    profile.prepare()
    (profile.path / "marker").write_text("profile")

    archive = archive_platform_state(config, "1001")

    assert archive.is_dir()
    if os.name == "posix":
        assert os.stat(archive).st_mode & 0o777 == 0o700
    assert (archive / config.state_db.name).exists()
    assert (archive / "profile-device" / "marker").read_text() == "profile"
    archived_credentials = CredentialStore(archive / "credentials.sqlite3", read_only=True)
    assert archived_credentials.get_bound_actor_id("boss") == "1001"
    assert archived_credentials.get("boss")["cookies"]["wt2"] == "secret"
    archived_credentials.close()
    active_credentials = CredentialStore(config.credential_db, read_only=True)
    assert active_credentials.get("boss") is None
    active_credentials.close()
    assert not config.state_db.exists()
    assert not profile.path.exists()


def test_web_reset_archives_platform_and_clears_visible_uid(tmp_path, monkeypatch):
    async def scenario():
        monkeypatch.chdir(tmp_path)
        seed_workspace(tmp_path)
        config = AdapterConfig.load(platform="boss", dotenv="missing.env")
        state = SQLiteStore(config.state_db)
        state.save_actor(Actor("boss", "1001", "Display Name"))
        state.close()
        credentials = CredentialStore(config.credential_db)
        credentials.save("boss", {"cookies": {"wt2": "secret"}}, platform_actor_id="1001")
        credentials.close()
        service = LocalAdapterService(dotenv="missing.env")
        service.workers["boss"].status.platform_actor_id = "1001"
        service.workers["boss"]._owner_lock_held = True

        archive = await service.reset_platform("boss", "1001")

        assert os.path.isdir(archive)
        assert service.workers["boss"].status.platform_actor_id == ""
        assert service.login_states["boss"].message.startswith("旧账号已安全归档")

    asyncio.run(scenario())


def test_reset_rejects_wrong_uid_and_active_worker_lock(tmp_path):
    config = make_config(tmp_path)
    state = SQLiteStore(config.state_db)
    state.save_actor(Actor("boss", "1001"))
    state.close()

    with pytest.raises(RuntimeError, match="does not match"):
        archive_platform_state(config, "2002")
    assert config.state_db.exists()

    with SingleInstanceLock(config.owner_lock_path):
        with pytest.raises(RuntimeError, match="already running"):
            archive_platform_state(config, "1001")


def test_multiple_legacy_credential_slots_are_not_auto_selected(tmp_path):
    path = tmp_path / "credentials.sqlite3"
    connection = sqlite3.connect(path)
    connection.execute(
        "CREATE TABLE credentials(platform TEXT, account_key TEXT, payload TEXT, updated_at REAL, "
        "PRIMARY KEY(platform, account_key))"
    )
    connection.execute("INSERT INTO credentials VALUES ('douyin', 'one', '{}', 1)")
    connection.execute("INSERT INTO credentials VALUES ('douyin', 'two', '{}', 2)")
    connection.commit()
    connection.close()

    store = CredentialStore(path)
    assert store.legacy_account_count("douyin") == 2
    assert store.get("douyin") is None
    store.close()


def _convert_state_to_v3(path, rows):
    current = SQLiteStore(path)
    current.close()
    connection = sqlite3.connect(path)
    connection.execute("ALTER TABLE account_state RENAME TO account_state_v4")
    connection.execute(
        """CREATE TABLE account_state (
               platform TEXT NOT NULL,
               account_key TEXT NOT NULL,
               platform_actor_id TEXT NOT NULL DEFAULT '',
               actor_name TEXT NOT NULL DEFAULT '',
               actor_avatar TEXT NOT NULL DEFAULT '',
               cursor TEXT NOT NULL DEFAULT '',
               initialized INTEGER NOT NULL DEFAULT 0,
               updated_at REAL NOT NULL,
               PRIMARY KEY (platform, account_key)
           )"""
    )
    connection.executemany(
        "INSERT INTO account_state VALUES (?, ?, ?, '', '', '', 0, ?)", rows
    )
    connection.execute("DROP TABLE account_state_v4")
    connection.execute("PRAGMA user_version=3")
    connection.commit()
    connection.close()


def test_single_v3_state_slot_migrates_to_platform_primary_key(tmp_path):
    path = tmp_path / "boss.sqlite3"
    _convert_state_to_v3(path, [("boss", "old-name", "1001", 1.0)])

    store = SQLiteStore(path)

    assert store.get_bound_actor_id("boss") == "1001"
    assert sqlite3.connect(path).execute("PRAGMA user_version").fetchone()[0] == 6
    store.close()


def test_multiple_v3_state_slots_are_refused_without_mutation(tmp_path):
    path = tmp_path / "boss.sqlite3"
    _convert_state_to_v3(
        path,
        [("boss", "one", "1001", 1.0), ("boss", "two", "2002", 2.0)],
    )

    with pytest.raises(RuntimeError, match="multiple account_key slots"):
        SQLiteStore(path)

    connection = sqlite3.connect(path)
    assert connection.execute("PRAGMA user_version").fetchone()[0] == 3
    assert connection.execute("SELECT COUNT(*) FROM account_state").fetchone()[0] == 2
    connection.close()


def test_v4_state_database_adds_persistent_rate_limit_schema(tmp_path):
    path = tmp_path / "boss.sqlite3"
    store = SQLiteStore(path)
    store.close()
    connection = sqlite3.connect(path)
    connection.execute("DROP TABLE outbound_rate_slots")
    connection.execute("PRAGMA user_version=4")
    connection.commit()
    connection.close()

    migrated = SQLiteStore(path)

    assert sqlite3.connect(path).execute("PRAGMA user_version").fetchone()[0] == 6
    assert migrated._conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='outbound_rate_slots'"
    ).fetchone()
    migrated.close()


def test_state_lists_wechat_and_wecom_beside_the_qr_platforms(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    async def scenario():
        service = LocalAdapterService(dotenv=str(tmp_path / "missing.env"))
        state = await service.control_payload()
        assert set(state["platforms"]) == {"boss", "douyin", "rednote", "wechat", "wecom"}
        assert state["platforms"]["wecom"]["online"] is False

    asyncio.run(scenario())


def test_wecom_login_reads_the_host_client_and_skips_qr(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    seed_workspace(tmp_path)

    def reject_qr(*args, **kwargs):
        raise AssertionError("host platforms must not open a QR login")

    def discover(platform):
        assert platform == "wecom"
        return {"platform_actor_id": "1688855621830548", "nickname": "教练"}

    monkeypatch.setattr("message_adapter.platforms.host_client.discover_host_account", discover)

    async def scenario():
        service = LocalAdapterService(dotenv=str(tmp_path / "missing.env"), login_handler=reject_qr)
        assert await service.start_login("wecom") is True
        await service._login_tasks["wecom"]
        state = await service.control_payload()
        wecom = state["platforms"]["wecom"]
        assert wecom["online"] is False
        assert wecom["platform_actor_id"] == "1688855621830548"
        assert wecom["login"]["state"] == "success"

    asyncio.run(scenario())


def test_host_docs_render_in_the_browser(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    wecom_original = resources.files("message_adapter.web").joinpath(WECOM_DOC_NAME).read_bytes()
    wechat_name = "小主机启动个人微信.docx"
    wechat_original = resources.files("message_adapter.web").joinpath(wechat_name).read_bytes()

    async def scenario():
        service = LocalAdapterService(dotenv=str(tmp_path / "missing.env"))
        wecom_file = await service.dispatch(HttpRequest("GET", "/docs/wecom.docx", {}))
        assert wecom_file.status == 200
        assert wecom_file.body == wecom_original
        wechat_file = await service.dispatch(HttpRequest("GET", "/docs/wechat.docx", {}))
        assert wechat_file.status == 200
        assert wechat_file.body == wechat_original
        for platform, phrase in (("wechat", "按win+s搜索讲述人"), ("wecom", "企业微信低版本通杀")):
            page = await service.dispatch(HttpRequest("GET", f"/docs/{platform}", {}))
            assert page.status == 200
            assert page.content_type.startswith("text/html")
            html = page.body.decode("utf-8")
            assert phrase in html
            assert f"/docs/{platform}/media/image1.png" in html
            assert 'width="55' in html
            image = await service.dispatch(HttpRequest("GET", f"/docs/{platform}/media/image1.png", {}))
            assert image.status == 200
            assert image.body.startswith(b"\x89PNG")

    asyncio.run(scenario())
