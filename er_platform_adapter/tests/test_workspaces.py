from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import zipfile
import io

import pytest

from message_adapter.config import AdapterConfig
from message_adapter.services.local import HttpRequest, LocalAdapterService
from message_adapter.storage import CredentialStore
from message_adapter.workspaces import WorkspaceRegistry


def test_activation_codes_use_isolated_random_workspace_paths(tmp_path):
    registry = WorkspaceRegistry(tmp_path / "adapter_data")
    first = registry.create("activation-a")
    second = registry.create("activation-b")

    assert first.workspace_id != second.workspace_id
    assert first.device_id != second.device_id
    assert "activation-a" not in str(first.root)
    assert "activation-b" not in str(second.root)

    registry.set_active(first.workspace_id)
    assert registry.active().workspace_id == first.workspace_id
    registry.set_active(second.workspace_id)
    assert registry.active().workspace_id == second.workspace_id
    registry.close()

    if os.name == "posix":
        assert os.stat(tmp_path / "adapter_data" / "workspaces.sqlite3").st_mode & 0o777 == 0o600


def test_adapter_config_uses_active_workspace(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    registry = WorkspaceRegistry(tmp_path / "adapter_data")
    workspace = registry.create("activation-a")
    registry.set_active(workspace.workspace_id)
    registry.close()

    config = AdapterConfig.load(platform="douyin", dotenv="missing.env")

    assert config.state_db.resolve() == workspace.root / "douyin.sqlite3"
    assert config.credential_db.resolve() == workspace.root / "credentials.sqlite3"
    assert config.browser_profile_root.resolve() == workspace.root / "profiles"


def test_legacy_flat_data_is_claimed_by_first_workspace(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    data_root = tmp_path / "adapter_data"
    credentials = CredentialStore(data_root / "credentials.sqlite3")
    credentials.save("boss", {"cookie": "secret"}, platform_actor_id="boss-1")
    credentials.close()

    async def scenario():
        service = LocalAdapterService(dotenv="missing.env")
        workspace, created = await service.login_local_account("first-code", create=True)

        assert created is True
        assert not (data_root / "credentials.sqlite3").exists()
        moved = CredentialStore(workspace.root / "credentials.sqlite3", read_only=True)
        assert moved.get_bound_actor_id("boss") == "boss-1"
        moved.close()

    asyncio.run(scenario())


def test_legacy_activation_and_device_identity_are_migrated(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    data_root = tmp_path / "adapter_data"
    credentials = CredentialStore(data_root / "credentials.sqlite3")
    credentials.save(
        "control_gateway",
        {
            "activation_code": "legacy-code",
            "device_id": "legacy-device-id",
            "device_token": "old-token",
        },
    )
    credentials.close()

    service = LocalAdapterService(dotenv="missing.env")

    assert service.active_workspace is not None
    assert service.active_workspace.activation_code == "legacy-code"
    assert service.active_workspace.device_id == "legacy-device-id"
    assert (service.active_workspace.root / "credentials.sqlite3").exists()


def test_switching_workspaces_preserves_inactive_profile(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    async def scenario():
        service = LocalAdapterService(dotenv="missing.env")
        first, _ = await service.login_local_account("activation-a", create=True)
        marker = first.root / "profiles" / "douyin" / "device" / "marker.txt"
        marker.parent.mkdir(parents=True)
        marker.write_text("account-a", encoding="utf-8")

        second, _ = await service.login_local_account("activation-b", create=True)
        assert second.root != first.root
        assert not (second.root / "profiles" / "douyin" / "device" / "marker.txt").exists()
        assert marker.read_text(encoding="utf-8") == "account-a"

        restored, created = await service.login_local_account("activation-a")
        assert created is False
        assert restored.workspace_id == first.workspace_id
        assert marker.read_text(encoding="utf-8") == "account-a"

    asyncio.run(scenario())


def test_reset_archives_workspace_but_preserves_local_identity(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    async def scenario():
        service = LocalAdapterService(dotenv="missing.env")
        workspace, _ = await service.login_local_account("activation-a", create=True)
        old_device_id = workspace.device_id
        marker = workspace.root / "profiles" / "boss" / "device" / "marker.txt"
        marker.parent.mkdir(parents=True)
        marker.write_text("old-profile", encoding="utf-8")
        credentials = CredentialStore(workspace.root / "credentials.sqlite3")
        credentials.save("boss", {"nickname": "old-boss"}, platform_actor_id="boss-1001")
        credentials.close()

        archive = await service.reset_local_account("重置当前工作区")

        assert service.active_workspace is not None
        assert service.active_workspace.workspace_id == workspace.workspace_id
        assert service.active_workspace.device_id == old_device_id
        assert service.active_workspace.activation_code == "activation-a"
        assert not marker.exists()
        archived = Path(archive)
        assert (archived / "profiles" / "boss" / "device" / "marker.txt").read_text() == "old-profile"
        manifest = json.loads((archived / "manifest.json").read_text())
        assert manifest["workspace_id"] == workspace.workspace_id
        assert manifest["platform_actor_ids"] == {"boss": "boss-1001"}
        assert "activation-a" not in (archived / "manifest.json").read_text()
        empty_credentials = CredentialStore(
            service.active_workspace.root / "credentials.sqlite3",
            read_only=True,
        )
        assert empty_credentials.get("boss") is None
        empty_credentials.close()

    asyncio.run(scenario())


def test_workspace_reset_rolls_back_when_archive_manifest_cannot_be_written(tmp_path, monkeypatch):
    registry = WorkspaceRegistry(tmp_path / "adapter_data")
    workspace = registry.create("activation-a")
    marker = workspace.root / "marker.txt"
    marker.write_text("keep-me")
    original = Path.write_text

    def fail_manifest(self, *args, **kwargs):
        if self.name == "manifest.json":
            raise PermissionError("simulated Windows file failure")
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", fail_manifest)

    with pytest.raises(PermissionError, match="Windows file failure"):
        registry.archive_and_recreate(workspace)

    assert marker.read_text() == "keep-me"
    assert not list(registry.archive_root.glob(f"workspace-{workspace.workspace_id}-*"))
    registry.close()


def test_local_account_api_requires_confirmation_before_creating(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    async def scenario():
        service = LocalAdapterService(dotenv="missing.env")
        headers = {"x-adapter-control": service._control_token}
        unknown = await service.dispatch(
            HttpRequest(
                "POST",
                "/api/local-account/login",
                headers,
                json.dumps({"activation_code": "new-code"}).encode(),
            )
        )
        assert unknown.status == 409
        assert json.loads(unknown.body)["can_create"] is True

        created = await service.dispatch(
            HttpRequest(
                "POST",
                "/api/local-account/login",
                headers,
                json.dumps({"activation_code": "new-code", "create": True}).encode(),
            )
        )
        assert created.status == 200
        state = await service.control_payload()
        assert state["local_account"]["logged_in"] is True
        assert state["local_account"]["activation_code"] == "new-code"

    asyncio.run(scenario())


def test_environment_credentials_block_workspace_creation(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DY_COOKIE", "sessionid=global-cookie")

    async def scenario():
        service = LocalAdapterService(dotenv="missing.env")
        try:
            await service.login_local_account("activation-a", create=True)
        except RuntimeError as exc:
            assert "DY_COOKIE" in str(exc)
        else:
            raise AssertionError("global credentials must not be shared between workspaces")

    asyncio.run(scenario())


def test_diagnostics_only_include_the_active_workspace_logs(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    async def scenario():
        service = LocalAdapterService(dotenv="missing.env")
        first, _ = await service.login_local_account("activation-a", create=True)
        (first.root / "logs").mkdir(parents=True)
        (first.root / "logs" / "adapter.jsonl").write_text("workspace-a-secret-message")
        second, _ = await service.login_local_account("activation-b", create=True)
        (second.root / "logs").mkdir(parents=True)
        (second.root / "logs" / "adapter.jsonl").write_text("workspace-b-message")

        response = await service.dispatch(
            HttpRequest(
                "POST",
                "/api/diagnostics/download",
                {"x-adapter-control": service._control_token},
                b"{}",
            )
        )

        assert response.status == 200
        with zipfile.ZipFile(io.BytesIO(response.body)) as archive:
            combined = b"\n".join(archive.read(name) for name in archive.namelist())
        assert b"workspace-b-message" in combined
        assert b"workspace-a-secret-message" not in combined
        assert b"activation-b" not in combined

    asyncio.run(scenario())


def test_upstream_sync_always_sends_the_complete_workspace_account_set(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    calls = []

    async def register(code, accounts, device_id, data_root):
        calls.append((code, accounts, device_id, data_root))
        return {"accounts": accounts}

    async def scenario():
        service = LocalAdapterService(
            dotenv="missing.env",
            registration_handler=register,
        )
        workspace, _ = await service.login_local_account("activation-a", create=True)
        credentials = CredentialStore(workspace.root / "credentials.sqlite3")
        credentials.save("boss", {"nickname": "Boss"}, platform_actor_id="boss-1")
        credentials.close()
        await service.sync_upstream()

        credentials = CredentialStore(workspace.root / "credentials.sqlite3")
        credentials.save("douyin", {"nickname": "Douyin"}, platform_actor_id="douyin-2")
        credentials.close()
        await service.sync_upstream()

        assert len(calls) == 2
        assert {(item["platform"], item["platform_actor_id"]) for item in calls[-1][1]} == {
            ("boss", "boss-1"),
            ("douyin", "douyin-2"),
        }
        assert calls[-1][0] == "activation-a"
        assert calls[-1][2] == workspace.device_id
        assert calls[-1][3] == str(workspace.root)

    asyncio.run(scenario())


def test_upstream_failure_does_not_logout_the_local_workspace(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    async def register(*_args):
        raise ConnectionError("gateway is offline")

    async def scenario():
        service = LocalAdapterService(
            dotenv="missing.env",
            registration_handler=register,
        )
        workspace, _ = await service.login_local_account("activation-a", create=True)
        credentials = CredentialStore(workspace.root / "credentials.sqlite3")
        credentials.save("douyin", {"nickname": "Douyin"}, platform_actor_id="douyin-1")
        credentials.close()

        response = await service.sync_upstream()
        state = await service.control_payload()

        assert response.status == 502
        assert state["local_account"]["logged_in"] is True
        assert state["local_account"]["workspace_id"] == workspace.workspace_id
        assert state["upstream_sync"]["state"] == "error"
        assert state["upstream_sync"]["retryable"] is True

    asyncio.run(scenario())


def test_only_the_first_workspace_can_claim_flat_legacy_data(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    data_root = tmp_path / "adapter_data"
    registry = WorkspaceRegistry(data_root)
    first = registry.create("activation-a")
    registry.set_active(first.workspace_id)
    registry.close()
    legacy = CredentialStore(data_root / "credentials.sqlite3")
    legacy.save("boss", {"cookie": "legacy"}, platform_actor_id="boss-legacy")
    legacy.close()

    async def scenario():
        service = LocalAdapterService(dotenv="missing.env")
        second, _ = await service.login_local_account("activation-b", create=True)

        assert (data_root / "credentials.sqlite3").exists()
        credentials = CredentialStore(second.root / "credentials.sqlite3", read_only=True)
        assert credentials.get("boss") is None
        credentials.close()

    asyncio.run(scenario())
