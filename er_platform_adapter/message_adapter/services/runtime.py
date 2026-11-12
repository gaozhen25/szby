from __future__ import annotations

import asyncio
import hashlib
import logging
import random
import time
from typing import Any

from message_adapter.config import AdapterConfig
from message_adapter.core.models import (
    Actor,
    Audience,
    Conversation,
    Message,
    SendRequest,
    downlink_client_msg_id,
    send_status_payload,
)
from message_adapter.core.platform import PlatformAdapter
from message_adapter.gateway import RabbitMQGateway
from message_adapter.process_lock import SingleInstanceLock
from message_adapter.storage import ConversationRecord, DownlinkRecord, SQLiteStore

logger = logging.getLogger(__name__)
activity_logger = logging.getLogger("message_adapter.activity")
# Phone exchange stays implemented. Turn this on to request it with WeChat.
BOSS_PHONE_EXCHANGE_ENABLED = False
BOSS_AI_REPLIES_BEFORE_EXCHANGE = 2


def _phone_exchange_request(adapter: PlatformAdapter) -> Any:
    if not BOSS_PHONE_EXCHANGE_ENABLED:
        return None
    return getattr(adapter, "request_phone_exchange", None)


class AdapterRuntime:
    """Coordinates one authenticated platform slot and its RabbitMQ bridge."""

    RETRY_SECONDS = (2.0, 5.0, 10.0, 30.0, 60.0)

    def __init__(
        self,
        config: AdapterConfig,
        adapter: PlatformAdapter,
        store: SQLiteStore,
        *,
        gateway: RabbitMQGateway | None = None,
    ):
        self.config = config
        self.adapter = adapter
        self.store = store
        self.gateway = gateway or RabbitMQGateway(config, store)
        self.stop_event = asyncio.Event()
        self.ready_event = asyncio.Event()
        self._incoming: asyncio.Queue[Message] = asyncio.Queue(maxsize=2000)
        self._actor: Actor | None = None
        self._stream_task: asyncio.Task[Any] | None = None
        self._side_tasks: set[asyncio.Task[Any]] = set()
        self._random = random.SystemRandom()

    @property
    def actor(self) -> Actor | None:
        return self._actor

    @property
    def is_ready(self) -> bool:
        return bool(
            self.ready_event.is_set()
            and getattr(self.gateway, "is_ready", True)
            and self._stream_task is not None
            and not self._stream_task.done()
        )

    async def run(self) -> None:
        errors = self.config.validate(require_gateway=True, require_send_status=True)
        if errors:
            raise ValueError("; ".join(errors))
        actor = await self.adapter.authenticate()
        if actor.platform != self.config.platform:
            raise ValueError("authenticated Actor platform does not match Adapter configuration")
        await self.adapter.validate_identity(actor)
        self._actor = actor
        actor_key = hashlib.sha256(f"{actor.platform}:{actor.platform_actor_id}".encode()).hexdigest()[:24]
        actor_lock = SingleInstanceLock(self.config.state_db.parent / ".locks" / f"{actor.platform}-{actor_key}.lock")
        lock_acquired = False
        tasks: list[asyncio.Task[Any]] = []
        bootstrap_task: asyncio.Task[Any] | None = None
        try:
            actor_lock.__enter__()
            lock_acquired = True
            await asyncio.to_thread(self.store.save_actor, actor)
            await self.adapter.persist_identity(actor)
            await self._recover_unconfirmed_downlinks()

            stream_task = asyncio.create_task(self._pump_platform(), name="platform-stream")
            self._stream_task = stream_task
            tasks.append(stream_task)
            bootstrap_started_ms = int(time.time() * 1000)
            initialized, cursor = await asyncio.to_thread(
                self.store.get_bootstrap,
                actor.platform,
            )
            # Live receive, uplink processing, RabbitMQ, and downlink send
            # start before friend-list bootstrap. Bootstrap must not delay them.
            processor = asyncio.create_task(
                self._process_stream(
                    first_start=not initialized,
                    bootstrap_started_ms=bootstrap_started_ms,
                    baseline_ids=frozenset(),
                ),
                name="platform-processor",
            )
            gateway = asyncio.create_task(
                self.gateway.run(actor, self._accept_delivery, self.stop_event),
                name="rabbitmq-gateway",
            )
            inbox = asyncio.create_task(self._inbox_worker(), name="downlink-inbox")
            stop_waiter = asyncio.create_task(self.stop_event.wait(), name="adapter-stop")
            tasks.extend((processor, gateway, inbox, stop_waiter))
            bootstrap_task = asyncio.create_task(
                self._bootstrap_in_background(initialized=initialized, cursor=cursor),
                name="platform-bootstrap",
            )
            wait_ready = getattr(self.gateway, "wait_ready", None)
            if wait_ready is not None:
                # RabbitMQ owns its reconnect loop.  Do not impose a short
                # startup timeout here: a slow broker handshake used to tear
                # down an otherwise healthy platform connection every 20s.
                gateway_ready = asyncio.create_task(
                    wait_ready(timeout=None),
                    name="rabbitmq-initial-ready",
                )
                try:
                    done, _ = await asyncio.wait(
                        (*tasks, gateway_ready),
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                    completed_workers = done - {gateway_ready}
                    if completed_workers:
                        if stop_waiter in completed_workers:
                            return
                        for task in completed_workers:
                            exc = task.exception()
                            if exc:
                                raise exc
                        raise RuntimeError("adapter worker stopped before RabbitMQ became ready")
                    await gateway_ready
                finally:
                    gateway_ready.cancel()
                    await asyncio.gather(gateway_ready, return_exceptions=True)
            self.ready_event.set()
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            if stop_waiter not in done:
                for task in done:
                    exc = task.exception()
                    if exc:
                        raise exc
                raise RuntimeError("adapter worker stopped unexpectedly")
        finally:
            self.ready_event.clear()
            self.stop_event.set()
            side_tasks = list(self._side_tasks)
            if bootstrap_task is not None:
                bootstrap_task.cancel()
            for task in side_tasks + tasks:
                task.cancel()
            pending = [task for task in (bootstrap_task, *side_tasks, *tasks) if task is not None]
            await asyncio.gather(*pending, return_exceptions=True)
            try:
                await self.adapter.close()
            finally:
                if lock_acquired:
                    actor_lock.__exit__(None, None, None)

    async def _bootstrap_in_background(self, *, initialized: bool, cursor: str) -> None:
        """Load conversations and optional history without blocking live I/O."""
        try:
            state = await self.adapter.bootstrap()
            await asyncio.to_thread(self._store_bootstrap, state, initialized)
            if initialized and self.adapter.capabilities.automatic_catch_up:
                for message in await self.adapter.catch_up(cursor):
                    if self.stop_event.is_set():
                        return
                    await self._accept_message(message)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning(
                "platform=%s background bootstrap failed",
                self.config.platform,
                exc_info=True,
            )

    def _store_bootstrap(self, state: Any, initialized: bool) -> None:
        for conversation in state.conversations:
            self.store.save_conversation(conversation)
        if not initialized:
            self.store.set_bootstrap(self.config.platform, state.cursor)

    def _track(self, task: asyncio.Task[Any]) -> None:
        self._side_tasks.add(task)
        task.add_done_callback(self._side_tasks.discard)

    async def stop(self) -> None:
        self.stop_event.set()
        await self.adapter.close()

    async def _pump_platform(self) -> None:
        async for message in self.adapter.stream_messages():
            await self._incoming.put(message)
            if self.stop_event.is_set():
                return

    async def _process_stream(
        self,
        *,
        first_start: bool,
        bootstrap_started_ms: int,
        baseline_ids: frozenset[str],
    ) -> None:
        while not self.stop_event.is_set():
            message = await self._incoming.get()
            try:
                if first_start and (message.message_id in baseline_ids or message.sent_at_ms < bootstrap_started_ms):
                    continue
                await self._accept_message(message)
            finally:
                self._incoming.task_done()

    async def _accept_message(self, message: Message) -> None:
        actor = self._require_actor()
        if not message.text:
            return
        await asyncio.to_thread(self.store.save_conversation, message.conversation)
        if message.is_send:
            suppressed = await asyncio.to_thread(
                self.store.consume_echo,
                platform=message.platform,
                platform_actor_id=message.conversation.platform_actor_id,
                platform_conversation_id=message.conversation.platform_conversation_id,
                platform_message_id=message.platform_message_id,
                fingerprint=message.echo_fingerprint(),
            )
            if suppressed:
                logger.info("suppressed adapter send echo id=%s", message.event_id)
                return
            sender_name = actor.username or actor.platform_actor_id
            sender_id = actor.platform_actor_id
            direction = "outgoing"
        else:
            sender = message.conversation.audience
            sender_name = sender.username or sender.platform_audience_id
            sender_id = sender.platform_audience_id
            direction = "incoming"
        payload = message.mq_payload(actor)
        enqueued = await asyncio.to_thread(self.store.enqueue, str(payload["id"]), payload)
        if not enqueued:
            return
        activity_logger.info(
            "platform=%s direction=%s sender=%s sender_id=%s content=%s",
            message.platform,
            direction,
            sender_name,
            sender_id,
            message.text,
            extra={
                "adapter_activity": {
                    "platform": message.platform,
                    "direction": direction,
                    "sender_name": sender_name,
                    "sender_id": sender_id,
                    "content": message.text,
                }
            },
        )
        await asyncio.to_thread(
            self.store.set_bootstrap,
            message.platform,
            str(message.sent_at_ms),
        )

    async def _accept_delivery(self, payload: dict[str, Any]) -> None:
        """Persist a matching delivery before RabbitMQ is allowed to ACK it."""
        actor = self._require_actor()
        if str(payload.get("platform") or "") != actor.platform:
            return
        if str(payload.get("platform_actor_id") or "") != actor.platform_actor_id:
            return
        try:
            request = SendRequest.from_mq_payload(payload)
        except (TypeError, ValueError) as exc:
            await self._record_invalid_delivery(payload, str(exc))
            return

        inserted = await asyncio.to_thread(self.store.put_downlink, request, payload)
        if inserted:
            return
        existing = await asyncio.to_thread(self.store.get_downlink, request.client_msg_id)
        if existing and existing.state == "done":
            await asyncio.to_thread(self.store.replay_downlink_status, request.client_msg_id)

    async def _record_invalid_delivery(self, payload: dict[str, Any], error: str) -> None:
        actor = self._require_actor()
        data = payload.get("data")
        data = data if isinstance(data, dict) else {}
        client_msg_id = downlink_client_msg_id(payload, data)
        if not client_msg_id:
            logger.warning("discarded invalid matching downlink without client_msg_id: %s", error)
            return
        audience_id = str(payload.get("platform_audience_id") or "")
        now_ms = int(time.time() * 1000)
        event = send_status_payload(
            platform=actor.platform,
            client_msg_id=client_msg_id,
            status=self.config.send_status_failed,
            actual_send_time=now_ms,
        )
        await asyncio.to_thread(
            self.store.record_rejected_downlink,
            client_msg_id=client_msg_id,
            platform=actor.platform,
            platform_actor_id=actor.platform_actor_id,
            platform_audience_id=audience_id,
            payload=payload,
            status=self.config.send_status_failed,
            status_event=event,
            error=f"invalid_request:{error}",
        )

    async def _inbox_worker(self) -> None:
        actor = self._require_actor()
        while not self.stop_event.is_set():
            record = await asyncio.to_thread(
                self.store.claim_due_downlink,
                platform=actor.platform,
                platform_actor_id=actor.platform_actor_id,
            )
            if record is None:
                try:
                    await asyncio.wait_for(self.stop_event.wait(), timeout=0.2)
                    return
                except asyncio.TimeoutError:
                    continue
            await self._process_downlink(record)

    async def _process_downlink(self, record: DownlinkRecord) -> None:
        request = SendRequest(
            platform=record.platform,
            platform_actor_id=record.platform_actor_id,
            platform_audience_id=record.platform_audience_id,
            client_msg_id=record.client_msg_id,
            content_type=record.content_type,
            content=record.content,
        )
        if request.content_type != 101:
            await self._finish_failed(request, f"unsupported_content_type:{request.content_type}")
            return
        if not request.content.strip():
            await self._finish_failed(request, "empty_content")
            return

        actor = self._require_actor()
        spacing = self.config.send_min_interval_seconds + self._random.uniform(
            0.0,
            self.config.send_jitter_seconds,
        )
        now = time.time()
        scheduled_at = await asyncio.to_thread(
            self.store.reserve_downlink_send_slot,
            request.client_msg_id,
            platform=actor.platform,
            platform_actor_id=actor.platform_actor_id,
            now=now,
            spacing_seconds=spacing,
            max_per_minute=self.config.send_max_per_minute,
            max_per_hour=self.config.send_max_per_hour,
        )
        if scheduled_at > now:
            logger.info(
                "platform=%s queued rate-limited send client_msg_id=%s delay=%.1fs",
                actor.platform,
                request.client_msg_id,
                scheduled_at - now,
            )
            return

        conversation_record = await asyncio.to_thread(
            self.store.resolve_conversation,
            actor.platform,
            actor.platform_actor_id,
            request.platform_audience_id,
        )
        missing_encrypt = (
            conversation_record is not None
            and actor.platform == "boss"
            and not str(conversation_record.platform_data.get("encrypt_geek_id") or "").strip()
        )
        if conversation_record is None or missing_encrypt:
            audience_id = str(request.platform_audience_id or "").strip()
            if actor.platform == "douyin" and audience_id and not audience_id.isdigit():
                logger.error(
                    "conversation resolution failed client_msg_id=%s error_type=ValueError detail=%s",
                    request.client_msg_id,
                    f"抖音 platform_audience_id 必须是数字 UID，收到: {audience_id!r}",
                )
                await self._finish_failed(
                    request,
                    f"conversation_resolve:invalid_audience_id:{audience_id}",
                )
                return
            try:
                await asyncio.to_thread(self.store.mark_downlink_sending, request.client_msg_id)
                resolved = await self.adapter.resolve_conversation(request.platform_audience_id)
            except Exception as exc:
                logger.exception("conversation resolution failed client_msg_id=%s", request.client_msg_id)
                if self._is_retryable_exception(exc):
                    await self._retry_downlink(record, f"conversation_resolve:{type(exc).__name__}")
                else:
                    await self._finish_failed(request, f"conversation_resolve:{type(exc).__name__}")
                return
            if resolved is None and conversation_record is None:
                await self._finish_failed(request, "conversation_not_found")
                return
            refreshed = str((resolved.platform_data if resolved is not None else {}).get("encrypt_geek_id") or "").strip()
            if resolved is not None and (conversation_record is None or refreshed or actor.platform != "boss"):
                await asyncio.to_thread(self.store.save_conversation, resolved)
                conversation = resolved
            else:
                conversation = self._conversation_from_record(conversation_record)
        else:
            conversation = self._conversation_from_record(conversation_record)
            await asyncio.to_thread(self.store.mark_downlink_sending, request.client_msg_id)
        try:
            result = await self.adapter.send_text(conversation, request.content)
        except Exception as exc:
            logger.error(
                "platform send failed client_msg_id=%s error_type=%s detail=%s",
                request.client_msg_id,
                type(exc).__name__,
                str(exc)[:300] or repr(exc),
                exc_info=True,
            )
            if self._is_retryable_exception(exc):
                await self._retry_downlink(record, type(exc).__name__)
            else:
                await self._finish_failed(request, f"{type(exc).__name__}:{exc}")
            return
        if result.conversation_ticket:
            conversation = Conversation(
                platform=conversation.platform,
                platform_actor_id=conversation.platform_actor_id,
                audience=conversation.audience,
                platform_conversation_id=result.conversation_id or conversation.platform_conversation_id,
                platform_data={
                    **conversation.platform_data,
                    "conversation_short_id": result.conversation_short_id
                    or int(conversation.platform_data.get("conversation_short_id") or 0),
                    "conversation_ticket": result.conversation_ticket,
                },
            )
            await asyncio.to_thread(self.store.save_conversation, conversation)
        if not result.success:
            if result.retryable:
                await self._retry_downlink(record, result.error or "platform_send_failed")
            else:
                await self._finish_failed(request, result.error or "platform_send_failed", result.sent_at_ms)
            return

        synthetic = Message(
            platform=actor.platform,
            message_id=result.platform_message_id or request.client_msg_id,
            platform_message_id=result.platform_message_id,
            conversation=conversation,
            text=request.content,
            sent_at_ms=result.sent_at_ms,
            is_send=True,
        )
        await asyncio.to_thread(
            self.store.add_echo,
            platform=actor.platform,
            platform_actor_id=actor.platform_actor_id,
            platform_conversation_id=conversation.platform_conversation_id,
            platform_message_id=result.platform_message_id,
            fingerprint=synthetic.echo_fingerprint(),
            ttl_seconds=120.0,
        )
        await self._finish_status(
            request,
            self.config.send_status_success,
            sent_at_ms=result.sent_at_ms,
            platform_message_id=result.platform_message_id,
        )
        await self._maybe_boss_exchange_after_ai_reply(conversation)

    async def _maybe_boss_exchange_after_ai_reply(self, conversation: Conversation) -> None:
        """Request WeChat once the AI has successfully sent two replies to this candidate."""
        if conversation.platform != "boss" or not self.adapter.capabilities.wechat_exchange:
            return
        wechat_request = getattr(self.adapter, "request_wechat_exchange", None)
        phone_request = _phone_exchange_request(self.adapter)
        if wechat_request is None and phone_request is None:
            return
        actor_id = conversation.platform_actor_id
        audience_id = conversation.audience.platform_audience_id
        if not audience_id:
            return
        need_wechat = wechat_request is not None and not await asyncio.to_thread(
            self.store.has_wechat_exchange, actor_id, audience_id
        )
        need_phone = phone_request is not None and not await asyncio.to_thread(
            self.store.has_phone_exchange, actor_id, audience_id
        )
        if not need_wechat and not need_phone:
            return
        count = await asyncio.to_thread(self.store.record_boss_ai_reply, actor_id, audience_id)
        if count < BOSS_AI_REPLIES_BEFORE_EXCHANGE:
            return
        if need_wechat and await asyncio.to_thread(self.store.claim_wechat_exchange, actor_id, audience_id):
            self._track(
                asyncio.create_task(
                    self._send_recorded_exchange(
                        wechat_request,
                        self.store.release_wechat_exchange,
                        conversation,
                        actor_id,
                        audience_id,
                        "wechat",
                    ),
                    name="boss-wechat-exchange",
                )
            )
        if need_phone and await asyncio.to_thread(self.store.claim_phone_exchange, actor_id, audience_id):
            self._track(
                asyncio.create_task(
                    self._send_recorded_exchange(
                        phone_request,
                        self.store.release_phone_exchange,
                        conversation,
                        actor_id,
                        audience_id,
                        "phone",
                    ),
                    name="boss-phone-exchange",
                )
            )

    async def _send_recorded_exchange(
        self,
        request: Any,
        release: Any,
        conversation: Conversation,
        actor_id: str,
        audience_id: str,
        kind: str,
    ) -> None:
        try:
            await request(conversation)
        except Exception:
            await asyncio.to_thread(release, actor_id, audience_id)
            logger.exception("BOSS %s exchange request failed audience=%s", kind, audience_id)
            return
        logger.info("BOSS %s exchange requested audience=%s", kind, audience_id)

    async def _retry_downlink(self, record: DownlinkRecord, error: str) -> None:
        delay = self.RETRY_SECONDS[min(max(0, record.attempts - 1), len(self.RETRY_SECONDS) - 1)]
        await asyncio.to_thread(
            self.store.retry_downlink,
            record.client_msg_id,
            time.time() + delay,
            error,
        )

    @staticmethod
    def _is_retryable_exception(exc: Exception) -> bool:
        if isinstance(exc, (ValueError, TypeError, PermissionError, UnicodeEncodeError)):
            return False
        lowered = str(exc).lower()
        permanent = (
            "credential",
            "authentication",
            "unauthorized",
            "forbidden",
            "permission",
            "invalid_request",
            "发信缺少",
            "create failed",
            "create incomplete",
            "syntaxerror",
            "缺少 ')'",
            "javascript runtime",
            "runtimeunavailable",
        )
        return not any(token in lowered for token in permanent)

    async def _recover_unconfirmed_downlinks(self) -> None:
        recovered = await asyncio.to_thread(self.store.recover_claimed_downlinks)
        if recovered:
            logger.info("requeued %d downlink(s) that had not reached the platform", recovered)
        # Re-sending an unconfirmed platform attempt may duplicate a user
        # message, so persist a failure and let IM/user decide whether to retry.
        for record in await asyncio.to_thread(self.store.processing_downlinks):
            request = SendRequest(
                platform=record.platform,
                platform_actor_id=record.platform_actor_id,
                platform_audience_id=record.platform_audience_id,
                client_msg_id=record.client_msg_id,
                content_type=record.content_type,
                content=record.content,
            )
            await self._finish_failed(request, "previous_attempt_unconfirmed")

    def _conversation_from_record(self, record: ConversationRecord) -> Conversation:
        actor = self._require_actor()
        return Conversation(
            platform=actor.platform,
            platform_actor_id=actor.platform_actor_id,
            audience=Audience(
                platform_audience_id=record.platform_audience_id,
                username=record.audience_name,
                avatar=record.audience_avatar,
            ),
            platform_conversation_id=record.platform_conversation_id,
            platform_data=record.platform_data,
        )

    async def _finish_failed(
        self,
        request: SendRequest,
        error: str,
        sent_at_ms: int | None = None,
    ) -> dict[str, Any]:
        return await self._finish_status(
            request,
            self.config.send_status_failed,
            sent_at_ms=sent_at_ms or int(time.time() * 1000),
            error=error,
        )

    async def _finish_status(
        self,
        request: SendRequest,
        status: int,
        *,
        sent_at_ms: int,
        platform_message_id: str = "",
        error: str = "",
    ) -> dict[str, Any]:
        event = send_status_payload(
            platform=request.platform,
            client_msg_id=request.client_msg_id,
            status=status,
            actual_send_time=sent_at_ms,
        )
        await asyncio.to_thread(
            self.store.finish_downlink,
            request.client_msg_id,
            status=status,
            status_event=event,
            platform_message_id=platform_message_id,
            error=error,
        )
        return event

    def _require_actor(self) -> Actor:
        if self._actor is None:
            raise RuntimeError("Adapter Actor is not authenticated")
        return self._actor
