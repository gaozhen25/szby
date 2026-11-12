from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import threading
import time
from collections.abc import AsyncIterator
from typing import Any

from message_adapter.async_tools import run_in_daemon_thread
from .credentials import DouyinCredential, load_douyin_cookie, save_douyin_cookie
from .protocol import (
    ImAuth,
    account_summary,
    create_conversation,
    list_conversations,
    im_uplink_content,
    load_auth,
    peer_profile_for_conversation,
    peer_uid_from_conversation,
    send_text,
)
from .websocket import resolve_device_id, run_im_ws_loop
from message_adapter.core.models import Actor, Audience, BootstrapState, Conversation, Message, SendResult
from message_adapter.core.platform import PlatformAdapter, PlatformCapabilities

logger = logging.getLogger(__name__)


class DouyinPlatformAdapter(PlatformAdapter):
    platform = "douyin"
    capabilities = PlatformCapabilities(history_backfill=False, automatic_catch_up=False)

    def __init__(self, *, credentials=None):
        self._credentials = credentials
        self._credential: DouyinCredential | None = None
        self._auth: ImAuth | None = None
        self._actor: Actor | None = None
        self._conversations: dict[str, Conversation] = {}
        self._queue: asyncio.Queue[Message | BaseException] = asyncio.Queue(maxsize=2000)
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._thread_stop = threading.Event()
        self._api_lock = threading.RLock()

    def _stored_credential(self) -> tuple[DouyinCredential, dict[str, Any]] | None:
        if self._credentials is None:
            return None
        data = self._credentials.get(self.platform)
        if not isinstance(data, dict):
            return None
        item = data.get("cookie")
        if not isinstance(item, dict) or not str(item.get("cookie") or "").strip():
            return None
        credential = DouyinCredential(
            cookie=str(item.get("cookie") or ""),
            name=str(item.get("name") or "douyin"),
            source="sqlite",
            sessionid=str(item.get("sessionid") or ""),
            uid=str(item.get("uid") or ""),
            unique_id=str(item.get("unique_id") or ""),
            nickname=str(item.get("nickname") or ""),
            sec_uid=str(item.get("sec_uid") or ""),
            browser_profile=str(item.get("browser_profile") or ""),
        )
        im = data.get("im") if isinstance(data.get("im"), dict) else {}
        return credential, im

    def _enqueue_threadsafe(self, item: Message | BaseException) -> None:
        loop = self._loop
        if loop is None or loop.is_closed():
            return

        def schedule() -> None:
            asyncio.create_task(self._queue.put(item))

        loop.call_soon_threadsafe(schedule)

    @staticmethod
    def _stable_message_id(raw: dict[str, Any]) -> str:
        server_id = str(raw.get("server_message_id") or "").strip()
        if server_id:
            return server_id
        index = str(raw.get("index_in_conversation") or "").strip()
        conversation_id = str(raw.get("conversation_id") or "").strip()
        return f"{conversation_id}:{index}" if conversation_id and index else ""

    async def authenticate(self) -> Actor:
        def work() -> tuple[DouyinCredential, ImAuth, dict[str, str]]:
            stored = self._stored_credential()
            credential = (
                stored[0]
                if stored
                else load_douyin_cookie(store=self._credentials)
            )
            im = stored[1] if stored else {}
            auth = load_auth(
                cookie=credential.cookie,
                account_name=credential.name,
                uid=credential.uid,
                send_credential=im,
            )
            summary = account_summary(auth)
            return credential, auth, summary

        credential, auth, summary = await run_in_daemon_thread(work)
        uid = str(credential.uid or summary.get("uid") or "").strip()
        if not uid:
            raise RuntimeError("Douyin credential has no stable uid; rerun: adapter douyin login")
        auth.uid = uid
        self._credential = credential
        self._auth = auth
        self._actor = Actor(
            platform=self.platform,
            platform_actor_id=uid,
            username=str(credential.nickname or summary.get("nickname") or credential.name),
            avatar=str(summary.get("avatar") or ""),
        )
        return self._actor

    async def validate_identity(self, actor: Actor) -> None:
        if self._credentials is None:
            return
        bound = await asyncio.to_thread(self._credentials.get_bound_actor_id, self.platform)
        if bound and bound != actor.platform_actor_id:
            raise RuntimeError(
                f"Douyin credential is bound to platform_actor_id={bound}; authenticated UID={actor.platform_actor_id}"
            )

    async def persist_identity(self, actor: Actor) -> None:
        if self._credentials is not None and not self._credentials.read_only:
            existing = await asyncio.to_thread(self._credentials.get, self.platform)
            if existing is None and self._credential is not None:
                await asyncio.to_thread(
                    save_douyin_cookie,
                    self._credential.cookie,
                    store=self._credentials,
                    name=self._credential.name,
                    source=self._credential.source,
                    uid=actor.platform_actor_id,
                    unique_id=self._credential.unique_id,
                    nickname=self._credential.nickname,
                    sec_uid=self._credential.sec_uid,
                    browser_profile=self._credential.browser_profile,
                )
            else:
                await asyncio.to_thread(self._credentials.bind_actor, self.platform, actor.platform_actor_id)

    def _conversation_from_raw(
        self,
        raw: dict[str, Any],
        messages: list[dict[str, Any]] | None = None,
        *,
        fetch_profile: bool = True,
    ) -> Conversation:
        assert self._actor is not None and self._auth is not None
        cid = str(raw.get("conversation_id") or "")
        peer_uid = peer_uid_from_conversation(cid, self._actor.platform_actor_id)
        profile: dict[str, Any] = {"uid": peer_uid, "nickname": peer_uid, "unique_id": "", "avatar": ""}
        # Live WebSocket callbacks must not do HTTP: the receive loop is blocked
        # until on_message returns, and a slow profile lookup trips keepalive
        # ping timeout so the socket dies after the first inbound message.
        if fetch_profile:
            try:
                profile = peer_profile_for_conversation(self._auth, cid, messages or [])
            except Exception:
                logger.debug("douyin peer profile unavailable cid=%s", cid, exc_info=True)
        conversation = Conversation(
            platform=self.platform,
            platform_actor_id=self._actor.platform_actor_id,
            audience=Audience(
                platform_audience_id=peer_uid,
                username=str(profile.get("nickname") or profile.get("unique_id") or peer_uid),
                avatar=str(profile.get("avatar") or ""),
            ),
            platform_conversation_id=cid,
            platform_data={
                "conversation_short_id": int(raw.get("conversation_short_id") or 0),
                "conversation_ticket": str(raw.get("conversation_ticket") or ""),
                "peer_uid": peer_uid,
            },
        )
        self._conversations[cid] = conversation
        return conversation

    def _message_from_raw(self, raw: dict[str, Any]) -> Message | None:
        assert self._actor is not None and self._auth is not None
        cid = str(raw.get("conversation_id") or "")
        if not cid:
            return None
        uplink = im_uplink_content(raw)
        if uplink is None:
            return None
        conversation = self._conversations.get(cid) or self._conversation_from_raw(
            raw,
            [raw],
            fetch_profile=False,
        )
        text = str(uplink["text"] or "").strip()
        if not text:
            return None
        platform_mid = str(raw.get("server_message_id") or "")
        mid = self._stable_message_id(raw)
        if not mid:
            mid = hashlib.sha256(
                json.dumps([cid, raw.get("sender"), raw.get("create_time_ms"), text], ensure_ascii=False).encode()
            ).hexdigest()
        return Message(
            platform=self.platform,
            message_id=mid,
            platform_message_id=platform_mid,
            conversation=conversation,
            text=text,
            sent_at_ms=int(raw.get("create_time_ms") or time.time() * 1000),
            is_send=str(raw.get("sender") or "") == self._actor.platform_actor_id,
            content_type=int(uplink["content_type"]),
            content=uplink["content"],
            raw=raw,
        )

    async def bootstrap(self) -> BootstrapState:
        # Deliberately do not read conversation history here.  The Frontier
        # WebSocket is started before bootstrap, and the runtime timestamp
        # baseline discards any stale frames delivered during first startup.
        return BootstrapState(
            cursor=str(int(time.time() * 1000)),
        )

    def _run_ws(self) -> None:
        assert self._auth is not None and self._credential is not None and self._loop is not None
        reconnect = 2.0
        while not self._thread_stop.is_set():
            try:
                device_id = resolve_device_id(self._auth)

                def emit(raw: dict[str, Any]) -> None:
                    # Do not take _api_lock here: send_text / resolve hold it for
                    # HTTP, and blocking the WS receive callback trips ping timeout.
                    message = self._message_from_raw(raw)
                    if message:
                        self._enqueue_threadsafe(message)

                def on_connected() -> None:
                    nonlocal reconnect
                    reconnect = 2.0

                error: list[str] = []
                run_im_ws_loop(
                    self._auth,
                    device_id=device_id,
                    cookie_str=self._credential.cookie,
                    on_message=emit,
                    stop=self._thread_stop,
                    on_connected=on_connected,
                    on_disconnected=error.append,
                )
                if self._thread_stop.is_set():
                    return
                if error:
                    logger.warning("douyin ws disconnected: %s", error[-1])
            except BaseException as exc:
                logger.warning("douyin ws failed: %s", exc, exc_info=True)
            self._thread_stop.wait(reconnect)
            reconnect = min(30.0, reconnect * 2)

    async def stream_messages(self) -> AsyncIterator[Message]:
        if self._actor is None:
            raise RuntimeError("authenticate must run before stream_messages")
        self._loop = asyncio.get_running_loop()
        self._thread = threading.Thread(target=self._run_ws, name="adapter-douyin-ws", daemon=True)
        self._thread.start()
        while not self._thread_stop.is_set():
            item = await self._queue.get()
            if isinstance(item, BaseException):
                raise item
            yield item

    async def catch_up(self, cursor: str) -> list[Message]:
        # Douyin history backfill is intentionally disabled to avoid a burst of
        # private API calls across every conversation.  Only live WebSocket
        # events enter the adapter.
        del cursor
        return []

    async def resolve_conversation(self, platform_audience_id: str) -> Conversation | None:
        audience_id = str(platform_audience_id or "").strip()
        if not audience_id:
            return None
        # Upstream sometimes sends campaign / reply tokens (e.g. easy_reply_…)
        # instead of a Douyin UID. Fail fast — never scrape inbox or int().
        if not audience_id.isdigit():
            raise ValueError(
                f"抖音 platform_audience_id 必须是数字 UID，收到: {audience_id!r}"
            )

        def work() -> Conversation | None:
            assert self._auth is not None and self._actor is not None
            with self._api_lock:
                for raw in list_conversations(self._auth, page_size=50, max_pages=10):
                    cid = str(raw.get("conversation_id") or "")
                    if cid and peer_uid_from_conversation(cid, self._actor.platform_actor_id) == audience_id:
                        return self._conversation_from_raw(raw)
                cid, short_id, ticket = create_conversation(self._auth, audience_id)
                if not cid or not short_id:
                    return None
                return self._conversation_from_raw(
                    {
                        "conversation_id": cid,
                        "conversation_short_id": short_id,
                        "conversation_ticket": ticket,
                    }
                )

        return await run_in_daemon_thread(work)

    async def send_text(self, conversation: Conversation, text: str) -> SendResult:
        def work() -> SendResult:
            assert self._auth is not None
            actor_id = self._actor.platform_actor_id if self._actor is not None else conversation.platform_actor_id
            logger.info(
                "Douyin send started platform_actor_id=%s platform_audience_id=%s "
                "conversation_id=%s content_length=%d",
                actor_id,
                conversation.audience.platform_audience_id,
                conversation.platform_conversation_id,
                len(text),
            )
            logger.debug(
                "Douyin send content platform_actor_id=%s platform_audience_id=%s content=%s",
                actor_id,
                conversation.audience.platform_audience_id,
                text,
            )
            with self._api_lock:
                result = send_text(
                    self._auth,
                    text,
                    conversation_id=conversation.platform_conversation_id,
                    conversation_short_id=int(conversation.platform_data.get("conversation_short_id") or 0),
                    conversation_ticket=str(conversation.platform_data.get("conversation_ticket") or ""),
                    to_user_id=conversation.audience.platform_audience_id,
                )
            ticket = str(result.get("conversation_ticket") or "")
            cid = str(result.get("conversation_id") or conversation.platform_conversation_id or "")
            short_id = int(result.get("conversation_short_id") or conversation.platform_data.get("conversation_short_id") or 0)
            if cid and ticket:
                updated = Conversation(
                    platform=conversation.platform,
                    platform_actor_id=conversation.platform_actor_id,
                    audience=conversation.audience,
                    platform_conversation_id=cid,
                    platform_data={
                        **conversation.platform_data,
                        "conversation_short_id": short_id,
                        "conversation_ticket": ticket,
                    },
                )
                self._conversations[cid] = updated
            sid = str(result.get("server_message_id") or "").strip()
            ok = bool(result.get("ok")) and bool(sid)
            err = str(result.get("error_desc") or result.get("message") or "")
            if bool(result.get("ok")) and not sid and not err:
                err = "发送未拿到 server_message_id（疑似未真正投递）"
            send_result = SendResult(
                success=ok,
                sent_at_ms=int(time.time() * 1000),
                platform_message_id=sid,
                error=err,
                conversation_id=cid,
                conversation_short_id=short_id,
                conversation_ticket=ticket,
            )
            logger.info(
                "Douyin send completed platform_actor_id=%s platform_audience_id=%s "
                "conversation_id=%s success=%s platform_message_id=%s error=%s",
                actor_id,
                conversation.audience.platform_audience_id,
                conversation.platform_conversation_id,
                send_result.success,
                send_result.platform_message_id,
                send_result.error,
            )
            return send_result

        return await run_in_daemon_thread(work)

    async def close(self) -> None:
        self._thread_stop.set()
        threads = [thread for thread in (self._thread,) if thread and thread.is_alive()]
        if threads:
            await asyncio.gather(*(asyncio.to_thread(thread.join, 2.0) for thread in threads))
