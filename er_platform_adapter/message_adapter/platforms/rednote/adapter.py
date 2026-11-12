"""Rednote private messages on the same adapter contract as Douyin and BOSS."""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from collections.abc import AsyncIterator
from typing import Any

from message_adapter.async_tools import run_in_daemon_thread
from message_adapter.core.models import Actor, Audience, BootstrapState, Conversation, Message, SendResult
from message_adapter.core.platform import PlatformAdapter, PlatformCapabilities

from .client import RednoteClient
from .credentials import RednoteCredential, load_rednote_cookie, save_rednote_cookie
from .im import account_summary, fetch_since, list_chats, uplink_content
from .im_ws import RednoteImSession, receive_messages_ws

logger = logging.getLogger(__name__)


def _millis(value: Any) -> int:
    try:
        stamp = int(value or 0)
    except (TypeError, ValueError):
        return 0
    if 0 < stamp < 1_000_000_000_000:
        return stamp * 1000
    return stamp


class RednotePlatformAdapter(PlatformAdapter):
    platform = "rednote"
    capabilities = PlatformCapabilities(
        text_receive=True,
        text_send=True,
        history_backfill=True,
        automatic_catch_up=False,
    )

    def __init__(self, *, credentials=None, browser_profile_root=None):
        del browser_profile_root
        self._credentials = credentials
        self._credential: RednoteCredential | None = None
        self._client: RednoteClient | None = None
        self._actor: Actor | None = None
        self._conversations: dict[str, Conversation] = {}
        self._queue: asyncio.Queue[Message | BaseException] = asyncio.Queue(maxsize=2000)
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._thread_stop = threading.Event()
        self._api_lock = threading.RLock()
        self._im = RednoteImSession()

    def _stored_credential(self) -> RednoteCredential | None:
        if self._credentials is None:
            return None
        data = self._credentials.get(self.platform)
        if not isinstance(data, dict):
            return None
        item = data.get("cookie")
        if not isinstance(item, dict) or not str(item.get("cookie") or "").strip():
            return None
        return RednoteCredential(
            cookie=str(item.get("cookie") or ""),
            name=str(item.get("name") or "rednote"),
            source=str(item.get("source") or "sqlite"),
            web_session=str(item.get("web_session") or ""),
            user_id=str(item.get("user_id") or ""),
            red_id=str(item.get("red_id") or ""),
            nickname=str(item.get("nickname") or ""),
            device_id=str(item.get("device_id") or ""),
            browser_profile=str(item.get("browser_profile") or ""),
        )

    def _device_id(self) -> str:
        assert self._credential is not None
        from .im_ws import stable_device_id

        uid = str(
            getattr(self._credential, "user_id", "")
            or (self._actor.platform_actor_id if self._actor else "")
            or ""
        ).strip()
        device_id = stable_device_id(uid)
        if getattr(self._credential, "device_id", "") == device_id:
            return device_id
        self._credential.device_id = device_id
        if self._credentials is not None and not self._credentials.read_only:
            save_rednote_cookie(
                self._credential.cookie,
                store=self._credentials,
                user_id=getattr(self._credential, "user_id", "") or uid,
                nickname=getattr(self._credential, "nickname", ""),
                red_id=getattr(self._credential, "red_id", ""),
                device_id=device_id,
                browser_profile=getattr(self._credential, "browser_profile", ""),
                source=getattr(self._credential, "source", "") or "sqlite",
            )
        return device_id

    def _enqueue_threadsafe(self, item: Message | BaseException) -> None:
        loop = self._loop
        if loop is None or loop.is_closed():
            return

        def schedule() -> None:
            asyncio.create_task(self._queue.put(item))

        loop.call_soon_threadsafe(schedule)

    def _conversation(self, chat_user_id: str, *, nickname: str = "", avatar: str = "") -> Conversation:
        assert self._actor is not None
        audience_id = str(chat_user_id or "").strip()
        existing = self._conversations.get(audience_id)
        if existing is not None and (not nickname or existing.audience.username == nickname):
            return existing
        conversation = Conversation(
            platform=self.platform,
            platform_actor_id=self._actor.platform_actor_id,
            audience=Audience(
                platform_audience_id=audience_id,
                username=nickname or (existing.audience.username if existing else audience_id),
                avatar=avatar or (existing.audience.avatar if existing else ""),
            ),
            platform_conversation_id=audience_id,
        )
        self._conversations[audience_id] = conversation
        return conversation

    def _mapped_message(
        self,
        *,
        chat_user_id: str,
        message_id: str,
        sent_at_ms: int,
        is_send: bool,
        mapped: dict[str, Any] | None,
        nickname: str = "",
        avatar: str = "",
        raw: dict[str, Any] | None = None,
    ) -> Message | None:
        if not mapped or not chat_user_id or not message_id:
            return None
        text = str(mapped.get("text") or "").strip()
        if not text:
            return None
        return Message(
            platform=self.platform,
            message_id=message_id,
            platform_message_id=message_id,
            conversation=self._conversation(chat_user_id, nickname=nickname, avatar=avatar),
            text=text,
            sent_at_ms=sent_at_ms or int(time.time() * 1000),
            is_send=is_send,
            content_type=int(mapped["content_type"]),
            content=mapped["content"],
            raw=raw or {},
        )

    def _message_from_http(self, raw: dict[str, Any], chat: dict[str, Any]) -> Message | None:
        assert self._actor is not None
        if raw.get("revoked"):
            return None
        sender = str(raw.get("sender_id") or "")
        info = chat.get("info") if isinstance(chat.get("info"), dict) else {}
        return self._mapped_message(
            chat_user_id=str(chat.get("chat_user_id") or ""),
            message_id=str(raw.get("id") or raw.get("uuid") or raw.get("store_id") or ""),
            sent_at_ms=_millis(raw.get("created_at")),
            is_send=sender == self._actor.platform_actor_id,
            mapped=uplink_content(raw.get("content")),
            nickname=str((info or {}).get("nickname") or (info or {}).get("user_name") or ""),
            avatar=str((info or {}).get("avatar") or ""),
            raw=raw,
        )

    def _message_from_push(self, raw: dict[str, Any]) -> Message | None:
        assert self._actor is not None
        if raw.get("revoked"):
            return None
        sender = str(raw.get("sender") or "")
        receiver = str(raw.get("receiver") or "")
        mine = self._actor.platform_actor_id
        outgoing = sender == mine
        peer = receiver if outgoing else sender
        return self._mapped_message(
            chat_user_id=peer,
            message_id=str(raw.get("message_id") or raw.get("client_uuid") or raw.get("store_id") or ""),
            sent_at_ms=_millis(raw.get("timestamp_ms")),
            is_send=outgoing,
            mapped=uplink_content(
                raw.get("raw_info") if raw.get("raw_info") is not None else raw.get("text"),
                raw_inner=raw.get("raw_inner"),
                raw_info=raw.get("raw_info"),
            ),
            nickname=str(raw.get("nickname") or "") if not outgoing else "",
            raw=raw,
        )

    async def authenticate(self) -> Actor:
        def work() -> tuple[RednoteCredential, dict[str, str]]:
            credential = self._stored_credential() or load_rednote_cookie(store=self._credentials)
            if not credential.is_valid:
                raise RuntimeError("小红书 cookie 无效，请重新扫码登录")
            client = RednoteClient(credential.cookie)
            summary = account_summary(client)
            return credential, summary

        credential, summary = await run_in_daemon_thread(work)
        uid = str(credential.user_id or summary.get("user_id") or "").strip()
        if not uid:
            raise RuntimeError("小红书登录没有取得稳定平台 UID，请重新扫码")
        credential.user_id = uid
        credential.nickname = credential.nickname or str(summary.get("nickname") or "")
        credential.red_id = credential.red_id or str(summary.get("red_id") or "")
        self._credential = credential
        self._client = RednoteClient(credential.cookie)
        self._actor = Actor(
            platform=self.platform,
            platform_actor_id=uid,
            username=credential.nickname or credential.name,
            avatar=str(summary.get("avatar") or ""),
        )
        return self._actor

    async def validate_identity(self, actor: Actor) -> None:
        if self._credentials is None:
            return
        bound = await asyncio.to_thread(self._credentials.get_bound_actor_id, self.platform)
        if bound and bound != actor.platform_actor_id:
            raise RuntimeError(
                f"小红书凭证已绑定 platform_actor_id={bound}；当前登录 UID={actor.platform_actor_id}"
            )

    async def persist_identity(self, actor: Actor) -> None:
        if self._credentials is None or self._credentials.read_only or self._credential is None:
            return
        await asyncio.to_thread(
            save_rednote_cookie,
            self._credential.cookie,
            store=self._credentials,
            user_id=actor.platform_actor_id,
            nickname=self._credential.nickname,
            red_id=self._credential.red_id,
            device_id=self._credential.device_id,
            browser_profile=self._credential.browser_profile,
            source=self._credential.source or "sqlite",
        )

    async def bootstrap(self) -> BootstrapState:
        return BootstrapState(cursor=str(int(time.time() * 1000)))

    def _messages_since(self, since_ms: int) -> list[Message]:
        assert self._client is not None
        found: list[Message] = []
        with self._api_lock:
            chats = list(list_chats(self._client, limit=100).get("chats") or [])
            for chat in chats:
                if not isinstance(chat, dict):
                    continue
                peer = str(chat.get("chat_user_id") or "")
                max_store = int(chat.get("max_store_id") or 0)
                if not peer or max_store <= 0:
                    continue
                for raw in fetch_since(
                    self._client,
                    peer,
                    since_store_id=max(0, max_store - 40),
                    max_store_id=max_store,
                ):
                    message = self._message_from_http(raw, chat)
                    if message and message.sent_at_ms > since_ms:
                        found.append(message)
        found.sort(key=lambda item: item.sent_at_ms)
        return found

    def _recover_gap(self, since_ms: int) -> None:
        """Pull messages that arrived while the live socket was down."""
        try:
            messages = self._messages_since(since_ms)
        except Exception:
            logger.warning("rednote gap recovery failed", exc_info=True)
            return
        for message in messages:
            self._enqueue_threadsafe(message)
        if messages:
            logger.info("rednote recovered messages count=%s", len(messages))

    def _run_ws(self) -> None:
        assert self._credential is not None and self._actor is not None
        reconnect = 2.0
        connected = False
        while not self._thread_stop.is_set():
            try:
                device_id = self._device_id()
                for raw in receive_messages_ws(
                    self._credential.cookie,
                    self._actor.platform_actor_id,
                    device_id=device_id,
                    stop=self._thread_stop,
                    session=self._im,
                ):
                    message = self._message_from_push(raw)
                    if message:
                        self._enqueue_threadsafe(message)
                if self._thread_stop.is_set():
                    return
                logger.warning("rednote im ws closed, reconnecting")
            except BaseException as exc:
                logger.warning("rednote ws failed: %s", exc, exc_info=True)
            lost_ms = int(time.time() * 1000)
            if connected:
                self._recover_gap(max(0, lost_ms - 60_000))
            connected = True
            self._thread_stop.wait(reconnect)
            reconnect = min(30.0, reconnect * 2)

    async def stream_messages(self) -> AsyncIterator[Message]:
        if self._actor is None:
            raise RuntimeError("authenticate must run before stream_messages")
        self._loop = asyncio.get_running_loop()
        self._thread = threading.Thread(target=self._run_ws, name="adapter-xhs-ws", daemon=True)
        self._thread.start()
        while not self._thread_stop.is_set():
            item = await self._queue.get()
            if isinstance(item, BaseException):
                raise item
            yield item

    async def catch_up(self, cursor: str) -> list[Message]:
        since = _millis(cursor)
        return await run_in_daemon_thread(lambda: self._messages_since(since))

    async def resolve_conversation(self, platform_audience_id: str) -> Conversation | None:
        audience_id = str(platform_audience_id or "").strip()
        if not audience_id:
            return None

        def work() -> Conversation:
            assert self._client is not None and self._actor is not None
            nickname = ""
            avatar = ""
            with self._api_lock:
                chats = list(list_chats(self._client, limit=100).get("chats") or [])
            for chat in chats:
                if not isinstance(chat, dict):
                    continue
                if str(chat.get("chat_user_id") or "") != audience_id:
                    continue
                info = chat.get("info") if isinstance(chat.get("info"), dict) else {}
                nickname = str(info.get("nickname") or info.get("user_name") or "")
                avatar = str(info.get("avatar") or "")
                break
            return self._conversation(audience_id, nickname=nickname, avatar=avatar)

        return await run_in_daemon_thread(work)

    async def send_text(self, conversation: Conversation, text: str) -> SendResult:
        def work() -> SendResult:
            assert self._credential is not None and self._actor is not None
            result = self._im.send_text(
                self._actor.platform_actor_id,
                conversation.audience.platform_audience_id,
                text,
                self._actor.username,
            )
            message_id = str(result.get("message_id") or "").strip()
            ok = bool(result.get("ok")) and bool(message_id)
            error = "" if ok else "小红书发送未确认"
            retryable = not ok and str(result.get("error") or "") in {
                "not connected",
                "send timeout",
                "socket closed",
            }
            return SendResult(
                success=ok,
                sent_at_ms=int(time.time() * 1000),
                platform_message_id=message_id,
                error=error,
                retryable=retryable,
                conversation_id=conversation.platform_conversation_id,
            )

        return await run_in_daemon_thread(work)

    async def close(self) -> None:
        self._thread_stop.set()
        threads = [thread for thread in (self._thread,) if thread and thread.is_alive()]
        if threads:
            await asyncio.gather(*(asyncio.to_thread(thread.join, 2.0) for thread in threads))
