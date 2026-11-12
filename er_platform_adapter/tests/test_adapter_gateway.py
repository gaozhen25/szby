from __future__ import annotations

import asyncio
import logging
import sys
from types import SimpleNamespace

from message_adapter.config import AdapterConfig
from message_adapter.core.models import Actor
from message_adapter.gateway import AioPikaBroker, RabbitMQGateway
from message_adapter.gateway.rabbitmq import should_log_received
from message_adapter.storage import SQLiteStore


def config(tmp_path):
    return AdapterConfig(
        platform="boss",
        rabbitmq_host="rabbit.test",
        rabbitmq_user="adapter",
        rabbitmq_password="secret",
        state_db=tmp_path / "state.sqlite3",
    )


class FakeBroker:
    def __init__(self, *, fail_connect=False, fail_publish=False):
        self.fail_connect = fail_connect
        self.fail_publish = fail_publish
        self.actor = None
        self.published: list[tuple[dict, str]] = []
        self.incoming: asyncio.Queue[dict] = asyncio.Queue()
        self.closed = False

    async def connect(self, actor):
        if self.fail_connect:
            raise ConnectionError("offline")
        self.actor = actor

    async def publish(self, payload, event_id):
        if self.fail_publish:
            raise ConnectionError("confirm failed")
        self.published.append((payload, event_id))

    async def consume(self, on_delivery):
        while True:
            await on_delivery(await self.incoming.get())

    async def close(self):
        self.closed = True


def test_broker_treats_shared_queue_and_exchange_as_server_owned(tmp_path, monkeypatch):
    class Queue:
        def __init__(self):
            self.bindings = []

        async def bind(self, exchange, routing_key):
            self.bindings.append((exchange, routing_key))

    class Channel:
        def __init__(self):
            self.queue_calls = []
            self.exchange_calls = []
            self.default_exchange = object()
            self.qos = None

        async def declare_queue(self, name, **kwargs):
            queue = Queue()
            self.queue_calls.append((name, kwargs, queue))
            return queue

        async def declare_exchange(self, name, **kwargs):
            exchange = object()
            self.exchange_calls.append((name, kwargs, exchange))
            return exchange

        async def set_qos(self, *, prefetch_count):
            self.qos = prefetch_count

    class Connection:
        def __init__(self):
            self.channels = [Channel(), Channel()]
            self.channel_calls = []
            self.is_closed = False

        async def channel(self, **kwargs):
            self.channel_calls.append(kwargs)
            return self.channels[len(self.channel_calls) - 1]

        async def close(self):
            self.is_closed = True

    async def scenario():
        connection = Connection()

        async def connect(**kwargs):
            return connection

        monkeypatch.setitem(sys.modules, "aio_pika", SimpleNamespace(connect=connect))
        broker = AioPikaBroker(config(tmp_path))
        actor = Actor("boss", "actor-1")

        await broker.connect(actor)

        publisher, consumer = connection.channels
        assert publisher.queue_calls[0][:2] == (
            "edge2im_messages",
            {"passive": True},
        )
        assert consumer.exchange_calls[0][:2] == (
            "im2edge.events",
            {"type": "topic", "passive": True},
        )
        receive_name, receive_options, receive_queue = consumer.queue_calls[0]
        assert receive_name == config(tmp_path).receive_queue_name("actor-1")
        assert receive_options["durable"] is True
        assert receive_queue.bindings == [
            (consumer.exchange_calls[0][2], "im2edge_messages")
        ]

    asyncio.run(scenario())


def test_gateway_publisher_confirm_completes_outbox(tmp_path):
    async def scenario():
        store = SQLiteStore(tmp_path / "state.sqlite3")
        event = {
            "id": "event-1",
            "func": "push_message_v2",
            "platform": "boss",
            "data": {"actorPlatformID": "actor-1"},
        }
        store.enqueue(event["id"], event)
        broker = FakeBroker()
        gateway = RabbitMQGateway(config(tmp_path), store, broker_factory=lambda: broker)
        stop = asyncio.Event()

        async def delivery_handler(payload):
            return None

        task = asyncio.create_task(gateway.run(Actor("boss", "actor-1"), delivery_handler, stop))
        await gateway.wait_ready(1)
        for _ in range(100):
            if broker.published:
                break
            await asyncio.sleep(0.01)
        stop.set()
        await asyncio.wait_for(task, 1)

        assert broker.actor == Actor("boss", "actor-1")
        assert broker.published == [(event, "event-1")]
        assert store.due_outbox() == []
        assert broker.closed
        store.close()

    asyncio.run(scenario())


def test_gateway_dispatches_rabbitmq_delivery(tmp_path):
    async def scenario():
        store = SQLiteStore(tmp_path / "state.sqlite3")
        broker = FakeBroker()
        gateway = RabbitMQGateway(config(tmp_path), store, broker_factory=lambda: broker)
        stop = asyncio.Event()
        calls = []

        async def delivery_handler(payload):
            calls.append(payload)
            stop.set()

        task = asyncio.create_task(gateway.run(Actor("boss", "actor-1"), delivery_handler, stop))
        await gateway.wait_ready(1)
        request = {
            "platform": "boss",
            "platform_actor_id": "actor-1",
            "platform_audience_id": "user-1",
            "data": {},
        }
        await broker.incoming.put(request)
        await asyncio.wait_for(task, 1)

        assert calls == [request]
        store.close()

    asyncio.run(scenario())


def test_gateway_logs_published_and_received_message_metadata(tmp_path, caplog):
    async def scenario():
        store = SQLiteStore(tmp_path / "state.sqlite3")
        event = {
            "id": "event-1",
            "func": "push_message_v2",
            "platform": "boss",
            "data": {
                "actorPlatformID": "actor-1",
                "audiencePlatformID": "user-1",
            },
        }
        store.enqueue(event["id"], event)
        broker = FakeBroker()
        gateway = RabbitMQGateway(config(tmp_path), store, broker_factory=lambda: broker)
        stop = asyncio.Event()

        async def delivery_handler(payload):
            stop.set()

        with caplog.at_level(logging.INFO, logger="message_adapter.gateway.rabbitmq"):
            task = asyncio.create_task(gateway.run(Actor("boss", "actor-1"), delivery_handler, stop))
            await gateway.wait_ready(1)
            for _ in range(100):
                if broker.published:
                    break
                await asyncio.sleep(0.01)
            await broker.incoming.put(
                {
                    "platform": "boss",
                    "platform_actor_id": "actor-1",
                    "platform_audience_id": "user-1",
                    "data": {"client_msg_id": "client-1"},
                }
            )
            await asyncio.wait_for(task, 1)

        assert "RabbitMQ published func=push_message_v2 event_id=event-1" in caplog.text
        assert "platform_actor_id=actor-1" in caplog.text
        assert "RabbitMQ received" in caplog.text
        assert "client_msg_id=client-1" in caplog.text
        store.close()

    asyncio.run(scenario())


def test_received_log_skips_other_accounts_and_queued_history(tmp_path, caplog):
    class HistoricalBroker(FakeBroker):
        async def consume(self, on_delivery):
            await on_delivery(await self.incoming.get(), historical=True)

    async def scenario():
        store = SQLiteStore(tmp_path / "state.sqlite3")
        actor = Actor("boss", "actor-1")
        assert should_log_received(
            {"platform": "wechat", "platform_actor_id": "wx-1", "data": {}},
            actor,
            historical=False,
        ) is False
        assert should_log_received(
            {"platform": "boss", "platform_actor_id": "actor-1", "data": {}},
            actor,
            historical=True,
        ) is False

        other = FakeBroker()
        gateway = RabbitMQGateway(config(tmp_path), store, broker_factory=lambda: other)
        stop = asyncio.Event()
        delivered: list[dict] = []

        async def delivery_handler(payload):
            delivered.append(payload)
            stop.set()

        with caplog.at_level(logging.INFO, logger="message_adapter.gateway.rabbitmq"):
            task = asyncio.create_task(gateway.run(actor, delivery_handler, stop))
            await gateway.wait_ready(1)
            await other.incoming.put(
                {
                    "platform": "wechat",
                    "platform_actor_id": "wx-1",
                    "data": {"client_msg_id": "foreign-1"},
                }
            )
            await asyncio.wait_for(task, 1)

        assert delivered[0]["platform"] == "wechat"
        assert "RabbitMQ received" not in caplog.text
        assert "foreign-1" not in caplog.text

        historical = HistoricalBroker()
        gateway = RabbitMQGateway(config(tmp_path), store, broker_factory=lambda: historical)
        stop = asyncio.Event()
        delivered.clear()

        async def historical_handler(payload):
            delivered.append(payload)
            stop.set()

        with caplog.at_level(logging.INFO, logger="message_adapter.gateway.rabbitmq"):
            task = asyncio.create_task(gateway.run(actor, historical_handler, stop))
            await gateway.wait_ready(1)
            await historical.incoming.put(
                {
                    "platform": "boss",
                    "platform_actor_id": "actor-1",
                    "data": {"client_msg_id": "old-1"},
                }
            )
            await asyncio.wait_for(task, 1)

        assert delivered[0]["data"]["client_msg_id"] == "old-1"
        assert "old-1" not in caplog.text
        store.close()

    asyncio.run(scenario())


def test_gateway_reconnects_and_reaches_ready(tmp_path):
    async def scenario():
        store = SQLiteStore(tmp_path / "state.sqlite3")
        brokers = [FakeBroker(fail_connect=True), FakeBroker()]

        def factory():
            return brokers.pop(0)

        gateway = RabbitMQGateway(config(tmp_path), store, broker_factory=factory)
        gateway.RETRY_SECONDS = (0.01,)
        stop = asyncio.Event()

        async def delivery_handler(payload):
            return None

        task = asyncio.create_task(gateway.run(Actor("boss", "actor-1"), delivery_handler, stop))
        await gateway.wait_ready(1)
        stop.set()
        await asyncio.wait_for(task, 1)

        assert brokers == []
        store.close()

    asyncio.run(scenario())


def test_negative_publish_confirm_retries_same_event_id(tmp_path):
    async def scenario():
        store = SQLiteStore(tmp_path / "state.sqlite3")
        store.enqueue(
            "event-1",
            {"id": "event-1"},
            platform="boss",
            platform_actor_id="actor-1",
        )
        first = FakeBroker(fail_publish=True)
        second = FakeBroker()
        brokers = [first, second]

        def factory():
            return brokers.pop(0)

        gateway = RabbitMQGateway(config(tmp_path), store, broker_factory=factory)
        gateway.RETRY_SECONDS = (0.01,)
        stop = asyncio.Event()
        task = asyncio.create_task(gateway.run(Actor("boss", "actor-1"), lambda payload: asyncio.sleep(0), stop))
        for _ in range(200):
            if second.published:
                break
            await asyncio.sleep(0.005)
        stop.set()
        await asyncio.wait_for(task, 1)
        assert first.closed
        assert second.published == [({"id": "event-1"}, "event-1")]
        assert store.due_outbox(now=float("inf")) == []
        store.close()

    asyncio.run(scenario())


def test_control_registration_failure_keeps_event_in_outbox(tmp_path):
    async def scenario():
        store = SQLiteStore(tmp_path / "state.sqlite3")
        event = {
            "id": "event-1",
            "func": "push_message_v2",
            "platform": "boss",
            "data": {"actorPlatformID": "actor-1"},
        }
        store.enqueue(event["id"], event)
        broker = FakeBroker()
        stop = asyncio.Event()

        async def registration_gate(payload):
            assert payload == event
            stop.set()
            raise ConnectionError("control gateway offline")

        gateway = RabbitMQGateway(
            config(tmp_path),
            store,
            broker_factory=lambda: broker,
            before_publish=registration_gate,
        )
        task = asyncio.create_task(
            gateway.run(Actor("boss", "actor-1"), lambda payload: asyncio.sleep(0), stop)
        )
        await asyncio.wait_for(task, 1)

        assert broker.published == []
        pending = store.due_outbox(now=float("inf"))
        assert len(pending) == 1
        assert pending[0].event_id == "event-1"
        assert pending[0].attempts == 1
        store.close()

    asyncio.run(scenario())
