from __future__ import annotations

import asyncio
import json
import logging
import time

import pytest

from message_adapter.config import AdapterConfig
from message_adapter.core.models import (
    Actor,
    Audience,
    BootstrapState,
    Conversation,
    Message,
    SendResult,
    status_event_id,
)
from message_adapter.core.platform import PlatformAdapter, PlatformCapabilities
from message_adapter.services.runtime import AdapterRuntime
from message_adapter.storage import SQLiteStore


class FakeAdapter(PlatformAdapter):
    platform = "boss"

    def __init__(self):
        self.actor = Actor("boss", "actor_1", "Actor")
        self.sent: list[tuple[Conversation, str]] = []
        self.resolved: Conversation | None = None

    async def authenticate(self):
        return self.actor

    async def bootstrap(self):
        return BootstrapState(cursor="0")

    async def stream_messages(self):
        if False:
            yield None

    async def catch_up(self, cursor):
        return []

    async def resolve_conversation(self, platform_audience_id):
        return self.resolved

    async def send_text(self, conversation, text):
        self.sent.append((conversation, text))
        return SendResult(True, int(time.time() * 1000), "platform-mid-1")

    async def close(self):
        return None


class StreamingAdapter(FakeAdapter):
    def __init__(self, messages, *, baseline_ids=frozenset(), catch_up=()):
        super().__init__()
        self.messages = list(messages)
        self.baseline_ids = frozenset(baseline_ids)
        self.catch_up_messages = list(catch_up)
        self.stream_started = asyncio.Event()
        self.release_stream = asyncio.Event()

    async def bootstrap(self):
        await self.stream_started.wait()
        self.release_stream.set()
        return BootstrapState(cursor="1000", baseline_message_ids=self.baseline_ids)

    async def stream_messages(self):
        self.stream_started.set()
        await self.release_stream.wait()
        for message in self.messages:
            yield message
        await asyncio.Event().wait()

    async def catch_up(self, cursor):
        assert cursor == "1000"
        return self.catch_up_messages


class StopAfterOutboxGateway:
    def __init__(self, store, count):
        self.store = store
        self.count = count

    async def run(self, actor, on_delivery, stop):
        for _ in range(200):
            if len(self.store.due_outbox()) >= self.count:
                stop.set()
                return
            await asyncio.sleep(0.005)
        raise AssertionError("runtime did not persist expected messages")


class SlowInitialGateway:
    def __init__(self):
        self.allow_ready = asyncio.Event()
        self.ready = asyncio.Event()
        self.timeout_seen = object()

    @property
    def is_ready(self):
        return self.ready.is_set()

    async def run(self, actor, on_delivery, stop):
        await self.allow_ready.wait()
        self.ready.set()
        await stop.wait()

    async def wait_ready(self, timeout=20.0):
        self.timeout_seen = timeout
        if timeout is None:
            await self.ready.wait()
            return
        await asyncio.wait_for(self.ready.wait(), timeout)


def make_config(tmp_path, **overrides):
    values = dict(
        platform="boss",
        rabbitmq_host="rabbit.test",
        rabbitmq_user="adapter",
        rabbitmq_password="secret",
        state_db=tmp_path / "state.sqlite3",
    )
    values.update(overrides)
    return AdapterConfig(**values)


def downlink(*, client_id="client-1", content_type=101, text="hello", actor="actor_1", platform="boss"):
    return {
        "platform": platform,
        "platform_actor_id": actor,
        "platform_audience_id": "audience_1",
        "data": {
            "clientMsgID": client_id,
            "content_type": content_type,
            "content": json.dumps({"content": text}),
        },
    }


def test_downlink_is_durable_idempotent_and_records_echo(tmp_path):
    async def scenario():
        store = SQLiteStore(tmp_path / "state.sqlite3")
        adapter = FakeAdapter()
        runtime = AdapterRuntime(make_config(tmp_path), adapter, store)
        runtime._actor = adapter.actor
        conv = Conversation("boss", "actor_1", Audience("audience_1", "User"), "friend-1")
        store.save_conversation(conv)
        payload = downlink()

        await runtime._accept_delivery(payload)
        record = store.claim_due_downlink()
        assert record is not None
        await runtime._process_downlink(record)
        await runtime._accept_delivery(payload)

        completed = store.get_downlink("client-1")
        assert completed is not None and completed.status == 0
        assert completed.status_event == {
            "clientMsgID": "client-1",
            "status": 0,
            "actualSendTime": completed.status_event["actualSendTime"],
        }
        assert len(adapter.sent) == 1
        event_id = status_event_id(completed.status_event)
        assert [item.event_id for item in store.due_outbox()] == [event_id]
        store.mark_published(event_id)
        echo = Message("boss", "platform-mid-1", conv, "hello", int(time.time() * 1000), True, "platform-mid-1")
        await runtime._accept_message(echo)
        assert store.due_outbox() == []
        store.close()

    asyncio.run(scenario())


def test_non_target_delivery_is_ignored(tmp_path):
    async def scenario():
        store = SQLiteStore(tmp_path / "state.sqlite3")
        adapter = FakeAdapter()
        runtime = AdapterRuntime(make_config(tmp_path), adapter, store)
        runtime._actor = adapter.actor
        await runtime._accept_delivery(downlink(platform="douyin"))
        await runtime._accept_delivery(downlink(actor="someone_else"))
        assert store.get_downlink("client-1") is None
        store.close()

    asyncio.run(scenario())


def test_unsupported_downlink_never_calls_platform(tmp_path):
    async def scenario():
        store = SQLiteStore(tmp_path / "state.sqlite3")
        adapter = FakeAdapter()
        runtime = AdapterRuntime(make_config(tmp_path), adapter, store)
        runtime._actor = adapter.actor
        await runtime._accept_delivery(downlink(client_id="image-1", content_type=102))
        record = store.claim_due_downlink()
        assert record is not None
        await runtime._process_downlink(record)
        completed = store.get_downlink("image-1")
        assert completed is not None and completed.status == 1
        assert completed.status_event["clientMsgID"] == "image-1"
        assert completed.status_event["status"] == 1
        assert adapter.sent == []
        store.close()

    asyncio.run(scenario())


def test_missing_mapping_is_resolved_by_stable_audience_uid(tmp_path):
    async def scenario():
        store = SQLiteStore(tmp_path / "state.sqlite3")
        adapter = FakeAdapter()
        adapter.resolved = Conversation(
            "boss",
            "actor_1",
            Audience("audience_1", "Resolved User"),
            "real-friend-id",
            {"encrypt_geek_id": "real-encrypted-id", "uid": "audience_1"},
        )
        runtime = AdapterRuntime(make_config(tmp_path), adapter, store)
        runtime._actor = adapter.actor
        await runtime._accept_delivery(downlink())
        record = store.claim_due_downlink()
        assert record is not None

        await runtime._process_downlink(record)

        assert adapter.sent[0][0].platform_conversation_id == "real-friend-id"
        assert store.resolve_conversation("boss", "actor_1", "audience_1") is not None
        store.close()

    asyncio.run(scenario())


def test_stored_boss_conversation_without_encrypt_id_is_refreshed_before_send(tmp_path):
    async def scenario():
        store = SQLiteStore(tmp_path / "state.sqlite3")
        adapter = FakeAdapter()
        adapter.resolved = Conversation(
            "boss",
            "actor_1",
            Audience("audience_1", "覃先生"),
            "503956637",
            {"encrypt_geek_id": "encrypt-from-detail", "uid": "audience_1", "friend_id": "503956637"},
        )
        runtime = AdapterRuntime(make_config(tmp_path), adapter, store)
        runtime._actor = adapter.actor
        store.save_conversation(
            Conversation(
                "boss",
                "actor_1",
                Audience("audience_1", "覃先生"),
                "503956637",
                {"encrypt_geek_id": "", "uid": "audience_1", "friend_id": "503956637"},
            )
        )
        await runtime._accept_delivery(downlink())
        record = store.claim_due_downlink()
        assert record is not None

        await runtime._process_downlink(record)

        assert adapter.sent[0][0].platform_data["encrypt_geek_id"] == "encrypt-from-detail"
        saved = store.resolve_conversation("boss", "actor_1", "audience_1")
        assert saved is not None
        assert saved.platform_data["encrypt_geek_id"] == "encrypt-from-detail"
        store.close()

    asyncio.run(scenario())


def test_im_burst_is_persisted_and_second_send_is_rate_limited(tmp_path):
    async def scenario():
        store = SQLiteStore(tmp_path / "state.sqlite3")
        adapter = FakeAdapter()
        runtime = AdapterRuntime(
            make_config(
                tmp_path,
                send_min_interval_seconds=30,
                send_jitter_seconds=0,
                send_max_per_minute=10,
                send_max_per_hour=100,
            ),
            adapter,
            store,
        )
        runtime._actor = adapter.actor
        store.save_conversation(
            Conversation("boss", "actor_1", Audience("audience_1", "User"), "friend-1")
        )
        await runtime._accept_delivery(downlink(client_id="burst-1", text="one"))
        await runtime._accept_delivery(downlink(client_id="burst-2", text="two"))

        first = store.claim_due_downlink()
        assert first is not None
        await runtime._process_downlink(first)
        second = store.claim_due_downlink()
        assert second is not None
        await runtime._process_downlink(second)

        assert [text for _, text in adapter.sent] == ["one"]
        queued = store.get_downlink("burst-2")
        assert queued is not None and queued.state == "pending"
        assert queued.attempts == 0
        assert queued.next_attempt_at > time.time() + 29
        store.close()

    asyncio.run(scenario())


def test_uid_mismatch_fails_before_gateway_or_outbox_recovery(tmp_path):
    class NeverGateway:
        ran = False

        async def run(self, actor, on_delivery, stop):
            self.ran = True

    async def scenario():
        store = SQLiteStore(tmp_path / "state.sqlite3")
        store.save_actor(Actor("boss", "old-uid"))
        adapter = FakeAdapter()
        adapter.actor = Actor("boss", "new-uid")
        gateway = NeverGateway()
        runtime = AdapterRuntime(make_config(tmp_path), adapter, store, gateway=gateway)

        with pytest.raises(RuntimeError, match="bound to platform_actor_id=old-uid"):
            await runtime.run()

        assert gateway.ran is False
        assert store.get_bound_actor_id("boss") == "old-uid"
        store.close()

    asyncio.run(scenario())


def test_slow_initial_rabbitmq_connection_does_not_restart_platform(tmp_path):
    class ConnectedAdapter(FakeAdapter):
        async def stream_messages(self):
            await asyncio.Event().wait()
            if False:
                yield None

    async def scenario():
        store = SQLiteStore(tmp_path / "state.sqlite3")
        adapter = ConnectedAdapter()
        gateway = SlowInitialGateway()
        runtime = AdapterRuntime(make_config(tmp_path), adapter, store, gateway=gateway)
        task = asyncio.create_task(runtime.run())

        for _ in range(100):
            if runtime.actor is not None and gateway.timeout_seen is None:
                break
            await asyncio.sleep(0.01)
        assert not task.done()
        assert gateway.timeout_seen is None
        assert not runtime.ready_event.is_set()

        gateway.allow_ready.set()
        await asyncio.wait_for(runtime.ready_event.wait(), 1)
        assert runtime.is_ready

        await runtime.stop()
        await asyncio.wait_for(task, 1)
        store.close()

    asyncio.run(scenario())


def test_friend_bootstrap_does_not_delay_rabbitmq_ready(tmp_path):
    class SlowBootstrap(FakeAdapter):
        def __init__(self):
            super().__init__()
            self.bootstrap_entered = asyncio.Event()
            self.release_bootstrap = asyncio.Event()

        async def stream_messages(self):
            await asyncio.Event().wait()
            if False:
                yield None

        async def bootstrap(self):
            self.bootstrap_entered.set()
            await self.release_bootstrap.wait()
            return BootstrapState(cursor="1")

    async def scenario():
        store = SQLiteStore(tmp_path / "state.sqlite3")
        adapter = SlowBootstrap()
        gateway = SlowInitialGateway()
        runtime = AdapterRuntime(make_config(tmp_path), adapter, store, gateway=gateway)
        task = asyncio.create_task(runtime.run())
        await asyncio.wait_for(adapter.bootstrap_entered.wait(), 1)
        assert not runtime.ready_event.is_set()

        gateway.allow_ready.set()
        await asyncio.wait_for(runtime.ready_event.wait(), 1)
        assert runtime.is_ready
        assert not adapter.release_bootstrap.is_set()

        adapter.release_bootstrap.set()
        await runtime.stop()
        await asyncio.wait_for(task, 1)
        store.close()

    asyncio.run(scenario())


def test_invalid_matching_request_with_client_id_gets_failure_status(tmp_path):
    async def scenario():
        store = SQLiteStore(tmp_path / "state.sqlite3")
        adapter = FakeAdapter()
        runtime = AdapterRuntime(make_config(tmp_path), adapter, store)
        runtime._actor = adapter.actor
        payload = downlink(client_id="bad-1")
        payload["data"]["content"] = "not-json"
        await runtime._accept_delivery(payload)
        completed = store.get_downlink("bad-1")
        assert completed is not None and completed.status == 1
        assert completed.status_event["clientMsgID"] == "bad-1"
        assert completed.status_event["status"] == 1
        assert len(store.due_outbox()) == 1
        store.close()

    asyncio.run(scenario())


def test_incoming_boss_message_does_not_auto_reply_or_exchange(tmp_path):
    async def scenario():
        store = SQLiteStore(tmp_path / "state.sqlite3")
        adapter = FakeAdapter()
        adapter.capabilities = PlatformCapabilities(wechat_exchange=True)
        adapter.opening_reply_lines = lambda: ("你好，是来找工作的吗？", "加个微信吧。")
        adapter.requests: list[tuple[str, str]] = []

        async def request_wechat_exchange(conversation):
            adapter.requests.append(("wechat", conversation.audience.platform_audience_id))

        async def request_phone_exchange(conversation):
            adapter.requests.append(("phone", conversation.audience.platform_audience_id))

        adapter.request_wechat_exchange = request_wechat_exchange
        adapter.request_phone_exchange = request_phone_exchange
        runtime = AdapterRuntime(make_config(tmp_path), adapter, store)
        runtime._actor = adapter.actor
        conversation = Conversation("boss", "actor_1", Audience("audience_1", "候选人甲"), "friend-1")
        await runtime._accept_message(Message("boss", "m1", conversation, "在的", 1700000000000))
        await runtime._accept_message(
            Message("boss", "m2", conversation, "对方请求与您交换微信", 1700000001000)
        )
        pending = list(runtime._side_tasks)
        if pending:
            await asyncio.wait_for(asyncio.gather(*pending), 1)
        assert adapter.sent == []
        assert adapter.requests == []
        store.close()

    asyncio.run(scenario())


def test_two_ai_replies_request_wechat_exchange_once(tmp_path):
    async def scenario():
        store = SQLiteStore(tmp_path / "state.sqlite3")
        adapter = FakeAdapter()
        adapter.capabilities = PlatformCapabilities(wechat_exchange=True)
        adapter.requests: list[tuple[str, str]] = []

        async def request_wechat_exchange(conversation):
            adapter.requests.append(("wechat", conversation.audience.platform_audience_id))

        async def request_phone_exchange(conversation):
            adapter.requests.append(("phone", conversation.audience.platform_audience_id))

        adapter.request_wechat_exchange = request_wechat_exchange
        adapter.request_phone_exchange = request_phone_exchange
        runtime = AdapterRuntime(
            make_config(tmp_path, send_min_interval_seconds=0, send_jitter_seconds=0),
            adapter,
            store,
        )
        runtime._actor = adapter.actor
        store.save_conversation(
            Conversation(
                "boss",
                "actor_1",
                Audience("audience_1", "候选人甲"),
                "friend-1",
                {"encrypt_geek_id": "enc"},
            )
        )

        await runtime._accept_delivery(downlink(client_id="ai-1", text="第一句"))
        first = store.claim_due_downlink()
        assert first is not None
        await runtime._process_downlink(first)
        pending = list(runtime._side_tasks)
        if pending:
            await asyncio.wait_for(asyncio.gather(*pending), 1)
        assert adapter.requests == []

        await runtime._accept_delivery(downlink(client_id="ai-2", text="第二句"))
        second = store.claim_due_downlink()
        assert second is not None
        await runtime._process_downlink(second)
        pending = list(runtime._side_tasks)
        if pending:
            await asyncio.wait_for(asyncio.gather(*pending), 1)
        assert [text for _, text in adapter.sent] == ["第一句", "第二句"]
        assert adapter.requests == [("wechat", "audience_1")]

        await runtime._accept_delivery(downlink(client_id="ai-3", text="第三句"))
        third = store.claim_due_downlink()
        assert third is not None
        await runtime._process_downlink(third)
        pending = list(runtime._side_tasks)
        if pending:
            await asyncio.wait_for(asyncio.gather(*pending), 1)
        assert adapter.requests == [("wechat", "audience_1")]
        store.close()

    asyncio.run(scenario())


def test_boss_exchange_prompt_does_not_send_opening_reply(tmp_path):
    async def scenario():
        store = SQLiteStore(tmp_path / "state.sqlite3")
        adapter = FakeAdapter()
        adapter.capabilities = PlatformCapabilities(wechat_exchange=True)
        adapter.opening_reply_lines = lambda: ("你好，是来找工作的吗？", "加个微信吧。")
        adapter.requests = []

        async def request_wechat_exchange(conversation):
            adapter.requests.append(conversation.audience.platform_audience_id)

        adapter.request_wechat_exchange = request_wechat_exchange
        runtime = AdapterRuntime(make_config(tmp_path), adapter, store)
        runtime._actor = adapter.actor
        conversation = Conversation("boss", "actor_1", Audience("audience_1", "候选人甲"), "friend-1")
        await runtime._accept_message(
            Message("boss", "m1", conversation, "对方请求与您交换微信", 1700000000000)
        )
        pending = list(runtime._side_tasks)
        if pending:
            await asyncio.wait_for(asyncio.gather(*pending), 1)
        assert adapter.sent == []
        assert adapter.requests == []
        store.close()

    asyncio.run(scenario())


def test_phone_send_is_uploaded_and_adapter_echo_is_not(tmp_path):
    """Messages typed on the phone go to MQ. Echoes of adapter sends do not."""

    async def scenario():
        store = SQLiteStore(tmp_path / "state.sqlite3")
        adapter = FakeAdapter()
        runtime = AdapterRuntime(make_config(tmp_path), adapter, store)
        runtime._actor = adapter.actor
        conv = Conversation("boss", "actor_1", Audience("audience_1"), "friend-1")
        message = Message("boss", "manual-1", conv, "manual", int(time.time() * 1000), True, "manual-1")
        await runtime._accept_message(message)
        queued = store.due_outbox()
        assert len(queued) == 1
        assert queued[0].payload["data"]["direction"] == 1
        assert queued[0].payload["data"]["content"] == {"text": "manual"}
        store.add_echo(
            platform="boss",
            platform_actor_id="actor_1",
            platform_conversation_id="friend-1",
            platform_message_id="platform-mid-1",
            fingerprint=Message("boss", "echo-1", conv, "hello", 1, True).echo_fingerprint(),
        )
        echo = Message("boss", "echo-1", conv, "hello", int(time.time() * 1000), True, "platform-mid-1")
        await runtime._accept_message(echo)
        assert [item.payload["data"]["content"] for item in store.due_outbox()] == [{"text": "manual"}]
        store.close()

    asyncio.run(scenario())


def test_inbound_message_emits_human_activity_record(tmp_path, caplog):
    async def scenario():
        store = SQLiteStore(tmp_path / "state.sqlite3")
        adapter = FakeAdapter()
        runtime = AdapterRuntime(make_config(tmp_path), adapter, store)
        runtime._actor = adapter.actor
        conversation = Conversation(
            "boss",
            "actor_1",
            Audience("audience_1", "候选人甲"),
            "friend-1",
        )
        message = Message("boss", "incoming-1", conversation, "你好，请问还招人吗？", 1700000000000)

        with caplog.at_level(logging.INFO, logger="message_adapter.activity"):
            await runtime._accept_message(message)

        activity = next(record.adapter_activity for record in caplog.records if hasattr(record, "adapter_activity"))
        assert activity == {
            "platform": "boss",
            "direction": "incoming",
            "sender_name": "候选人甲",
            "sender_id": "audience_1",
            "content": "你好，请问还招人吗？",
        }
        store.close()

    asyncio.run(scenario())


def test_first_start_buffers_live_stream_and_discards_only_baseline(tmp_path):
    async def scenario():
        store = SQLiteStore(tmp_path / "state.sqlite3")
        conv = Conversation("boss", "actor_1", Audience("audience_1"), "friend-1")
        old = Message("boss", "baseline", conv, "old", 1, False, "baseline")
        new = Message("boss", "new", conv, "new", int(time.time() * 1000) + 1000, False, "new")
        adapter = StreamingAdapter([old, new], baseline_ids={"baseline"})
        runtime = AdapterRuntime(make_config(tmp_path), adapter, store, gateway=StopAfterOutboxGateway(store, 1))

        await asyncio.wait_for(runtime.run(), 2)

        items = store.due_outbox()
        assert len(items) == 1 and items[0].payload["data"]["content"] == {"text": "new"}
        assert store.get_bootstrap("boss") == (True, str(new.sent_at_ms))
        store.close()

    asyncio.run(scenario())


def test_restart_catches_up_and_cursor_never_moves_backwards(tmp_path):
    async def scenario():
        store = SQLiteStore(tmp_path / "state.sqlite3")
        actor = Actor("boss", "actor_1", "Actor")
        store.save_actor(actor)
        store.set_bootstrap("boss", "1000")
        conv = Conversation("boss", "actor_1", Audience("audience_1"), "friend-1")
        newer = Message("boss", "1200", conv, "newer", 1200)
        older = Message("boss", "1100", conv, "older", 1100)
        adapter = StreamingAdapter([], catch_up=[newer, older])
        runtime = AdapterRuntime(make_config(tmp_path), adapter, store, gateway=StopAfterOutboxGateway(store, 2))

        await asyncio.wait_for(runtime.run(), 2)

        assert {item.payload["data"]["content"]["text"] for item in store.due_outbox()} == {"older", "newer"}
        assert store.get_bootstrap("boss") == (True, "1200")
        store.close()

    asyncio.run(scenario())


def test_restart_skips_catch_up_when_platform_disables_automatic_history(tmp_path):
    async def scenario():
        store = SQLiteStore(tmp_path / "state.sqlite3")
        actor = Actor("boss", "actor_1", "Actor")
        store.save_actor(actor)
        store.set_bootstrap("boss", "1000")
        adapter = StreamingAdapter([])
        adapter.capabilities = PlatformCapabilities(
            history_backfill=True,
            automatic_catch_up=False,
        )

        async def forbidden(_cursor):
            raise AssertionError("automatic catch_up must not run")

        adapter.catch_up = forbidden

        class StopGateway:
            is_ready = True

            async def run(self, actor, on_delivery, stop):
                stop.set()

            async def wait_ready(self, timeout=None):
                return None

        runtime = AdapterRuntime(make_config(tmp_path), adapter, store, gateway=StopGateway())
        await asyncio.wait_for(runtime.run(), 2)
        store.close()

    asyncio.run(scenario())


def test_invalid_request_is_not_retryable():
    assert AdapterRuntime._is_retryable_exception(RuntimeError("create failed message='INVALID_REQUEST' err=4")) is False
    assert AdapterRuntime._is_retryable_exception(RuntimeError("发信缺少 DY_TICKET")) is False
    assert AdapterRuntime._is_retryable_exception(RuntimeError("SyntaxError: 缺少 ')'")) is False
    assert AdapterRuntime._is_retryable_exception(RuntimeError("send HTTP 502: temporary")) is True
