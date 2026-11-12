from __future__ import annotations

import json
import logging
import sys
import zipfile
import io
from unittest.mock import patch

from click.testing import CliRunner

from message_adapter.cli import ActivityFormatter, cli
from message_adapter.observability import configure_logging, diagnostic_bundle
from message_adapter.workspaces import WorkspaceRegistry


def seed_workspace(tmp_path):
    registry = WorkspaceRegistry(tmp_path / "adapter_data")
    workspace = registry.create("test-code")
    registry.set_active(workspace.workspace_id)
    registry.close()


def test_activity_formatter_highlights_sender_and_content():
    record = logging.LogRecord("message_adapter.activity", logging.INFO, "", 0, "message", (), None)
    record.adapter_activity = {
        "platform": "douyin",
        "direction": "incoming",
        "sender_name": "拾捌",
        "sender_id": "52286300247",
        "content": "你好\n请问还在吗",
    }

    rendered = ActivityFormatter(use_color=True).format(record)

    assert "\033[1;96m" in rendered
    assert "\033[1;93m" in rendered
    assert "抖音 收到" in rendered
    assert "拾捌（UID 52286300247）" in rendered
    assert "你好 ↵ 请问还在吗" in rendered


def test_json_formatter_includes_exception_message():
    from message_adapter.cli import JsonFormatter

    record = logging.LogRecord("message_adapter.services.runtime", logging.ERROR, "", 0, "platform send failed", (), None)
    try:
        raise RuntimeError("create failed message='INVALID_REQUEST' err=4")
    except RuntimeError:
        record.exc_info = sys.exc_info()

    payload = json.loads(JsonFormatter().format(record))
    assert payload["message"] == "platform send failed"
    assert payload["error_type"] == "RuntimeError"
    assert "INVALID_REQUEST" in payload["error"]


def test_persistent_log_rotates_and_keeps_redacted_traceback(tmp_path):
    root = logging.getLogger()
    old_handlers = root.handlers[:]
    old_level = root.level
    try:
        path = configure_logging(False, log_dir=tmp_path / "logs")
        rotating = next(handler for handler in root.handlers if hasattr(handler, "backupCount"))
        assert rotating.maxBytes == 10 * 1024 * 1024
        assert rotating.backupCount == 5
        try:
            raise RuntimeError("password=do-not-log")
        except RuntimeError:
            logging.getLogger("test.adapter").exception("send failed client_msg_id=client-1")
        for handler in root.handlers:
            handler.flush()
        record = json.loads(path.read_text(encoding="utf-8").splitlines()[-1])
        assert record["error_type"] == "RuntimeError"
        assert "do-not-log" not in json.dumps(record)
        assert "traceback" in record
    finally:
        for handler in root.handlers:
            handler.close()
        root.handlers[:] = old_handlers
        root.setLevel(old_level)


def test_diagnostic_bundle_contains_no_activation_or_env_values(tmp_path):
    dotenv = tmp_path / ".env"
    dotenv.write_text("RABBITMQ_PASSWORD=secret-value\nADAPTER_GATEWAY_URL=https://example.test\n")
    data = diagnostic_bundle(
        state={"local_account": {"activation_code": "visible-code"}, "platforms": {}},
        dotenv=str(dotenv),
        log_dir=tmp_path / "logs",
    )
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        manifest = archive.read("diagnostics.json").decode("utf-8")
    assert "visible-code" not in manifest
    assert "secret-value" not in manifest
    assert "RABBITMQ_PASSWORD" in manifest


def test_activity_color_respects_force_and_no_color(monkeypatch):
    from message_adapter.cli import _activity_color_enabled

    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.delenv("FORCE_COLOR", raising=False)
    monkeypatch.delenv("CLICOLOR_FORCE", raising=False)
    monkeypatch.setattr(sys, "stderr", type("E", (), {"isatty": lambda self: False})())
    assert _activity_color_enabled() is False

    monkeypatch.setenv("NO_COLOR", "1")
    assert _activity_color_enabled() is False

    # FORCE_COLOR wins so non-TTY / agent shells can still highlight activity.
    monkeypatch.setenv("FORCE_COLOR", "1")
    assert _activity_color_enabled() is True



def test_root_cli_exposes_services_and_platform_tooling():
    result = CliRunner().invoke(cli, ["--help"])

    assert result.exit_code == 0
    for command in ("run", "serve", "reset", "doctor", "backfill", "mq-watch", "boss", "douyin"):
        assert command in result.output
    for removed in ("search", "recommend", "recruiter", "chat", "web"):
        assert removed not in result.output


def test_platform_clis_expose_the_same_minimal_commands():
    expected = {"login", "logout", "status", "conversations", "messages", "send"}
    removed = {"accounts", "set-cookie", "grab-ticket", "inbox", "reply", "dump", "web"}

    for platform in ("boss", "douyin"):
        command = cli.commands[platform]
        assert set(command.commands) == expected

        result = CliRunner().invoke(cli, [platform, "--help"])
        assert result.exit_code == 0
        for name in expected:
            assert name in result.output
        for name in removed:
            assert name not in result.output
        assert "--account" not in result.output


def test_platform_cli_requires_an_active_local_workspace(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    result = CliRunner().invoke(
        cli,
        ["boss", "--dotenv", str(tmp_path / "missing.env"), "status", "--json"],
    )

    assert result.exit_code == 1
    assert "登录本地激活码账号" in result.output


def test_status_reports_missing_boss_credentials(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    seed_workspace(tmp_path)
    with patch("message_adapter.platforms.boss.cli.get_credential", return_value=None):
        result = CliRunner().invoke(
            cli,
            ["boss", "--dotenv", str(tmp_path / "missing.env"), "status", "--json"],
        )

    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload == {
        "ok": False,
        "platform": "boss",
        "data": {
            "authenticated": False,
            "platform_actor_id": "",
            "send_ready": False,
            "reason": "credential_missing",
        },
    }


def test_douyin_backfill_is_refused_before_authentication(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    seed_workspace(tmp_path)

    result = CliRunner().invoke(
        cli,
        [
            "backfill",
            "--platform",
            "douyin",
            "--since",
            "2026-09-01T00:00:00+08:00",
            "--limit",
            "10",
            "--dry-run",
            "--dotenv",
            str(tmp_path / "missing.env"),
        ],
    )

    assert result.exit_code == 1
    assert "douyin history access is disabled" in result.output
