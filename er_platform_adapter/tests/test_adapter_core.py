from __future__ import annotations

import json
import os
import sqlite3
import sys
import time
import uuid
from pathlib import Path
from types import ModuleType

from click.testing import CliRunner
import pytest

from message_adapter.cli import cli
from message_adapter.config import AdapterConfig
from message_adapter.core.models import (
    Actor,
    Audience,
    Conversation,
    Message,
    SendRequest,
    send_status_payload,
    status_event_id,
)
from message_adapter.platforms import create_platform_adapter
from message_adapter.process_lock import SingleInstanceLock
from message_adapter.storage import (
    CredentialStore,
    SQLiteStore,
    inspect_database,
    inspect_unowned_outbox_count,
)


def config(tmp_path, **overrides):
    values = {
        "platform": "boss",
        "rabbitmq_host": "rabbit.test",
        "rabbitmq_user": "adapter",
        "rabbitmq_password": "secret",
        "state_db": tmp_path / "state.sqlite3",
    }
    values.update(overrides)
    return AdapterConfig(**values)


def test_models_build_exact_rabbitmq_uplink_contract():
    actor = Actor("boss", "actor_with_under", "招聘者", "https://example.test/actor.jpg")
    audience = Audience("user_with_under", "候选人", "https://example.test/a.jpg", "后端")
    conversation = Conversation("boss", actor.platform_actor_id, audience, "platform-friend-1")
    message = Message("boss", "8801", conversation, "您好", 1_788_926_500_000)

    payload = message.mq_payload(actor, created_at_ms=1_788_926_500_123)
    uuid.UUID(payload["id"])
    uuid.UUID(payload["data"]["requestID"])
    assert payload == {
        "id": message.event_id,
        "func": "push_message_v2",
        "timestamp": 1_788_926_500_123,
        "platform": "boss",
        "is_task_message": True,
        "data": {
            "actorPlatformID": "actor_with_under",
            "audiencePlatformID": "user_with_under",
            "platform": "boss",
            "requestID": message.request_id,
            "audienceNickname": "候选人",
            "audienceFaceURL": "https://example.test/a.jpg",
            "sendTime": 1_788_926_500_000,
            "actorNickname": "招聘者",
            "actorFaceURL": "https://example.test/actor.jpg",
            "contentType": 101,
            "content": {"text": "您好"},
            "ex": "{}",
            "direction": 0,
        },
    }


def test_outgoing_manual_message_direction_contract():
    actor = Actor("douyin", "1001")
    conv = Conversation("douyin", "1001", Audience("2002"), "0:1:1001:2002")
    payload = Message("douyin", "mid", conv, "sent", 123, is_send=True).mq_payload(actor)
    assert payload["is_task_message"] is False
    assert payload["data"]["direction"] == 1


def test_send_request_parses_nested_json_string():
    req = SendRequest.from_mq_payload(
        {
            "platform": "douyin",
            "platform_actor_id": "1001",
            "platform_audience_id": "2002",
            "data": {
                "clientMsgID": "client-1",
                "content_type": 101,
                "content": json.dumps({"content": "reply"}),
            },
        }
    )
    assert req == SendRequest("douyin", "1001", "2002", "client-1", 101, "reply")


def test_send_request_accepts_legacy_client_msg_id():
    req = SendRequest.from_mq_payload(
        {
            "platform": "douyin",
            "platform_actor_id": "1001",
            "platform_audience_id": "2002",
            "data": {
                "client_msg_id": "legacy-1",
                "content_type": 101,
                "content": json.dumps({"content": "reply"}),
            },
        }
    )
    assert req.client_msg_id == "legacy-1"


def test_status_contract_is_full_and_stable():
    first = send_status_payload(
        platform="boss",
        client_msg_id="070170c51974100bdc4ffb4d2cdbe80a",
        status=0,
        actual_send_time=1788959679000,
    )
    second = send_status_payload(
        platform="boss",
        client_msg_id="070170c51974100bdc4ffb4d2cdbe80a",
        status=0,
        actual_send_time=1788959679000,
    )
    assert first == second
    assert first == {
        "clientMsgID": "070170c51974100bdc4ffb4d2cdbe80a",
        "status": 0,
        "actualSendTime": 1788959679000,
    }
    uuid.UUID(status_event_id(first))
    assert status_event_id(first) == status_event_id(second)


def test_config_loads_rabbitmq_and_builds_stable_actor_queue(tmp_path, monkeypatch):
    monkeypatch.setenv("RABBITMQ_HOST", "rabbit.test")
    monkeypatch.setenv("RABBITMQ_USER", "adapter")
    monkeypatch.setenv("RABBITMQ_PASSWORD", "secret")
    monkeypatch.chdir(tmp_path)
    loaded = AdapterConfig.load(platform="douyin")
    assert loaded.validate() == []
    assert loaded.send_status_success == 0
    assert loaded.send_status_failed == 1
    assert loaded.receive_queue_name("uid:1001") == loaded.receive_queue_name("uid:1001")
    assert loaded.receive_queue_name("uid:1001") != loaded.receive_queue_name("uid:1002")
    assert loaded.receive_queue_name("uid:1001").startswith("im2edge_messages.adapter.douyin.")


def test_config_loads_global_rate_limits_with_per_platform_overrides(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ADAPTER_SEND_MIN_INTERVAL_SECONDS", "3.5")
    monkeypatch.setenv("ADAPTER_SEND_JITTER_SECONDS", "2.5")
    monkeypatch.setenv("ADAPTER_SEND_MAX_PER_MINUTE", "7")
    monkeypatch.setenv("ADAPTER_SEND_MAX_PER_HOUR", "90")
    monkeypatch.setenv("BOSS_SEND_MIN_INTERVAL_SECONDS", "6")

    boss = AdapterConfig.load(platform="boss")
    douyin = AdapterConfig.load(platform="douyin")

    assert boss.send_min_interval_seconds == 6
    assert boss.send_jitter_seconds == 2.5
    assert boss.send_max_per_minute == 7
    assert boss.send_max_per_hour == 90
    assert douyin.send_min_interval_seconds == 3.5


def test_config_gate_rejects_missing_broker_and_ambiguous_status(tmp_path):
    invalid = config(
        tmp_path,
        rabbitmq_host="",
        rabbitmq_password="",
        send_status_success=1,
        send_status_failed=1,
    )
    errors = invalid.validate()
    assert any("RABBITMQ_HOST" in error for error in errors)
    assert any("RABBITMQ_PASSWORD" in error for error in errors)
    assert any(
        "SEND_STATUS_SUCCESS=0" in error and "SEND_STATUS_FAILED=1" in error
        for error in errors
    )

    reversed_contract = config(
        tmp_path,
        send_status_success=1,
        send_status_failed=0,
    )
    assert any(
        "SEND_STATUS_SUCCESS=0" in error and "SEND_STATUS_FAILED=1" in error
        for error in reversed_contract.validate()
    )


def test_config_gate_rejects_invalid_rate_limits(tmp_path):
    invalid = config(
        tmp_path,
        send_min_interval_seconds=-1,
        send_jitter_seconds=-1,
        send_max_per_minute=20,
        send_max_per_hour=10,
    )
    errors = invalid.validate()
    assert any("SEND_MIN_INTERVAL_SECONDS" in error for error in errors)
    assert any("SEND_JITTER_SECONDS" in error for error in errors)
    assert any("SEND_MAX_PER_HOUR" in error for error in errors)


def test_remote_http_gateway_requires_explicit_opt_in(tmp_path):
    protected = config(tmp_path, control_gateway_url="http://gateway.example.test:10030")
    assert any("ALLOW_INSECURE_HTTP" in error for error in protected.validate())

    allowed = config(
        tmp_path,
        control_gateway_url="http://gateway.example.test:10030",
        control_gateway_allow_insecure_http=True,
    )
    assert not any("ADAPTER_GATEWAY_URL" in error for error in allowed.validate())


def test_rednote_supports_text_like_the_other_message_platforms():
    adapter = create_platform_adapter("rednote")
    assert adapter.platform == "rednote"
    assert adapter.capabilities.text_receive is True
    assert adapter.capabilities.text_send is True
    assert adapter.capabilities.history_backfill is True


def test_adapter_cli_surface():
    result = CliRunner().invoke(cli, ["--help"])
    assert result.exit_code == 0
    assert all(command in result.output for command in ("run", "serve", "reset", "doctor", "backfill"))
    assert "--account" not in CliRunner().invoke(cli, ["run", "--help"]).output


def test_doctor_can_validate_local_config_without_platform(tmp_path, monkeypatch):
    for key in ("RABBITMQ_HOST", "RABBITMQ_USER", "RABBITMQ_PASSWORD"):
        monkeypatch.delenv(key, raising=False)
    result = CliRunner().invoke(
        cli,
        [
            "doctor",
            "--platform",
            "boss",
            "--skip-platform",
            "--dotenv",
            str(tmp_path / "missing.env"),
        ],
    )
    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["ok"] is False
    assert payload["data"]["platform_authenticated"] is None
    assert payload["data"]["send_rate_limit"] == {
        "min_interval_seconds": 4.0,
        "jitter_seconds": 4.0,
        "max_per_minute": 8,
        "max_per_hour": 120,
    }


def test_sqlite_outbox_confirm_and_restart(tmp_path):
    path = tmp_path / "state.sqlite3"
    payload = {"id": "event-1", "func": "push_message_v2"}
    store = SQLiteStore(path)
    assert store.enqueue(payload["id"], payload)
    store.mark_attempt(payload["id"], time.time() - 1)
    store.close()

    reopened = SQLiteStore(path)
    due = reopened.due_outbox()
    assert len(due) == 1 and due[0].attempts == 1
    assert reopened.mark_published(payload["id"])
    assert reopened.due_outbox() == []
    assert reopened.enqueue(payload["id"], payload) is False
    reopened.close()


def test_unknown_confirm_cannot_tombstone_a_future_event(tmp_path):
    store = SQLiteStore(tmp_path / "state.sqlite3")
    assert store.mark_published("future") is False
    assert store.enqueue("future", {"id": "future"}) is True
    store.close()


def test_downlink_result_and_status_outbox_are_one_transaction(tmp_path):
    store = SQLiteStore(tmp_path / "state.sqlite3")
    request = SendRequest("boss", "a", "u", "client-atomic", 101, "hello")
    assert store.put_downlink(request, {"data": {}})
    assert store.claim_due_downlink() is not None
    store._conn.execute(
        """CREATE TRIGGER reject_status BEFORE INSERT ON outbox
           BEGIN SELECT RAISE(ABORT, 'simulated crash'); END"""
    )
    event = send_status_payload(
        platform="boss",
        client_msg_id="client-atomic",
        status=0,
        actual_send_time=1,
    )
    with pytest.raises(sqlite3.IntegrityError, match="simulated crash"):
        store.finish_downlink("client-atomic", status=1, status_event=event)
    assert store.get_downlink("client-atomic").state == "claimed"
    assert store.due_outbox() == []
    store.close()


def test_sqlite_inbox_is_durable_and_claimed_once(tmp_path):
    path = tmp_path / "state.sqlite3"
    request = SendRequest("douyin", "actor", "audience", "c1", 101, "你好")
    store = SQLiteStore(path)
    assert store.put_downlink(request, {"platform": "douyin"})
    assert not store.put_downlink(request, {"platform": "douyin"})
    store.close()
    reopened = SQLiteStore(path)
    claimed = reopened.claim_due_downlink()
    assert claimed is not None and claimed.client_msg_id == "c1" and claimed.attempts == 1
    assert reopened.claim_due_downlink() is None
    reopened.close()


def test_outbound_rate_slots_are_durable_and_reused_after_restart(tmp_path):
    path = tmp_path / "state.sqlite3"
    store = SQLiteStore(path)
    first = SendRequest("boss", "actor", "audience", "rate-1", 101, "one")
    second = SendRequest("boss", "actor", "audience", "rate-2", 101, "two")
    assert store.put_downlink(first, {})
    assert store.claim_due_downlink(now=100) is not None
    assert store.reserve_downlink_send_slot(
        "rate-1",
        platform="boss",
        platform_actor_id="actor",
        now=100,
        spacing_seconds=5,
        max_per_minute=10,
        max_per_hour=100,
    ) == 100
    store.mark_downlink_sending("rate-1", now=100)
    assert store.put_downlink(second, {})
    assert store.claim_due_downlink(now=100) is not None
    scheduled = store.reserve_downlink_send_slot(
        "rate-2",
        platform="boss",
        platform_actor_id="actor",
        now=100,
        spacing_seconds=5,
        max_per_minute=10,
        max_per_hour=100,
    )
    assert scheduled == 105
    assert store.get_downlink("rate-2").state == "pending"
    store.close()

    reopened = SQLiteStore(path)
    assert reopened.claim_due_downlink(now=104.999) is None
    claimed = reopened.claim_due_downlink(now=105)
    assert claimed is not None and claimed.client_msg_id == "rate-2"
    assert reopened.reserve_downlink_send_slot(
        "rate-2",
        platform="boss",
        platform_actor_id="actor",
        now=105,
        spacing_seconds=999,
        max_per_minute=10,
        max_per_hour=100,
    ) == 105
    reopened.close()


def test_overdue_slots_are_rebased_from_actual_attempt_without_burst(tmp_path):
    store = SQLiteStore(tmp_path / "state.sqlite3")
    for index in range(3):
        client_id = f"overdue-{index}"
        request = SendRequest("boss", "actor", "audience", client_id, 101, "text")
        assert store.put_downlink(request, {})
        assert store.claim_due_downlink(now=100) is not None
        assert store.reserve_downlink_send_slot(
            client_id,
            platform="boss",
            platform_actor_id="actor",
            now=100,
            spacing_seconds=5,
            max_per_minute=20,
            max_per_hour=100,
        ) == 100 + index * 5

    store.mark_downlink_sending("overdue-0", now=108)
    second = store.claim_due_downlink(now=112)
    assert second is not None and second.client_msg_id == "overdue-1"
    second_at = store.reserve_downlink_send_slot(
        "overdue-1",
        platform="boss",
        platform_actor_id="actor",
        now=112,
        spacing_seconds=5,
        max_per_minute=20,
        max_per_hour=100,
    )
    third = store.claim_due_downlink(now=112)
    assert third is not None and third.client_msg_id == "overdue-2"
    third_at = store.reserve_downlink_send_slot(
        "overdue-2",
        platform="boss",
        platform_actor_id="actor",
        now=112,
        spacing_seconds=5,
        max_per_minute=20,
        max_per_hour=100,
    )

    assert second_at == 113
    assert third_at == 118
    assert store.get_downlink("overdue-1").state == "pending"
    assert store.get_downlink("overdue-2").state == "pending"
    store.close()


def test_outbound_rate_slots_enforce_rolling_minute_cap(tmp_path):
    store = SQLiteStore(tmp_path / "state.sqlite3")
    scheduled = []
    for index in range(3):
        client_id = f"minute-{index}"
        request = SendRequest("douyin", "actor", "audience", client_id, 101, "text")
        assert store.put_downlink(request, {})
        assert store.claim_due_downlink(now=100) is not None
        scheduled.append(
            store.reserve_downlink_send_slot(
                client_id,
                platform="douyin",
                platform_actor_id="actor",
                now=100,
                spacing_seconds=0,
                max_per_minute=2,
                max_per_hour=100,
            )
        )
    assert scheduled[:2] == [100, 100]
    assert scheduled[2] > 160
    store.close()


def test_outbound_rate_slots_enforce_rolling_hour_cap(tmp_path):
    store = SQLiteStore(tmp_path / "state.sqlite3")
    scheduled = []
    for index in range(4):
        client_id = f"hour-{index}"
        request = SendRequest("boss", "actor", "audience", client_id, 101, "text")
        assert store.put_downlink(request, {})
        assert store.claim_due_downlink(now=100) is not None
        scheduled.append(
            store.reserve_downlink_send_slot(
                client_id,
                platform="boss",
                platform_actor_id="actor",
                now=100,
                spacing_seconds=0,
                max_per_minute=100,
                max_per_hour=3,
            )
        )
    assert scheduled[:3] == [100, 100, 100]
    assert scheduled[3] > 3700
    store.close()


def test_claimed_downlink_recovers_but_started_send_does_not(tmp_path):
    store = SQLiteStore(tmp_path / "state.sqlite3")
    for client_id in ("not-started", "started"):
        request = SendRequest("boss", "actor", "audience", client_id, 101, "text")
        assert store.put_downlink(request, {})
        assert store.claim_due_downlink(now=100) is not None
        assert store.reserve_downlink_send_slot(
            client_id,
            platform="boss",
            platform_actor_id="actor",
            now=100,
            spacing_seconds=0,
            max_per_minute=10,
            max_per_hour=100,
        ) == 100
        if client_id == "started":
            store.mark_downlink_sending(client_id, now=100)

    assert store.recover_claimed_downlinks() == 1
    assert store.get_downlink("not-started").state == "pending"
    assert store.get_downlink("started").state == "processing"
    store.close()


def test_sqlite_conversation_lookup_uses_platform_audience_uid(tmp_path):
    store = SQLiteStore(tmp_path / "state.sqlite3")
    conv = Conversation("douyin", "actor_1", Audience("audience_2"), "0:1:actor_1:audience_2", {"short": 9})
    store.save_conversation(conv)
    found = store.resolve_conversation("douyin", "actor_1", "audience_2")
    assert found is not None
    assert found.platform_conversation_id == "0:1:actor_1:audience_2"
    assert found.platform_data == {"short": 9}
    store.close()


def test_sqlite_echo_is_one_shot(tmp_path):
    store = SQLiteStore(tmp_path / "state.sqlite3")
    args = {
        "platform": "boss",
        "platform_actor_id": "1",
        "platform_conversation_id": "2",
        "platform_message_id": "mid",
        "fingerprint": "fp",
    }
    store.add_echo(**args)
    assert store.consume_echo(**args)
    assert not store.consume_echo(**args)
    store.close()


def test_sqlite_echo_matches_fingerprint_across_conversation_id(tmp_path):
    store = SQLiteStore(tmp_path / "state.sqlite3")
    store.add_echo(
        platform="douyin",
        platform_actor_id="actor",
        platform_conversation_id="0:1:actor:peer",
        platform_message_id="",
        fingerprint="same-text-fp",
        ttl_seconds=120.0,
    )
    assert store.consume_echo(
        platform="douyin",
        platform_actor_id="actor",
        platform_conversation_id="0:1:actor:peer-updated",
        platform_message_id="",
        fingerprint="same-text-fp",
    )
    store.close()


def test_sqlite_bootstrap_cursor_is_monotonic(tmp_path):
    store = SQLiteStore(tmp_path / "state.sqlite3")
    store.set_bootstrap("boss", "200")
    store.set_bootstrap("boss", "100")
    assert store.get_bootstrap("boss") == (True, "200")
    store.close()


def test_sqlite_doctor_inspection_is_read_only(tmp_path):
    path = tmp_path / "nested" / "state.sqlite3"
    before = inspect_database(path)
    assert before["exists"] is False and before["creatable"] is True
    assert not path.parent.exists()
    store = SQLiteStore(path)
    store.close()
    after = inspect_database(path)
    assert after["schema_version"] == 6
    assert after["journal_mode"] == "wal"
    assert after["integrity"] == "ok"


def test_actor_scoped_outbox_and_downlink_never_cross_accounts(tmp_path):
    store = SQLiteStore(tmp_path / "state.sqlite3")
    store.enqueue("old-event", {"id": "old-event"}, platform="boss", platform_actor_id="old")
    store.enqueue("new-event", {"id": "new-event"}, platform="boss", platform_actor_id="new")
    store.put_downlink(SendRequest("boss", "old", "u1", "old-client", 101, "old"), {})
    store.put_downlink(SendRequest("boss", "new", "u2", "new-client", 101, "new"), {})

    assert [item.event_id for item in store.due_outbox(platform="boss", platform_actor_id="new")] == [
        "new-event"
    ]
    claimed = store.claim_due_downlink(platform="boss", platform_actor_id="new")
    assert claimed is not None and claimed.client_msg_id == "new-client"
    assert store.get_downlink("old-client").state == "pending"
    store.close()


def test_v5_outbox_migration_backfills_actor_and_blocks_unknown_rows(tmp_path):
    path = tmp_path / "state.sqlite3"
    store = SQLiteStore(path)
    store.enqueue(
        "known",
        {
            "id": "known",
            "platform": "boss",
            "data": {"actorPlatformID": "actor-1"},
        },
    )
    store.enqueue("unknown", {"id": "unknown"})
    store.close()
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        ALTER TABLE outbox RENAME TO outbox_v6;
        CREATE TABLE outbox (
            event_id TEXT PRIMARY KEY,
            payload TEXT NOT NULL,
            attempts INTEGER NOT NULL DEFAULT 0,
            next_attempt_at REAL NOT NULL DEFAULT 0,
            created_at REAL NOT NULL,
            last_error TEXT NOT NULL DEFAULT ''
        );
        INSERT INTO outbox(event_id, payload, attempts, next_attempt_at, created_at, last_error)
            SELECT event_id, payload, attempts, next_attempt_at, created_at, last_error FROM outbox_v6;
        DROP TABLE outbox_v6;
        PRAGMA user_version=5;
        """
    )
    connection.close()

    migrated = SQLiteStore(path)
    assert [
        item.event_id
        for item in migrated.due_outbox(platform="boss", platform_actor_id="actor-1")
    ] == ["known"]
    assert inspect_unowned_outbox_count(path) == 1
    migrated.close()


def test_sqlite_credential_files_are_private(tmp_path):
    path = tmp_path / "credentials.sqlite3"
    store = CredentialStore(path)
    store.save("boss", {"cookies": {"wt2": "redacted"}})
    if os.name == "posix":
        assert os.stat(path).st_mode & 0o777 == 0o600
        for suffix in ("-wal", "-shm"):
            candidate = Path(f"{path}{suffix}")
            if candidate.exists():
                assert os.stat(candidate).st_mode & 0o777 == 0o600
    store.close()


def test_read_only_credential_store_does_not_create_a_database(tmp_path):
    path = tmp_path / "missing" / "credentials.sqlite3"
    store = CredentialStore(path, read_only=True)
    assert store.get("boss") is None
    assert store.list_legacy_accounts("douyin") == []
    assert not path.exists()
    with pytest.raises(PermissionError, match="read-only"):
        store.save("boss", {})
    store.close()


def test_single_instance_lock_rejects_second_owner(tmp_path):
    path = tmp_path / "actor.lock"
    path.write_text("stale-pid", encoding="utf-8")
    with SingleInstanceLock(path):
        assert path.read_text(encoding="utf-8") == str(os.getpid())
        second = SingleInstanceLock(path)
        with pytest.raises(RuntimeError, match="already running"):
            with second:
                pass
        assert second._file is None

    with SingleInstanceLock(path):
        assert path.read_text(encoding="utf-8") == str(os.getpid())


def test_single_instance_lock_uses_windows_byte_lock(tmp_path, monkeypatch):
    from message_adapter import process_lock

    calls = []
    fake_msvcrt = ModuleType("msvcrt")
    fake_msvcrt.LK_NBLCK = 1
    fake_msvcrt.LK_UNLCK = 2

    def locking(fd, mode, length):
        calls.append((fd, mode, length))

    fake_msvcrt.locking = locking
    monkeypatch.setitem(sys.modules, "msvcrt", fake_msvcrt)
    monkeypatch.setattr(process_lock, "_IS_WINDOWS", True)
    path = tmp_path / "windows.lock"

    with process_lock.SingleInstanceLock(path):
        assert path.read_text(encoding="utf-8") == str(os.getpid())
        assert calls[-1][1:] == (fake_msvcrt.LK_NBLCK, 1)

    assert calls[-1][1:] == (fake_msvcrt.LK_UNLCK, 1)


def test_single_instance_lock_reports_unavailable_backend(tmp_path, monkeypatch):
    from message_adapter import process_lock

    monkeypatch.setattr(process_lock, "_IS_WINDOWS", False)
    monkeypatch.setitem(sys.modules, "fcntl", None)
    lock = process_lock.SingleInstanceLock(tmp_path / "unsupported.lock")

    with pytest.raises(RuntimeError, match="file locking is unavailable"):
        with lock:
            pass

    assert lock._file is None


def test_credential_update_preserves_other_sections(tmp_path):
    store = CredentialStore(tmp_path / "credentials.sqlite3")
    store.save("douyin", {"cookie": {"uid": "1"}}, platform_actor_id="1")
    store.update("douyin", {"im": {"ticket": "redacted"}})
    assert store.get("douyin") == {
        "cookie": {"uid": "1"},
        "im": {"ticket": "redacted"},
    }
    store.close()


def test_state_uid_cannot_be_changed_by_nickname_update(tmp_path):
    store = SQLiteStore(tmp_path / "state.sqlite3")
    store.save_actor(Actor("boss", "1001", "First name"))
    store.save_actor(Actor("boss", "1001", "Renamed"))
    assert store.get_bound_actor_id("boss") == "1001"
    with pytest.raises(RuntimeError, match="authenticated UID=2002"):
        store.save_actor(Actor("boss", "2002", "Renamed"))
    assert store.get_bound_actor_id("boss") == "1001"
    store.close()
