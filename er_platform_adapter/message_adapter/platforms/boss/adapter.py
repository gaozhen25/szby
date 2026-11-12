from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import threading
import time
from collections import OrderedDict
from collections.abc import AsyncIterator
from typing import Any

from message_adapter.browser_profiles import BrowserProfile
from message_adapter.async_tools import run_in_daemon_thread
from message_adapter.core.models import Actor, Audience, BootstrapState, Conversation, Message, SendResult
from message_adapter.core.platform import PlatformAdapter, PlatformCapabilities

from .auth import Credential, get_credential
from .client import BossClient
from .exchange import (
    ExchangeAcceptType,
    ExchangeContext,
    ExchangeResult,
    ExchangeType,
    PendingExchangeRequest,
    exchange_context_from_friend,
    find_pending_exchange_request,
)
from .mapping import history_message, mqtt_is_mine
from .mqtt import IDENTITY_BOSS, run_mqtt_listen

logger = logging.getLogger(__name__)
_SEEN_MESSAGE_LIMIT = 20000


def _time_ms(value: Any) -> int:
    try:
        raw = int(value or 0)
    except (TypeError, ValueError):
        return int(time.time() * 1000)
    return raw if raw > 10_000_000_000 else raw * 1000


class BossPlatformAdapter(PlatformAdapter):
    """Recruiter-side BOSS adapter wrapping the proven HTTP/MQTT engine."""

    platform = "boss"
    capabilities = PlatformCapabilities(wechat_exchange=True, automatic_catch_up=False)

    def __init__(
        self,
        *,
        credentials=None,
        browser_profile: BrowserProfile | None = None,
    ):
        self._credentials = credentials
        self._browser_profile = browser_profile
        self._credential: Credential | None = None
        self._actor: Actor | None = None
        self._user_info: dict[str, Any] = {}
        self._peers: dict[str, dict[str, Any]] = {}
        self._queue: asyncio.Queue[Message | BaseException] = asyncio.Queue(maxsize=2000)
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._thread_stop = threading.Event()
        self._peers_ready = threading.Event()
        self._seen_ids: OrderedDict[str, None] = OrderedDict()
        self._seen_lock = threading.Lock()
        self._listen_started_ms = 0
        self._recovery_since_ms = 0
        self._live_chat = None
        self._live_chat_lock = threading.Lock()

    def _stored_credential(self) -> Credential | None:
        if self._credentials is None:
            return None
        data = self._credentials.get(self.platform)
        if not isinstance(data, dict) or not isinstance(data.get("cookies"), dict):
            return None
        credential = Credential.from_dict(data)
        return credential if credential.is_valid else None

    def _enqueue_threadsafe(self, item: Message | BaseException) -> None:
        loop = self._loop
        if loop is None or loop.is_closed():
            return

        def schedule() -> None:
            asyncio.create_task(self._queue.put(item))

        loop.call_soon_threadsafe(schedule)

    async def authenticate(self) -> Actor:
        def work() -> tuple[Credential, dict[str, Any]]:
            credential = self._stored_credential() or get_credential(
                store=self._credentials,
            )
            if credential is None:
                raise RuntimeError("BOSS credential missing; run: adapter boss login")
            with BossClient(credential) as client:
                _, _, info = client.get_ws_auth()
            return credential, info

        credential, info = await run_in_daemon_thread(work)
        uid = str(info.get("userId") or info.get("uid") or "").strip()
        if not uid:
            raise RuntimeError("BOSS authenticated response has no stable userId")
        self._credential = credential
        self._user_info = info
        self._actor = Actor(
            platform=self.platform,
            platform_actor_id=uid,
            username=str(info.get("name") or info.get("userName") or info.get("showName") or ""),
            avatar=str(info.get("avatar") or info.get("tinyUrl") or info.get("face") or ""),
        )
        return self._actor

    async def validate_identity(self, actor: Actor) -> None:
        if self._credentials is None:
            return
        bound = await asyncio.to_thread(self._credentials.get_bound_actor_id, self.platform)
        if bound and bound != actor.platform_actor_id:
            raise RuntimeError(
                f"BOSS credential is bound to platform_actor_id={bound}; authenticated UID={actor.platform_actor_id}"
            )

    async def persist_identity(self, actor: Actor) -> None:
        if self._credentials is not None and not self._credentials.read_only:
            await asyncio.to_thread(self._credentials.bind_actor, self.platform, actor.platform_actor_id)

    def _load_conversations_sync(self, *, baseline: bool) -> tuple[list[Conversation], set[str]]:
        assert self._credential is not None and self._actor is not None
        conversations: list[Conversation] = []
        baseline_ids: set[str] = set()
        with BossClient(self._credential) as client:
            listed = client.get_boss_friend_list().get("result") or []
            friend_ids = [int(x["friendId"]) for x in listed if x.get("friendId")]
            details = client.get_boss_friend_details(friend_ids).get("friendList") or listed
            last_messages = client.get_boss_last_messages(friend_ids) if baseline else []
        for friend in details:
            uid = str(friend.get("uid") or friend.get("friendId") or "").strip()
            if not uid:
                continue
            friend_id = str(friend.get("friendId") or uid)
            self._peers[uid] = dict(friend)
            self._peers[friend_id] = dict(friend)
            conversations.append(self._conversation(friend))
        for item in last_messages:
            raw = item.get("lastMsgInfo") or item
            mid = str(raw.get("mid") or raw.get("msgId") or raw.get("messageId") or "")
            if mid:
                baseline_ids.add(mid)
        return conversations, baseline_ids

    async def bootstrap(self) -> BootstrapState:
        try:
            conversations, baseline = await run_in_daemon_thread(self._load_conversations_sync, baseline=True)
        finally:
            # Friend details are filled in the background. Live MQTT callbacks
            # do not wait for this map.
            self._peers_ready.set()
        return BootstrapState(
            cursor=str(int(time.time() * 1000)),
            conversations=tuple(conversations),
            baseline_message_ids=frozenset(baseline),
        )

    @staticmethod
    def _peer_encrypt_id(peer: dict[str, Any]) -> str:
        return str(peer.get("encryptGeekId") or peer.get("encryptUid") or peer.get("encryptFriendId") or "").strip()

    def _remember_friend(self, friend: dict[str, Any]) -> dict[str, Any]:
        record = dict(friend)
        uid = str(record.get("uid") or record.get("friendId") or "").strip()
        friend_id = str(record.get("friendId") or uid).strip()
        if uid and not record.get("uid"):
            record["uid"] = uid
        if friend_id and not record.get("friendId"):
            record["friendId"] = friend_id
        if uid:
            self._peers[uid] = record
        if friend_id and friend_id != uid:
            self._peers[friend_id] = record
        return record

    def _friend_with_encrypt_id(self, audience_id: str) -> dict[str, Any] | None:
        """Return a friend record that can be used to send, loading it when the cache has none."""
        key = str(audience_id or "").strip()
        if not key:
            return None
        cached = self._peers.get(key)
        if isinstance(cached, dict) and self._peer_encrypt_id(cached):
            return cached
        if self._credential is None:
            return cached if isinstance(cached, dict) else None
        try:
            friend_id = int(key)
        except (TypeError, ValueError):
            return cached if isinstance(cached, dict) else None
        with BossClient(self._credential) as client:
            details = client.get_boss_friend_details([friend_id]).get("friendList") or []
        if not details:
            return cached if isinstance(cached, dict) else None
        friend = dict(details[0])
        if not friend.get("uid"):
            friend["uid"] = friend_id
        if not friend.get("friendId"):
            friend["friendId"] = friend_id
        return self._remember_friend(friend)

    def _conversation(self, peer: dict[str, Any]) -> Conversation:
        assert self._actor is not None
        uid = str(peer.get("uid") or peer.get("friendId") or "")
        friend_id = str(peer.get("friendId") or uid)
        return Conversation(
            platform=self.platform,
            platform_actor_id=self._actor.platform_actor_id,
            audience=Audience(
                platform_audience_id=uid,
                username=str(peer.get("name") or peer.get("geekName") or ""),
                avatar=str(peer.get("avatar") or peer.get("tinyUrl") or ""),
                remark=str(peer.get("jobName") or ""),
            ),
            platform_conversation_id=friend_id,
            platform_data={
                "friend_id": friend_id,
                "uid": uid,
                "friend_source": int(peer.get("friendSource") or 0),
                "encrypt_geek_id": str(peer.get("encryptGeekId") or peer.get("encryptUid") or peer.get("encryptFriendId") or ""),
                "job_id": str(peer.get("jobId") or ""),
            },
        )

    @staticmethod
    def _conversation_friend_id(conversation: Conversation) -> int:
        friend_id = str(conversation.platform_data.get("friend_id") or conversation.platform_conversation_id)
        try:
            return int(friend_id)
        except (TypeError, ValueError) as exc:
            raise RuntimeError(f"BOSS exchange requires a numeric friendId, got {friend_id!r}") from exc

    @classmethod
    def _fresh_exchange_context(cls, client: BossClient, conversation: Conversation) -> ExchangeContext:
        friend_id = cls._conversation_friend_id(conversation)
        details = client.get_boss_friend_details([friend_id]).get("friendList") or []
        if not details:
            raise RuntimeError(f"BOSS conversation no longer exists: friendId={friend_id}")
        return exchange_context_from_friend(
            details[0],
            fallback_friend_id=str(friend_id),
            fallback_audience_id=conversation.audience.platform_audience_id,
        )

    @staticmethod
    def _conversation_audience_id(conversation: Conversation) -> int:
        try:
            audience_id = int(conversation.platform_data.get("uid") or conversation.audience.platform_audience_id)
        except (TypeError, ValueError) as exc:
            raise RuntimeError("BOSS conversation has an invalid audience uid") from exc
        if not audience_id:
            raise RuntimeError("BOSS conversation has no audience uid")
        return audience_id

    def _message_from_live(self, payload: dict[str, Any]) -> Message | None:
        assert self._actor is not None
        if int(payload.get("message_type") or 0) not in (0, 1):
            return None
        mine = mqtt_is_mine(
            from_uid=int(payload.get("uid") or 0),
            to_uid=int(payload.get("to_uid") or 0),
            flag=int(payload.get("flag") or 0),
            my_uid=int(self._actor.platform_actor_id),
            from_name=str(payload.get("from_name") or ""),
            my_encrypt=str(self._user_info.get("encryptUserId") or ""),
            my_name=self._actor.username,
        )
        peer_uid = str(payload.get("to_uid") if mine else payload.get("uid") or "").strip()
        if not peer_uid:
            return None
        # Friend HTTP stays off the MQTT thread. A missing cache entry still
        # becomes a live message; send and background bootstrap fill details.
        peer = self._peers.get(peer_uid)
        if not isinstance(peer, dict):
            peer = {"uid": peer_uid, "friendId": peer_uid, "name": payload.get("name")}
        conversation = self._conversation(peer)
        mid = str(payload.get("mid") or "")
        if not mid:
            material = json.dumps(
                [conversation.platform_conversation_id, payload.get("timestamp_ms"), payload.get("text"), mine],
                ensure_ascii=False,
            )
            mid = hashlib.sha256(material.encode()).hexdigest()
        return Message(
            platform=self.platform,
            message_id=mid,
            platform_message_id=str(payload.get("mid") or ""),
            conversation=conversation,
            text=str(payload.get("text") or ""),
            sent_at_ms=_time_ms(payload.get("timestamp_ms")),
            is_send=mine,
            raw=payload,
        )

    def _claim_message(self, message_id: str) -> bool:
        message_id = str(message_id or "")
        if not message_id:
            return False
        with self._seen_lock:
            if message_id in self._seen_ids:
                self._seen_ids.move_to_end(message_id)
                return False
            self._seen_ids[message_id] = None
            while len(self._seen_ids) > _SEEN_MESSAGE_LIMIT:
                self._seen_ids.popitem(last=False)
            return True

    def _emit_once(self, message: Message, *, recovered: bool = False) -> None:
        if self._loop is None or self._loop.is_closed():
            return
        if not self._claim_message(message.message_id):
            return
        if recovered:
            logger.info(
                "BOSS recovered missed message audience=%s message_id=%s",
                message.conversation.audience.platform_audience_id,
                message.message_id,
            )
        self._enqueue_threadsafe(message)

    def _recover_missed_messages(self) -> None:
        """Pull chat history for conversations whose latest message was not seen live."""
        if self._credential is None or self._actor is None:
            return
        if not self._peers_ready.wait(timeout=30):
            logger.warning("BOSS history recovery skipped; friend list was not ready")
            return
        since = self._recovery_since_ms or self._listen_started_ms
        try:
            with BossClient(self._credential, request_delay=0.2) as client:
                listed = client.get_boss_friend_list().get("result") or []
                friend_ids = [int(item["friendId"]) for item in listed if item.get("friendId")]
                if not friend_ids:
                    return
                pending: list[tuple[dict[str, Any], str]] = []
                seen_peers: set[str] = set()
                for item in client.get_boss_last_messages(friend_ids):
                    if not isinstance(item, dict):
                        continue
                    info = item.get("lastMsgInfo") if isinstance(item.get("lastMsgInfo"), dict) else {}
                    message_id = str(info.get("msgId") or info.get("mid") or "")
                    if message_id and message_id in self._seen_ids:
                        continue
                    sent_at_ms = _time_ms(info.get("msgTime") or item.get("lastTS"))
                    if sent_at_ms and since and sent_at_ms < since:
                        if message_id:
                            self._claim_message(message_id)
                        continue
                    uid = str(item.get("uid") or info.get("fromId") or "").strip()
                    if not uid or uid in seen_peers:
                        continue
                    seen_peers.add(uid)
                    peer = self._peers.get(uid)
                    if not isinstance(peer, dict):
                        details = client.get_boss_friend_details([int(uid)]).get("friendList") or []
                        peer = self._remember_friend(details[0]) if details else {"uid": uid, "friendId": uid}
                    pending.append((peer, message_id))
                recovered: list[Message] = []
                covered_ids: list[str] = []
                for peer, message_id in pending:
                    messages, covered = self._history_since(client, peer, since)
                    recovered.extend(messages)
                    if covered and message_id:
                        covered_ids.append(message_id)
        except Exception:
            logger.warning("BOSS history recovery failed", exc_info=True)
            return
        for message in sorted(recovered, key=lambda item: (item.sent_at_ms, item.message_id)):
            if message.is_send:
                self._claim_message(message.message_id)
                continue
            self._emit_once(message, recovered=True)
        for message_id in covered_ids:
            self._claim_message(message_id)

    def _history_since(self, client: BossClient, peer: dict[str, Any], since: int) -> tuple[list[Message], bool]:
        raw_id = str(peer.get("friendId") or peer.get("uid") or "").strip()
        try:
            friend_id = int(raw_id)
        except (TypeError, ValueError):
            return [], False
        found: list[Message] = []
        max_message_id = 0
        covered = False
        for _ in range(5):
            data = client.get_boss_chat_history(friend_id, count=50, max_message_id=max_message_id)
            raws = [item for item in (data.get("messages") or data.get("messageList") or []) if isinstance(item, dict)]
            if not raws:
                break
            covered = True
            oldest_id = 0
            reached_older = False
            for raw in raws:
                message = self._history_message(raw, peer)
                try:
                    mid = int(raw.get("mid") or raw.get("msgId") or 0)
                except (TypeError, ValueError):
                    mid = 0
                if mid and (oldest_id == 0 or mid < oldest_id):
                    oldest_id = mid
                if message is None:
                    continue
                if since and message.sent_at_ms < since:
                    reached_older = True
                    continue
                if message.message_id in self._seen_ids:
                    continue
                found.append(message)
            if reached_older or len(raws) < 50 or not oldest_id or oldest_id == max_message_id:
                break
            max_message_id = oldest_id
        return found, covered

    def _run_mqtt(self) -> None:
        assert self._credential is not None and self._actor is not None and self._loop is not None
        try:
            with BossClient(self._credential) as client:
                page_token, wt2, info = client.get_ws_auth()
                cookies = client.session_cookies()

            def emit(payload: dict[str, Any]) -> None:
                message = self._message_from_live(payload)
                if message:
                    self._emit_once(message)

            def reconnect():
                with BossClient(self._credential) as client:
                    token, secret, info = client.get_ws_auth()
                    return token, secret, client.session_cookies(), info.get("userId")

            # Sending opens no second socket: a new MQTT login kicks this one
            # off and the server does not replay what arrived in the gap.
            # Live receive does not scan chat history before reading MQTT frames.
            run_mqtt_listen(
                page_token=page_token,
                wt2=wt2,
                cookies=cookies,
                my_uid=int(self._actor.platform_actor_id),
                identity=IDENTITY_BOSS,
                duration=0,
                show_all=True,
                backlog=False,
                on_message=emit,
                on_session=self._bind_live_chat,
                on_reconnect=reconnect,
                stop_event=self._thread_stop,
            )
        except BaseException as exc:
            if not self._thread_stop.is_set():
                self._enqueue_threadsafe(exc)

    async def stream_messages(self) -> AsyncIterator[Message]:
        if self._actor is None:
            raise RuntimeError("authenticate must run before stream_messages")
        self._loop = asyncio.get_running_loop()
        self._thread = threading.Thread(target=self._run_mqtt, name="adapter-boss-mqtt", daemon=True)
        self._thread.start()
        while not self._thread_stop.is_set():
            item = await self._queue.get()
            if isinstance(item, BaseException):
                raise item
            yield item

    def _history_message(self, raw: dict[str, Any], peer: dict[str, Any]) -> Message | None:
        assert self._actor is not None
        parsed = history_message(
            raw,
            my_uid=int(self._actor.platform_actor_id),
            peer_uid=int(peer.get("uid") or peer.get("friendId") or 0),
        )
        text = str(parsed.get("text") or "")
        if parsed.get("kind") != "text" or not text:
            return None
        mid = str(parsed.get("mid") or raw.get("messageId") or "")
        if not mid:
            return None
        return Message(
            platform=self.platform,
            message_id=mid,
            platform_message_id=mid,
            conversation=self._conversation(peer),
            text=text,
            sent_at_ms=_time_ms(parsed.get("ts") or raw.get("timestamp") or raw.get("createTime")),
            is_send=bool(parsed.get("mine")),
            raw=raw,
        )

    async def catch_up(self, cursor: str) -> list[Message]:
        since = int(cursor or 0)

        def work() -> list[Message]:
            assert self._credential is not None
            self._load_conversations_sync(baseline=False)
            out: list[Message] = []
            with BossClient(self._credential) as client:
                seen: set[str] = set()
                for peer in self._peers.values():
                    friend_id = str(peer.get("friendId") or "")
                    if not friend_id or friend_id in seen:
                        continue
                    seen.add(friend_id)
                    data = client.get_boss_chat_history(int(friend_id), count=50)
                    for raw in data.get("messages") or data.get("messageList") or []:
                        message = self._history_message(raw, peer)
                        if message and message.sent_at_ms > since:
                            out.append(message)
            return sorted(out, key=lambda message: message.sent_at_ms)

        return await run_in_daemon_thread(work)

    async def resolve_conversation(self, platform_audience_id: str) -> Conversation | None:
        audience_id = str(platform_audience_id or "").strip()
        if not audience_id:
            return None

        def work() -> Conversation | None:
            peer = self._friend_with_encrypt_id(audience_id)
            if not isinstance(peer, dict):
                return None
            uid = str(peer.get("uid") or "").strip()
            if uid and uid != audience_id:
                return None
            return self._conversation(peer)

        return await run_in_daemon_thread(work)

    def _bind_live_chat(self, chat: Any) -> None:
        with self._live_chat_lock:
            self._live_chat = chat

    def _live_sender(self):
        deadline = time.time() + 8
        while time.time() < deadline:
            with self._live_chat_lock:
                chat = self._live_chat
            if chat is not None and not chat.dropped:
                return chat
            time.sleep(0.05)
        raise RuntimeError("BOSS 消息通道未连接，请稍后重试")

    async def send_text(self, conversation: Conversation, text: str) -> SendResult:
        def work() -> SendResult:
            assert self._actor is not None
            current = conversation
            uid = int(current.platform_data.get("uid") or current.audience.platform_audience_id)
            encrypt_id = str(current.platform_data.get("encrypt_geek_id") or "").strip()
            if not encrypt_id:
                peer = self._friend_with_encrypt_id(str(uid))
                if isinstance(peer, dict):
                    current = self._conversation(peer)
                    encrypt_id = str(current.platform_data.get("encrypt_geek_id") or "").strip()
            if not encrypt_id:
                raise RuntimeError("BOSS conversation has no encryptGeekId; refresh conversations")
            chat = self._live_sender()
            chat.send(
                from_uid=int(self._actor.platform_actor_id),
                from_encrypt_uid=str(self._user_info.get("encryptUserId") or ""),
                to_uid=uid,
                to_encrypt_uid=encrypt_id,
                text=text,
            )
            return SendResult(success=True, sent_at_ms=int(time.time() * 1000))

        return await run_in_daemon_thread(work)

    async def request_wechat_exchange(self, conversation: Conversation) -> ExchangeResult:
        """Request a WeChat exchange with the saved session, same as boss recruiter exchange-wechat."""
        return await self._request_contact_exchange(conversation, ExchangeType.WECHAT, "wechat")

    async def request_phone_exchange(self, conversation: Conversation) -> ExchangeResult:
        """Request a phone-number exchange with the saved session."""
        return await self._request_contact_exchange(conversation, ExchangeType.PHONE, "phone")

    async def _request_contact_exchange(
        self,
        conversation: Conversation,
        exchange_type: ExchangeType,
        label: str,
    ) -> ExchangeResult:
        def work() -> ExchangeResult:
            assert self._credential is not None
            with BossClient(self._credential) as client:
                context = self._fresh_exchange_context(client, conversation)
                payload = client.request_exchange(
                    security_id=context.security_id,
                    unique_id=context.unique_id,
                    exchange_type=exchange_type,
                    name=context.audience_name,
                )
            return ExchangeResult(
                action="request",
                exchange_type=label,
                platform_message_id=str(payload.get("mid") or payload.get("messageId") or ""),
                data=payload,
            )

        return await run_in_daemon_thread(work)

    async def find_pending_wechat_exchange(self, conversation: Conversation) -> PendingExchangeRequest | None:
        """Find the newest incoming WeChat-exchange system message."""

        def work() -> PendingExchangeRequest | None:
            assert self._credential is not None
            audience_id = self._conversation_audience_id(conversation)
            with BossClient(self._credential) as client:
                history = client.get_boss_chat_history(audience_id, count=50)
            return find_pending_exchange_request(
                history.get("messages") or history.get("messageList") or [],
                audience_id=audience_id,
                exchange_type=ExchangeAcceptType.WECHAT,
            )

        return await run_in_daemon_thread(work)

    async def accept_wechat_exchange(
        self,
        conversation: Conversation,
        platform_message_id: str = "",
    ) -> ExchangeResult:
        """Accept an incoming WeChat request, discovering its message ID when omitted."""

        def work() -> ExchangeResult:
            assert self._credential is not None
            with BossClient(self._credential) as client:
                context = self._fresh_exchange_context(client, conversation)
                message_id = str(platform_message_id or "").strip()
                if not message_id:
                    raise RuntimeError("同意微信交换需要对方请求的消息 ID")
                payload = client.accept_exchange(
                    security_id=context.security_id,
                    platform_message_id=int(message_id),
                    exchange_type=ExchangeAcceptType.WECHAT,
                )
            return ExchangeResult(
                action="accept",
                exchange_type="wechat",
                platform_message_id=message_id,
                data=payload,
            )

        return await run_in_daemon_thread(work)

    async def get_wechat_exchange_content(self, conversation: Conversation) -> dict[str, Any]:
        """Return the platform response containing exchanged contact details."""

        def work() -> dict[str, Any]:
            assert self._credential is not None
            audience_id = self._conversation_audience_id(conversation)
            with BossClient(self._credential) as client:
                return client.get_exchange_content(audience_id)

        return await run_in_daemon_thread(work)

    async def close(self) -> None:
        self._thread_stop.set()
        if self._thread and self._thread.is_alive():
            await asyncio.to_thread(self._thread.join, 2.0)
