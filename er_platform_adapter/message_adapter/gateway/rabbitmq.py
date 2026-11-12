from __future__ import annotations

import asyncio
import json
import logging
import random
import time
from collections.abc import Awaitable, Callable
from datetime import timedelta
from typing import Any, Protocol

from message_adapter.config import AdapterConfig
from message_adapter.core.models import Actor
from message_adapter.storage import SQLiteStore

logger = logging.getLogger(__name__)

DeliveryHandler = Callable[[dict[str, Any]], Awaitable[None]]
PrePublishHandler = Callable[[dict[str, Any]], Awaitable[None]]


def _payload_account(payload: dict[str, Any]) -> tuple[str, str]:
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    platform = str(payload.get("platform") or data.get("platform") or "")
    actor_id = str(payload.get("platform_actor_id") or data.get("actorPlatformID") or "")
    return platform, actor_id


def should_log_received(payload: dict[str, Any], actor: Actor, *, historical: bool) -> bool:
    """Log only this account's deliveries that arrived after the current login."""
    if historical:
        return False
    platform, actor_id = _payload_account(payload)
    return platform == actor.platform and actor_id == actor.platform_actor_id


def _log_message(direction: str, payload: dict[str, Any], *, event_id: str = "") -> None:
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    logger.info(
        "RabbitMQ %s func=%s event_id=%s platform=%s platform_actor_id=%s "
        "platform_audience_id=%s client_msg_id=%s",
        direction,
        payload.get("func") or "",
        event_id or payload.get("id") or "",
        payload.get("platform") or data.get("platform") or "",
        payload.get("platform_actor_id") or data.get("actorPlatformID") or "",
        payload.get("platform_audience_id") or data.get("audiencePlatformID") or "",
        data.get("clientMsgID") or payload.get("clientMsgID") or data.get("client_msg_id") or payload.get("client_msg_id") or "",
    )
    logger.debug(
        "RabbitMQ %s payload=%s",
        direction,
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
    )


async def probe_rabbitmq(config: AdapterConfig) -> None:
    """Read-only connection and passive topology check used by doctor."""
    import aio_pika

    connection = await aio_pika.connect(
        host=config.rabbitmq_host,
        port=config.rabbitmq_port,
        login=config.rabbitmq_user,
        password=config.rabbitmq_password,
        virtualhost=config.rabbitmq_vhost,
        timeout=15,
        client_properties={"connection_name": "message-adapter:doctor"},
    )
    try:
        channel = await connection.channel()
        await channel.declare_queue(config.edge_queue, passive=True)
        await channel.declare_exchange(
            config.receive_exchange,
            type=config.receive_exchange_type,
            passive=True,
        )
    finally:
        if not connection.is_closed:
            await connection.close()


async def watch_rabbitmq(config: AdapterConfig, on_delivery: DeliveryHandler) -> None:
    """Observe new exchange deliveries through an isolated auto-delete queue."""
    import aio_pika

    connection = await aio_pika.connect(
        host=config.rabbitmq_host,
        port=config.rabbitmq_port,
        login=config.rabbitmq_user,
        password=config.rabbitmq_password,
        virtualhost=config.rabbitmq_vhost,
        timeout=15,
        client_properties={"connection_name": "message-adapter:mq-watch"},
    )
    try:
        channel = await connection.channel()
        await channel.set_qos(prefetch_count=20)
        exchange = await channel.declare_exchange(
            config.receive_exchange,
            type=config.receive_exchange_type,
            passive=True,
        )
        queue = await channel.declare_queue(
            "",
            durable=False,
            exclusive=True,
            auto_delete=True,
        )
        await queue.bind(exchange, routing_key=config.receive_routing_key)
        async with queue.iterator() as iterator:
            async for message in iterator:
                async with message.process(requeue=False):
                    try:
                        payload = json.loads(message.body.decode("utf-8"))
                    except (UnicodeDecodeError, json.JSONDecodeError):
                        logger.warning("mq-watch discarded invalid JSON delivery")
                        continue
                    if isinstance(payload, dict):
                        await on_delivery(payload)
    finally:
        if not connection.is_closed:
            await connection.close()


class BrokerSession(Protocol):
    async def connect(self, actor: Actor) -> None: ...

    async def publish(self, payload: dict[str, Any], event_id: str) -> None: ...

    async def consume(self, on_delivery: DeliveryHandler) -> None: ...

    async def close(self) -> None: ...


class AioPikaBroker:
    """One RabbitMQ connection with separate confirm and consumer channels."""

    def __init__(self, config: AdapterConfig):
        self.config = config
        self._connection = None
        self._publish_channel = None
        self._consumer_channel = None
        self._outgoing_exchange = None
        self._receive_queue = None
        self._queued_before_consume = 0

    async def connect(self, actor: Actor) -> None:
        import aio_pika

        # Use plain connect (not connect_robust). Robust reconnects the TCP
        # socket underneath while leaving these channel objects dead, which
        # surfaces as ChannelInvalidStateError: No active transport in channel.
        # RabbitMQGateway.run() already owns full session reconnect + new channels.
        self._connection = await aio_pika.connect(
            host=self.config.rabbitmq_host,
            port=self.config.rabbitmq_port,
            login=self.config.rabbitmq_user,
            password=self.config.rabbitmq_password,
            virtualhost=self.config.rabbitmq_vhost,
            timeout=15,
            client_properties={"connection_name": (f"message-adapter:{actor.platform}:{actor.platform_actor_id}")},
        )
        self._publish_channel = await self._connection.channel(
            publisher_confirms=True,
            on_return_raises=True,
        )
        # The edge-to-IM queue is shared infrastructure owned by the IM side.
        # Only verify that it exists: redeclaring it with local arguments (for
        # example x-message-ttl) closes the channel when the server topology
        # was created with different settings.  Per-message expiration is set
        # in publish() below.
        await self._publish_channel.declare_queue(
            self.config.edge_queue,
            passive=True,
        )
        self._outgoing_exchange = self._publish_channel.default_exchange

        self._consumer_channel = await self._connection.channel()
        await self._consumer_channel.set_qos(prefetch_count=self.config.prefetch_count)
        exchange = await self._consumer_channel.declare_exchange(
            self.config.receive_exchange,
            type=self.config.receive_exchange_type,
            passive=True,
        )
        arguments = {"x-single-active-consumer": True} if self.config.single_active_consumer else None
        self._receive_queue = await self._consumer_channel.declare_queue(
            self.config.receive_queue_name(actor.platform_actor_id),
            durable=True,
            exclusive=False,
            auto_delete=False,
            arguments=arguments,
        )
        await self._receive_queue.bind(exchange, routing_key=self.config.receive_routing_key)
        # Messages already sitting in the queue belong to the previous session.
        declared = getattr(self._receive_queue, "declaration_result", None)
        try:
            queued = int(getattr(declared, "message_count", 0) or 0)
        except (TypeError, ValueError):
            queued = 0
        self._queued_before_consume = max(0, queued)

    async def publish(self, payload: dict[str, Any], event_id: str) -> None:
        import aio_pika

        if self._outgoing_exchange is None:
            raise ConnectionError("RabbitMQ publisher is not connected")
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        confirmed = await self._outgoing_exchange.publish(
            aio_pika.Message(
                body=body,
                content_type="application/json",
                content_encoding="utf-8",
                delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
                message_id=event_id,
                timestamp=int(time.time()),
                expiration=timedelta(milliseconds=self.config.message_ttl_ms),
            ),
            routing_key=self.config.edge_queue,
            mandatory=True,
        )
        if confirmed is False:
            raise ConnectionError("RabbitMQ publisher confirm was negative")

    async def consume(self, on_delivery: DeliveryHandler) -> None:
        if self._receive_queue is None:
            raise ConnectionError("RabbitMQ consumer is not connected")
        async with self._receive_queue.iterator() as iterator:
            async for message in iterator:
                async with message.process(requeue=True, ignore_processed=True):
                    try:
                        decoded = message.body.decode("utf-8")
                        payload = json.loads(decoded)
                    except (UnicodeDecodeError, json.JSONDecodeError):
                        logger.warning("discarded invalid RabbitMQ JSON delivery")
                        continue
                    if not isinstance(payload, dict):
                        logger.warning("discarded non-object RabbitMQ JSON delivery")
                        continue
                    historical = self._queued_before_consume > 0
                    if historical:
                        self._queued_before_consume -= 1
                    # Returning normally ACKs. Repository failures escape this
                    # block and are NACKed with requeue by aio-pika.
                    await on_delivery(payload, historical=historical)

    async def close(self) -> None:
        connection = self._connection
        self._connection = None
        self._publish_channel = None
        self._consumer_channel = None
        self._outgoing_exchange = None
        self._receive_queue = None
        if connection is not None and not connection.is_closed:
            await connection.close()


class RabbitMQGateway:
    """RabbitMQ bridge backed by the transactional SQLite publish outbox."""

    RETRY_SECONDS = (2.0, 5.0, 10.0, 30.0, 60.0)

    def __init__(
        self,
        config: AdapterConfig,
        store: SQLiteStore,
        *,
        broker_factory=None,
        before_publish: PrePublishHandler | None = None,
    ):
        self.config = config
        self.store = store
        self._broker_factory = broker_factory or (lambda: AioPikaBroker(config))
        self._before_publish = before_publish
        self._ready = asyncio.Event()

    async def run(self, actor: Actor, on_delivery: DeliveryHandler, stop: asyncio.Event) -> None:
        reconnect_attempt = 0
        while not stop.is_set():
            broker: BrokerSession = self._broker_factory()
            try:
                await broker.connect(actor)
                self._ready.set()
                reconnect_attempt = 0
                logger.info(
                    "RabbitMQ ready platform=%s platform_actor_id=%s",
                    actor.platform,
                    actor.platform_actor_id,
                )
                await self._run_session(broker, actor, on_delivery, stop)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._ready.clear()
                delay = self.RETRY_SECONDS[min(reconnect_attempt, len(self.RETRY_SECONDS) - 1)]
                reconnect_attempt += 1
                delay += random.uniform(0, min(1.0, delay * 0.1))
                logger.warning(
                    "RabbitMQ connection lost; retrying in %.1fs: %s",
                    delay,
                    exc,
                    exc_info=True,
                )
                try:
                    await asyncio.wait_for(stop.wait(), timeout=delay)
                except asyncio.TimeoutError:
                    pass
            finally:
                self._ready.clear()
                await broker.close()

    async def _run_session(
        self,
        broker: BrokerSession,
        actor: Actor,
        on_delivery: DeliveryHandler,
        stop: asyncio.Event,
    ) -> None:
        async def logged_delivery(payload: dict[str, Any], historical: bool = False) -> None:
            if should_log_received(payload, actor, historical=historical):
                _log_message("received", payload)
            await on_delivery(payload)

        consumer = asyncio.create_task(broker.consume(logged_delivery), name="rabbitmq-consumer")
        publisher = asyncio.create_task(self._outbox_loop(broker, actor, stop), name="rabbitmq-publisher")
        stop_waiter = asyncio.create_task(stop.wait(), name="rabbitmq-stop")
        tasks = (consumer, publisher, stop_waiter)
        try:
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            if stop_waiter in done:
                return
            for task in done:
                exc = task.exception()
                if exc:
                    raise exc
            raise ConnectionError("RabbitMQ worker stopped unexpectedly")
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _outbox_loop(self, broker: BrokerSession, actor: Actor, stop: asyncio.Event) -> None:
        while not stop.is_set():
            items = await asyncio.to_thread(
                self.store.due_outbox,
                None,
                100,
                platform=actor.platform,
                platform_actor_id=actor.platform_actor_id,
            )
            if not items:
                try:
                    await asyncio.wait_for(stop.wait(), timeout=0.2)
                    return
                except asyncio.TimeoutError:
                    continue
            for item in items:
                if self._before_publish is not None:
                    try:
                        await self._before_publish(item.payload)
                    except Exception as exc:
                        retry = self.RETRY_SECONDS[min(item.attempts, len(self.RETRY_SECONDS) - 1)]
                        await asyncio.to_thread(
                            self.store.mark_attempt,
                            item.event_id,
                            time.time() + retry,
                            f"control_gateway:{type(exc).__name__}",
                        )
                        logger.warning(
                            "outbox event waiting for IM account registration event_id=%s error=%s detail=%s",
                            item.event_id,
                            type(exc).__name__,
                            str(exc),
                            exc_info=True,
                        )
                        # Do not sleep the whole publisher: other due outbox
                        # events must still reach RabbitMQ immediately.
                        continue
                try:
                    await broker.publish(item.payload, item.event_id)
                except Exception as exc:
                    retry = self.RETRY_SECONDS[min(item.attempts, len(self.RETRY_SECONDS) - 1)]
                    await asyncio.to_thread(
                        self.store.mark_attempt,
                        item.event_id,
                        time.time() + retry,
                        type(exc).__name__,
                    )
                    raise
                await asyncio.to_thread(self.store.mark_published, item.event_id)
                _log_message("published", item.payload, event_id=item.event_id)

    async def wait_ready(self, timeout: float | None = 20.0) -> None:
        """Wait until a broker session is usable.

        Interactive diagnostics may still use a finite timeout.  The long-running
        adapter passes ``None`` because ``run()`` already owns the reconnect
        policy; a slow first connection must not restart the platform session.
        """
        if timeout is None:
            await self._ready.wait()
            return
        await asyncio.wait_for(self._ready.wait(), timeout=timeout)

    @property
    def is_ready(self) -> bool:
        return self._ready.is_set()
