"""Local HTTP + SSE bridge for the Douyin private-message UI (frontier-im WS push)."""

from __future__ import annotations

import json
import logging
import queue
import random
import re
import threading
import time
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from boss_cli.constants import DOUYIN_AUTO_REPLY_STATE_FILE
from boss_cli.douyin.credentials import DouyinCredential
from boss_cli.douyin.im import (
    DEFAULT_AUTO_REPLIES,
    ImAuth,
    account_summary,
    auto_reply_for_conversation_state,
    create_conversation,
    ensure_send_cred,
    get_messages_by_conversation,
    list_conversations,
    load_auth,
    peer_profile_for_conversation,
    peer_uid_from_conversation,
    resolve_user_profile,
    send_text,
    sort_messages,
)
from boss_cli.douyin.im_ws import resolve_device_id, run_im_ws_loop
from boss_cli.webchat.payload import format_msg_time
from boss_cli.webchat.server import QuietHTTPServer, content_disposition, is_client_gone, query_param

from .im_media import cached_bytes, image_urls_for_mid, resolve_media_bytes
from .payload import (
    allowed_media_url,
    avatar_from_user,
    conversation_item,
    history_message,
    live_message,
    media_url_fallbacks,
    message_preview,
    public_me,
)

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).resolve().parent / "static"
MAX_POST_BYTES = 16_384
MEDIA_MAX_BYTES = 32_000_000
LIST_PREVIEW_LIMIT = 0
PROFILE_MSG_LIMIT = 8
ACTIVE_POLL_INTERVAL_S = 0.6
ACTIVE_POLL_MSG_LIMIT = 15
INBOX_POLL_INTERVAL_S = 3.0
INBOX_POLL_LIMIT = 4
INBOX_LIST_EVERY = 2
RECENT_CATCHUP_MS = 20 * 60 * 1000
WS_RECONNECT_MIN_S = 2.0
WS_RECONNECT_MAX_S = 30.0
INBOX_REFRESH_S = 30.0
CONV_CACHE_TTL_S = 20.0
# Sidebar: first visit returns this many most-recent chats; later visits return all.
RECENT_INBOX_LIMIT = 5
INBOX_CANDIDATE_LIMIT = 100
SSE_QUEUE_SIZE = 800


def _is_conversation_id(value: str) -> bool:
    return bool(re.fullmatch(r"0:\d+:\d+:\d+", str(value or "").strip()))


def _same_dm_conversation(cid_a: str, cid_b: str, my_uid: str) -> bool:
    """True when two conversation_ids refer to the same 1:1 peer pair."""
    try:
        return peer_uid_from_conversation(cid_a, my_uid) == peer_uid_from_conversation(cid_b, my_uid)
    except Exception:
        return False


def _is_uidish_name(name: str, uid: str = "") -> bool:
    """True when name is empty / conversation-id / the raw uid — not a real nickname.

    Short digit nicknames (e.g. \"9277\") are valid Douyin nicknames and must NOT
    be treated as placeholders. Long all-digit strings that equal the uid are.
    """
    text = str(name or "").strip()
    uid = str(uid or "").strip()
    if not text:
        return True
    if text in {"加载中…", "加载中...", "新会话", "未知", "…"}:
        return True
    if text.startswith("0:") and text.count(":") >= 3:
        return True
    if uid and text == uid:
        return True
    if uid and re.fullmatch(rf"{re.escape(uid)}\({re.escape(uid)}\)", text):
        return True
    # \"用户1234\" style fallback labels
    if re.fullmatch(r"用户\d{1,6}", text):
        return True
    # Long digit-only == likely a Douyin uid (typically >= 10), but only if it
    # matches the known uid. Otherwise keep as possible nickname / unique_id.
    if re.fullmatch(r"\d+", text):
        if uid and text == uid:
            return True
        if uid and len(text) >= 10 and len(text) == len(uid):
            return True
        if not uid and len(text) >= 12:
            return True
        return False
    return False


def _display_peer_name(prof: dict[str, Any]) -> str:
    uid = str(prof.get("uid") or "").strip()
    nick = str(prof.get("nickname") or "").strip()
    unique = str(prof.get("unique_id") or "").strip()
    if nick and not _is_uidish_name(nick, uid):
        return nick
    if unique and unique != uid and not _is_uidish_name(unique, uid):
        return unique
    if nick:
        return nick
    if unique:
        return unique
    return uid or "未知"


def _fallback_peer_label(*, uid: str = "", name: str = "", job: str = "") -> str:
    uid = str(uid or "").strip()
    name = str(name or "").strip()
    job = str(job or "").strip()
    if name and not _is_uidish_name(name, uid):
        return name
    if job and not _is_uidish_name(job, uid):
        return job
    if uid:
        return f"用户{uid[-4:]}" if len(uid) >= 4 else uid
    return "新会话"


def _urls_look_same(a: str, b: str) -> bool:
    left = str(a or "").strip()
    right = str(b or "").strip()
    if not left or not right:
        return False
    if left == right:
        return True
    # Douyin CDN often varies query / host; compare path stem.
    try:
        from urllib.parse import urlparse

        pa = urlparse(left).path
        pb = urlparse(right).path
        return bool(pa and pb and pa == pb)
    except Exception:
        return False


def _json_bytes(payload: dict[str, Any], status: int = 200) -> tuple[int, str, bytes]:
    return status, "application/json; charset=utf-8", json.dumps(payload, ensure_ascii=False).encode("utf-8")


def _filter_conv_states(raw: object) -> dict[str, str]:
    out: dict[str, str] = {}
    if not isinstance(raw, dict):
        return out
    for cid, state in raw.items():
        key = str(cid or "").strip()
        val = str(state or "").strip()
        if key and val in {"greeted", "done"}:
            out[key] = val
    return out


def _migrate_auto_reply_state(raw: object, uid: str) -> dict:
    """旧全局格式迁移：cid 含目标 uid 的归入该账号桶，其余归 legacy。"""
    accounts: dict[str, dict] = {}
    if not isinstance(raw, dict):
        return accounts
    for cid, state in raw.items():
        key = str(cid or "").strip()
        val = str(state or "").strip()
        if not key or val not in {"greeted", "done"}:
            continue
        parts = key.split(":")
        target = uid if (uid and len(parts) >= 4 and uid in parts) else "legacy"
        bucket = accounts.setdefault(target, {"conversations": {}})
        bucket["conversations"][key] = val
    return accounts


def _save_auto_reply_state_doc(doc: dict) -> None:
    DOUYIN_AUTO_REPLY_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    DOUYIN_AUTO_REPLY_STATE_FILE.write_text(
        json.dumps(doc, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _load_auto_reply_conv_state(uid: str = "") -> dict[str, str]:
    """按账号 uid 分桶加载自动回复状态；旧全局格式自动迁移到 accounts 桶。"""
    path = DOUYIN_AUTO_REPLY_STATE_FILE
    try:
        if not path.exists():
            return {}
        data = json.loads(path.read_text(encoding="utf-8"))
        accounts = data.get("accounts") if isinstance(data, dict) else None
        if isinstance(accounts, dict):
            bucket = accounts.get(uid, {}) if uid else {}
            raw = bucket.get("conversations") if isinstance(bucket, dict) else {}
            return _filter_conv_states(raw)
        # 旧格式（顶层 conversations）→ 一次性迁移，避免新账号串用历史状态
        legacy_raw = data.get("conversations") if isinstance(data, dict) else {}
        migrated = _migrate_auto_reply_state(legacy_raw, uid)
        _save_auto_reply_state_doc({"accounts": migrated})
        bucket = migrated.get(uid, {}) if uid else {}
        raw = bucket.get("conversations") if isinstance(bucket, dict) else {}
        return _filter_conv_states(raw)
    except Exception:
        logger.debug("load douyin auto-reply state failed", exc_info=True)
        return {}


def _save_auto_reply_conv_state(state: dict[str, str], uid: str = "") -> None:
    try:
        DOUYIN_AUTO_REPLY_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        try:
            data = json.loads(DOUYIN_AUTO_REPLY_STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            data = {}
        accounts = data.get("accounts") if isinstance(data, dict) else None
        if not isinstance(accounts, dict):
            legacy_raw = data.get("conversations") if isinstance(data, dict) else {}
            accounts = {"legacy": {"conversations": legacy_raw}} if legacy_raw else {}
        key = uid or "legacy"
        bucket = accounts.setdefault(key, {"conversations": {}})
        if not isinstance(bucket, dict):
            bucket = {}
            accounts[key] = bucket
        bucket["conversations"] = dict(sorted(state.items()))
        _save_auto_reply_state_doc({"accounts": accounts})
    except Exception:
        logger.debug("save douyin auto-reply state failed", exc_info=True)


class DouyinWebApp:
    def __init__(
        self,
        credential: DouyinCredential,
        *,
        poll: bool = True,
        auto_reply: bool = True,
        auto_replies: list[str] | None = None,
    ):
        self.credential = credential
        # 必须带上扫码缓存的 uid：profile 风控时 cookie-only 推断会失败/猜错
        self._auth = load_auth(
            cookie=credential.cookie,
            account_name=credential.name,
            uid=str(getattr(credential, "uid", "") or ""),
        )
        if not self._auth.uid and getattr(credential, "uid", ""):
            self._auth.uid = str(credential.uid)
        self._lock = threading.RLock()
        self._subs: list[queue.Queue] = []
        self._stop = threading.Event()
        self._conv_meta: dict[str, dict[str, Any]] = {}
        self._peers: dict[str, dict[str, Any]] = {}
        self._peer_fetching: set[str] = set()
        self._seen: dict[str, set[str]] = {}
        self._thread_cache: dict[str, dict[str, Any]] = {}
        self._active_conv = ""
        self._me: dict[str, Any] = {"uid": "", "name": "我", "avatar": ""}
        self._my_uid = ""
        self._poll_status = "connecting"
        self._auto_reply = bool(auto_reply)
        replies = [
            str(t).strip()
            for t in (auto_replies if auto_replies is not None else DEFAULT_AUTO_REPLIES)
            if str(t).strip()
        ]
        self._auto_replies = replies
        self._auto_reply_mids: set[str] = set()
        self._auto_reply_busy: set[str] = set()
        self._credential_uid = str(getattr(credential, "uid", "") or "").strip()
        self._auto_reply_conv_state: dict[str, str] = _load_auto_reply_conv_state(
            self._credential_uid
        )
        self._auto_reply_conv_busy: set[str] = set()
        self._ws_thread: threading.Thread | None = None
        self._ws_msg_queue: queue.Queue = queue.Queue(maxsize=500)
        self._ws_worker: threading.Thread | None = None
        self._active_poll_thread: threading.Thread | None = None
        self._inbox_poll_thread: threading.Thread | None = None
        self._inbox_lock = threading.Lock()
        self._imapi_lock = threading.Lock()
        self._conversations_cache: list[dict[str, Any]] = []
        self._conversations_cache_at = 0.0
        self._conv_raw_by_id: dict[str, dict[str, Any]] = {}
        self._inbox_order: list[str] = []
        self._refresh_me(resolve_avatar=True)
        # 与 _refresh_me 对齐：发信路径走 auth.uid / _self_uid
        if self._my_uid and not self._auth.uid:
            self._auth.uid = str(self._my_uid)
        if poll:
            self._ws_worker = threading.Thread(
                target=self._ws_message_worker,
                name="douyin-web-ws-msg",
                daemon=True,
            )
            self._ws_worker.start()
            self._ws_thread = threading.Thread(target=self._ws_loop, name="douyin-web-ws", daemon=True)
            self._ws_thread.start()
            self._active_poll_thread = threading.Thread(
                target=self._active_poll_loop,
                name="douyin-web-active-poll",
                daemon=True,
            )
            self._active_poll_thread.start()
            self._inbox_poll_thread = threading.Thread(
                target=self._inbox_poll_loop,
                name="douyin-web-inbox-poll",
                daemon=True,
            )
            self._inbox_poll_thread.start()

    @property
    def auth(self) -> ImAuth:
        return self._auth

    def stop(self) -> None:
        self._stop.set()
        self._poll_status = "stopped"
        self._broadcast({"type": "status", "mqtt": self._poll_status, "me": self._me})

    def _refresh_me(self, *, resolve_avatar: bool = False) -> None:
        summary = account_summary(self._auth) or {}
        # 扫码时写入的 uid 优先：profile 风控时 infer_self_uid 在单会话下会猜错并把「我」和对方互换
        stored_uid = str(getattr(self.credential, "uid", "") or "").strip()
        stored_nick = str(
            getattr(self.credential, "nickname", "")
            or getattr(self.credential, "name", "")
            or ""
        ).strip()
        stored_unique = str(getattr(self.credential, "unique_id", "") or "").strip()
        stored_sec = str(getattr(self.credential, "sec_uid", "") or "").strip()
        avatar = str(self._me.get("avatar") or summary.get("avatar") or "")
        uid = stored_uid or str(summary.get("uid") or "")
        if stored_uid:
            summary["uid"] = stored_uid
        if stored_sec and not summary.get("sec_uid"):
            summary["sec_uid"] = stored_sec
        if stored_unique and not summary.get("unique_id"):
            summary["unique_id"] = stored_unique
        if (resolve_avatar or not avatar) and uid and not avatar:
            try:
                from boss_cli.douyin.im import resolve_user_profile

                sec = str(summary.get("sec_uid") or "")
                prof = resolve_user_profile(self._auth, uid, sec)
                avatar = avatar_from_user(prof) or str(prof.get("avatar") or "")
            except Exception:
                logger.debug("self avatar lookup failed", exc_info=True)
        raw_nick = str(summary.get("nickname") or "").strip()
        # nickname 落成纯数字 uid 时视为解析失败
        if not raw_nick or (uid and raw_nick == uid) or raw_nick.isdigit():
            raw_nick = stored_nick if (stored_nick and not stored_nick.isdigit()) else ""
        name = raw_nick or str(summary.get("unique_id") or stored_unique or uid or "我")
        self._me = public_me({**summary, "nickname": name}, avatar=avatar)
        self._my_uid = uid
        # 发信 / create_conversation 走 _self_uid(auth)，必须与 UI 身份一致
        if uid:
            self._auth.uid = str(uid)
        if uid and not avatar:
            threading.Thread(
                target=self._refresh_me_avatar_job,
                args=(uid, str(summary.get("sec_uid") or ""), str(summary.get("unique_id") or "")),
                name="douyin-web-me-avatar",
                daemon=True,
            ).start()

    def _refresh_me_avatar_job(self, uid: str, sec_uid: str = "", unique_id: str = "") -> None:
        try:
            from boss_cli.douyin.im import resolve_peer_uid, resolve_user_profile

            avatar = ""
            # Prefer self profile (has avatar fields); fall back to unique_id / sec.
            try:
                raw = self._auth.client.get_self_profile()
                user = raw.get("user") if isinstance(raw, dict) and raw.get("user") else raw
                if isinstance(user, dict):
                    avatar = avatar_from_user(user)
                    if not sec_uid:
                        sec_uid = str(user.get("sec_uid") or user.get("sec_user_id") or "")
            except Exception:
                pass
            if not avatar and (sec_uid or unique_id):
                target = unique_id or uid
                if unique_id:
                    try:
                        found = resolve_peer_uid(self._auth, unique_id)
                        sec_uid = str(found.get("sec_uid") or sec_uid)
                        uid = str(found.get("uid") or uid)
                        avatar = str(found.get("avatar") or "")
                    except Exception:
                        pass
                prof = resolve_user_profile(self._auth, str(uid), str(sec_uid))
                avatar = avatar or avatar_from_user(prof) or str(prof.get("avatar") or "")
            if avatar:
                self._me["avatar"] = avatar
                self._broadcast({"type": "status", "mqtt": self._poll_status, "me": self._me})
        except Exception:
            logger.debug("async self avatar lookup failed", exc_info=True)

    def _remember_my_avatar(self, avatar: str) -> None:
        av = str(avatar or "").strip()
        if av and not str(self._me.get("avatar") or "").strip():
            self._me["avatar"] = av

    def _broadcast(self, event: dict[str, Any]) -> None:
        payload = dict(event)
        with self._lock:
            subs = list(self._subs)
        for sub in subs:
            try:
                sub.put_nowait(payload)
            except Exception:
                logger.debug("SSE queue put failed", exc_info=True)

    def subscribe(self) -> queue.Queue:
        q: queue.Queue = queue.Queue(maxsize=SSE_QUEUE_SIZE)
        with self._lock:
            self._subs.append(q)
        q.put({"type": "status", "mqtt": self._poll_status, "me": self._me})
        return q

    def unsubscribe(self, q: queue.Queue) -> None:
        with self._lock:
            if q in self._subs:
                self._subs.remove(q)

    def set_active_conversation(self, conversation_id: str) -> None:
        cid = str(conversation_id or "")
        with self._lock:
            self._active_conv = cid
        if cid:
            threading.Thread(
                target=self._poll_conversation_safe,
                args=(cid,),
                name="douyin-web-poll-now",
                daemon=True,
            ).start()

    def api_set_active(self, conversation_id: str) -> dict[str, Any]:
        self.set_active_conversation(str(conversation_id or ""))
        return {"ok": True, "schema_version": "1", "data": {"activeId": str(conversation_id or "")}}

    def _poll_conversation_safe(self, conversation_id: str) -> None:
        try:
            self._poll_active_conversation(str(conversation_id or ""))
        except Exception:
            logger.debug("immediate poll failed for %s", conversation_id, exc_info=True)

    def _poll_conversation_catchup(self, conversation_id: str) -> None:
        try:
            self._poll_active_conversation(
                str(conversation_id or ""),
                allow_recent_catchup=True,
            )
        except Exception:
            logger.debug("catchup poll failed for %s", conversation_id, exc_info=True)

    def _mark_seen_from_views(self, conversation_id: str, messages: list[dict[str, Any]]) -> None:
        cid = str(conversation_id or "")
        if not cid:
            return
        seen = self._seen.setdefault(cid, set())
        for view in messages:
            mid = str((view or {}).get("mid") or "")
            if mid:
                seen.add(mid)

    def _remember_meta(self, item: dict[str, Any]) -> None:
        meta = item.get("_meta") if isinstance(item.get("_meta"), dict) else {}
        cid = str(meta.get("conversation_id") or item.get("friendId") or "")
        if not cid:
            return
        short = int(meta.get("conversation_short_id") or 0)
        peer_uid = str(meta.get("peer_uid") or "")
        with self._lock:
            prev = self._conv_meta.get(cid) or {}
            self._conv_meta[cid] = {
                "conversation_id": cid,
                "conversation_short_id": short or int(prev.get("conversation_short_id") or 0),
                "peer_uid": peer_uid or str(prev.get("peer_uid") or ""),
                "peer_unique_id": str(meta.get("peer_unique_id") or prev.get("peer_unique_id") or ""),
            }
            if item.get("name") or item.get("avatar"):
                prev_peer = self._peers.get(cid) or {}
                incoming_name = str(item.get("name") or "")
                keep_name = incoming_name
                if _is_uidish_name(incoming_name, peer_uid or str(prev_peer.get("uid") or "")):
                    keep_name = str(prev_peer.get("name") or "")
                    if _is_uidish_name(keep_name, peer_uid):
                        keep_name = incoming_name
                self._peers[cid] = {
                    "name": keep_name or prev_peer.get("name") or "",
                    "avatar": item.get("avatar") or prev_peer.get("avatar") or "",
                    "uid": peer_uid or str(prev_peer.get("uid") or prev.get("peer_uid") or ""),
                    "job": item.get("job") or prev_peer.get("job") or "",
                }

    def _ensure_conv_meta(self, conversation_id: str) -> dict[str, Any]:
        cid = str(conversation_id or "")
        if not cid:
            return {}
        meta = self._meta(cid)
        if int(meta.get("conversation_short_id") or 0):
            self._sync_locked_peer_meta(cid)
            return meta

        cshort = 0
        peer_uid = self._locked_peer_uid(cid)
        if not peer_uid:
            peer_uid = str(meta.get("peer_uid") or self._peer(cid).get("uid") or "")
        with self._lock:
            raw = self._conv_raw_by_id.get(cid)
        if raw:
            cshort = int(raw.get("conversation_short_id") or 0)

        if not peer_uid:
            try:
                if self._my_uid:
                    peer_uid = peer_uid_from_conversation(cid, self._my_uid)
                else:
                    parts = cid.split(":")
                    peer_uid = parts[3] if len(parts) >= 4 else ""
            except Exception:
                peer_uid = ""
        else:
            self._sync_locked_peer_meta(cid)

        # Sticky / WS-only sessions may be absent from inbox; resolve cshort via create_conversation.
        if not cshort and peer_uid and self._auth:
            try:
                with self._imapi_lock:
                    alt_cid, cshort2, _ = create_conversation(self._auth, peer_uid)
                alt_cid = str(alt_cid or "").strip()
                if cshort2 and alt_cid:
                    # Only accept when Douyin returned the same DM pair — never poison this
                    # cid with another chat's conversation_short_id (causes 串会话).
                    if alt_cid == cid or (
                        self._my_uid and _same_dm_conversation(cid, alt_cid, self._my_uid)
                    ):
                        cshort = int(cshort2)
                        with self._lock:
                            self._conv_raw_by_id[alt_cid] = {
                                "conversation_id": alt_cid,
                                "conversation_short_id": cshort,
                            }
                            if alt_cid != cid:
                                self._conv_raw_by_id[cid] = {
                                    "conversation_id": cid,
                                    "conversation_short_id": cshort,
                                }
                    else:
                        logger.warning(
                            "skip cshort from create_conversation: cid=%s peer=%s got_cid=%s",
                            cid,
                            peer_uid,
                            alt_cid,
                        )
            except Exception:
                logger.debug("create_conversation for cshort failed cid=%s peer=%s", cid, peer_uid, exc_info=True)

        if peer_uid or cshort:
            with self._lock:
                prev = self._conv_meta.get(cid) or {}
                locked = self._locked_peer_uid(cid) or peer_uid
                self._conv_meta[cid] = {
                    "conversation_id": cid,
                    "conversation_short_id": cshort or int(prev.get("conversation_short_id") or 0),
                    "peer_uid": locked or str(prev.get("peer_uid") or ""),
                    "peer_unique_id": str(prev.get("peer_unique_id") or ""),
                }
            return self._meta(cid)
        return meta

    def _locked_peer_uid(self, conversation_id: str) -> str:
        """Authoritative peer uid derived from conversation_id (never from cache)."""
        cid = str(conversation_id or "")
        if not cid or not _is_conversation_id(cid):
            return ""
        if not self._my_uid:
            self._refresh_me()
        if not self._my_uid:
            return ""
        try:
            return str(peer_uid_from_conversation(cid, self._my_uid) or "")
        except Exception:
            return ""

    def _sync_locked_peer_meta(self, conversation_id: str) -> None:
        """Persist conversation_id-derived peer uid into meta (session lock)."""
        cid = str(conversation_id or "")
        locked = self._locked_peer_uid(cid)
        if not cid or not locked:
            return
        with self._lock:
            prev = self._conv_meta.get(cid) or {}
            if str(prev.get("peer_uid") or "") == locked:
                return
            self._conv_meta[cid] = {**prev, "conversation_id": cid, "peer_uid": locked}

    def _peer_uid_for(self, conversation_id: str) -> str:
        locked = self._locked_peer_uid(conversation_id)
        if locked:
            return locked
        cid = str(conversation_id or "")
        if not cid:
            return ""
        cached = self._peer(cid)
        uid = str(cached.get("uid") or self._meta(cid).get("peer_uid") or "")
        if uid and uid != str(self._my_uid or ""):
            return uid
        if not self._my_uid:
            self._refresh_me()
        try:
            return peer_uid_from_conversation(cid, self._my_uid)
        except Exception:
            return ""

    def _messages_belong_to_conversation(self, conversation_id: str, messages: list[dict[str, Any]]) -> bool:
        """Guard against poisoned conversation_short_id attaching another chat's history."""
        cid = str(conversation_id or "")
        if not cid or not messages or not self._my_uid:
            return True
        peer = self._locked_peer_uid(cid)
        if not peer:
            return True
        my = str(self._my_uid)
        checked = 0
        for msg in messages:
            msg_cid = str((msg or {}).get("conversation_id") or "").strip()
            if msg_cid and _is_conversation_id(msg_cid):
                if msg_cid != cid and not _same_dm_conversation(cid, msg_cid, my):
                    return False
            sender = str((msg or {}).get("sender") or "").strip()
            if not sender:
                continue
            checked += 1
            if sender != my and sender != peer:
                return False
            if checked >= 12:
                break
        # Opaque batch history (no senders) cannot be trusted when peer is locked.
        if checked == 0:
            if len(messages) == 1:
                only = messages[0] or {}
                msg_cid = str(only.get("conversation_id") or "").strip()
                if msg_cid and msg_cid == cid:
                    return True
            return False
        return True

    def _expected_peer_uid(self, conversation_id: str) -> str:
        return self._locked_peer_uid(conversation_id)

    def _view_belongs_to_conversation(self, conversation_id: str, view: dict[str, Any] | None) -> bool:
        cid = str(conversation_id or "")
        if not cid or not view or not self._my_uid:
            return True
        sender = str(view.get("fromUid") or "").strip()
        peer = self._expected_peer_uid(cid)
        my = str(self._my_uid)
        if not sender:
            # Live WS push may omit sender; allow inbound when we cannot prove it is foreign.
            if peer:
                return not bool(view.get("mine"))
            return True
        if sender == my:
            return True
        if peer and sender == peer:
            return True
        return False

    def _claim_cshort(self, conversation_id: str, cshort: int) -> int:
        """Bind cshort exclusively to this cid's locked peer; drop conflicts that cause 串."""
        cid = str(conversation_id or "")
        cshort = int(cshort or 0)
        if not cid or not cshort:
            return 0
        locked = self._locked_peer_uid(cid)
        with self._lock:
            for other_cid, meta in list(self._conv_meta.items()):
                if other_cid == cid:
                    continue
                if int(meta.get("conversation_short_id") or 0) != cshort:
                    continue
                other_peer = self._locked_peer_uid(other_cid)
                if locked and other_peer and locked == other_peer:
                    continue
                logger.warning(
                    "cshort conflict %s: cid=%s peer=%s vs cid=%s peer=%s — clearing other",
                    cshort,
                    cid,
                    locked,
                    other_cid,
                    other_peer,
                )
                self._conv_meta[other_cid] = {**meta, "conversation_short_id": 0}
                self._thread_cache.pop(other_cid, None)
            prev = self._conv_meta.get(cid) or {}
            self._conv_meta[cid] = {
                **prev,
                "conversation_id": cid,
                "conversation_short_id": cshort,
                "peer_uid": locked or str(prev.get("peer_uid") or ""),
            }
        return cshort

    def _dedupe_conversations_by_peer(self, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """One sidebar row per locked peer uid (prefer richer identity + newer activity)."""
        best: dict[str, dict[str, Any]] = {}
        passthrough: list[dict[str, Any]] = []
        for item in items:
            cid = str(item.get("friendId") or "")
            peer = self._locked_peer_uid(cid) or str(item.get("uid") or "")
            if not peer:
                passthrough.append(item)
                continue
            prev = best.get(peer)
            if not prev:
                best[peer] = item
                continue
            prev_ready = 1 if self._conversation_list_ready(prev) else 0
            cur_ready = 1 if self._conversation_list_ready(item) else 0
            prev_ts = self._conversation_last_ts(prev)
            cur_ts = self._conversation_last_ts(item)
            if (cur_ready, cur_ts) > (prev_ready, prev_ts):
                best[peer] = item
        return list(best.values()) + passthrough

    def _filter_views_for_conversation(
        self,
        conversation_id: str,
        views: list[dict[str, Any]] | None,
    ) -> list[dict[str, Any]]:
        return [dict(v) for v in (views or []) if self._view_belongs_to_conversation(conversation_id, v)]

    def _clear_poisoned_conversation(self, conversation_id: str) -> None:
        cid = str(conversation_id or "")
        if not cid:
            return
        with self._lock:
            prev = self._conv_meta.get(cid) or {}
            self._conv_meta[cid] = {**prev, "conversation_short_id": 0}
            # Always drop thread cache — filtered leftovers still look like 串 in UI.
            self._thread_cache.pop(cid, None)
            rows = []
            for row in list(self._conversations_cache):
                if str(row.get("friendId") or "") != cid:
                    rows.append(row)
                    continue
                cleaned = dict(row)
                cleaned.pop("lastMessage", None)
                cleaned.pop("lastTime", None)
                cleaned["lastTs"] = 0
                rows.append(cleaned)
            self._conversations_cache = rows

    def _merge_history_with_live_cache(self, conversation_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        prev = self._thread_cache.get(conversation_id) or {}
        live_msgs = self._filter_views_for_conversation(conversation_id, list(prev.get("messages") or []))
        if not live_msgs:
            return payload
        hist = list(payload.get("messages") or [])
        by_mid: dict[str, dict[str, Any]] = {
            str(m.get("mid") or ""): dict(m)
            for m in hist
            if m.get("mid")
        }
        hist_max_ts = 0
        for m in hist:
            try:
                hist_max_ts = max(hist_max_ts, int(m.get("ts") or 0))
            except (TypeError, ValueError):
                continue
        for old in live_msgs:
            mid = str((old or {}).get("mid") or "")
            if not mid:
                continue
            if mid in by_mid:
                by_mid[mid] = self._merge_message_views(by_mid[mid], old)
                continue
            # Only keep very recent live/pending extras — never resurrect poisoned older rows.
            try:
                ots = int(old.get("ts") or 0)
            except (TypeError, ValueError):
                ots = 0
            if hist_max_ts and ots and ots + 120_000 < hist_max_ts:
                continue
            if hist_max_ts and ots and ots > hist_max_ts + 7 * 24 * 3600 * 1000:
                continue
            by_mid[mid] = dict(old)
        if not by_mid:
            return payload
        return {
            **payload,
            "messages": sorted(
                by_mid.values(),
                key=lambda m: (int(m.get("ts") or 0), str(m.get("mid") or "")),
            ),
        }

    def _recent_messages(self, conversation_id: str, conversation_short_id: int, *, limit: int = PROFILE_MSG_LIMIT) -> list[dict[str, Any]]:
        return self._recent_messages_locked(conversation_id, conversation_short_id, limit=limit)

    def _recent_messages_locked(self, conversation_id: str, conversation_short_id: int, *, limit: int = PROFILE_MSG_LIMIT) -> list[dict[str, Any]]:
        cid = str(conversation_id or "")
        cshort = int(conversation_short_id or 0)
        if not cid or not cshort:
            return []
        try:
            with self._imapi_lock:
                raw = get_messages_by_conversation(
                    self._auth,
                    cid,
                    cshort,
                    limit=max(3, int(limit)),
                    anchor_index=0,
                )
            if not self._messages_belong_to_conversation(cid, raw):
                logger.warning("recent preview peer mismatch for %s cshort=%s", cid, cshort)
                with self._lock:
                    prev = self._conv_meta.get(cid) or {}
                    self._conv_meta[cid] = {**prev, "conversation_short_id": 0}
                return []
            return sort_messages(raw)
        except Exception:
            logger.debug("recent messages failed for %s", cid, exc_info=True)
            return []

    def _preview_from_messages(self, raw: list[dict[str, Any]]) -> tuple[str, str, int]:
        for msg in reversed(raw):
            if int(msg.get("message_type") or 0) == 50001:
                continue
            text = message_preview(msg)
            if text:
                ts = int(msg.get("create_time_ms") or 0)
                if ts and ts < 10_000_000_000:
                    ts *= 1000
                return text[:120], format_msg_time(ts), ts
        return "", "", 0

    @staticmethod
    def _conversation_last_ts(item: dict[str, Any] | None) -> int:
        if not item:
            return 0
        try:
            ts = int(item.get("lastTs") or 0)
        except (TypeError, ValueError):
            ts = 0
        return ts

    def _inbox_last_ts(self, conversation_id: str) -> int:
        """收件箱刷新后该会话的最新消息时间（小红书方案：判断缓存是否过期）。"""
        cid = str(conversation_id or "")
        with self._lock:
            for row in self._conversations_cache:
                if str(row.get("friendId") or "") == cid:
                    return self._conversation_last_ts(row)
        return 0

    def _sort_conversations_by_recent(self, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        ranked = sorted(
            items,
            key=lambda it: (self._conversation_last_ts(it), str(it.get("friendId") or "")),
            reverse=True,
        )
        for i, row in enumerate(ranked):
            row["index"] = i + 1
        return ranked

    def _take_recent_conversations(self, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return self._sort_conversations_by_recent(items)[:RECENT_INBOX_LIMIT]

    def _fill_item_last_activity(self, item: dict[str, Any], *, network: bool = True) -> dict[str, Any]:
        """Attach lastMessage / lastTs from thread cache or a cheap history peek."""
        row = dict(item)
        cid = str(row.get("friendId") or "")
        if not cid:
            return row
        if int(row.get("lastTs") or 0) and row.get("lastMessage"):
            return row
        # Cached list responses must not pull previews from live/poisoned thread stubs.
        if not network:
            return row
        cached = self._thread_cache.get(cid) or {}
        if str(cached.get("source") or "") != "history":
            cached = {}
        msgs = self._filter_views_for_conversation(cid, list(cached.get("messages") or []))
        if msgs:
            last = msgs[-1]
            if not row.get("lastMessage"):
                row["lastMessage"] = str(last.get("text") or cached.get("lastMessage") or "")
            if not row.get("lastTime"):
                row["lastTime"] = str(last.get("time") or "")
            if not int(row.get("lastTs") or 0):
                try:
                    row["lastTs"] = int(last.get("ts") or 0)
                except (TypeError, ValueError):
                    row["lastTs"] = 0
            if int(row.get("lastTs") or 0) and row.get("lastMessage"):
                return row
        if not network:
            return row
        meta = self._meta(cid)
        cshort = int(meta.get("conversation_short_id") or 0)
        if not cshort:
            return row
        try:
            recent = self._recent_messages(cid, cshort, limit=3)
            text, stamp, ts = self._preview_from_messages(recent)
            if text and not row.get("lastMessage"):
                row["lastMessage"] = text
            if stamp and not row.get("lastTime"):
                row["lastTime"] = stamp
            if ts and not int(row.get("lastTs") or 0):
                row["lastTs"] = ts
        except Exception:
            logger.debug("fill last activity failed for %s", cid, exc_info=True)
        return row

    def _refresh_row_preview_from_api(self, row: dict[str, Any]) -> dict[str, Any]:
        """Force lastMessage preview from validated history (never WS/thread stubs)."""
        cid = str(row.get("friendId") or "")
        if not cid:
            return row
        meta = self._meta(cid)
        cshort = int(meta.get("conversation_short_id") or 0)
        if not cshort:
            return row
        recent = self._recent_messages_locked(cid, cshort, limit=5)
        text, stamp, ts = self._preview_from_messages(recent)
        if text:
            row = dict(row)
            row["lastMessage"] = text
            row["lastTime"] = stamp
            row["lastTs"] = ts
        return row

    def _peer_identity_ready(self, conversation_id: str) -> bool:
        """True when locked peer has both a real nickname and avatar."""
        cid = str(conversation_id or "")
        cached = self._peer(cid)
        uid = self._locked_peer_uid(cid) or str(cached.get("uid") or "")
        name = str(cached.get("name") or "")
        avatar = str(cached.get("avatar") or "")
        if not uid or not avatar or not name or _is_uidish_name(name, uid):
            return False
        return True

    def _conversation_list_ready(self, item: dict[str, Any]) -> bool:
        """Sidebar row is usable once we know the peer uid (avatar/nickname may arrive later)."""
        cid = str(item.get("friendId") or "")
        if not _is_conversation_id(cid):
            return False
        uid = self._locked_peer_uid(cid) or str(item.get("uid") or "")
        if not uid:
            return False
        my_uid = str(self._my_uid or self._me.get("uid") or "")
        if my_uid and uid == my_uid:
            return False
        return True

    def _filter_list_ready(self, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [it for it in items if self._conversation_list_ready(it)]

    def _remember_peer_sec(self, conversation_id: str, peer_uid: str, sec_sender: str) -> None:
        cid = str(conversation_id or "")
        sec = str(sec_sender or "").strip()
        uid = str(peer_uid or "").strip()
        if not cid or not sec:
            return
        # Never store *my* sec_uid as the peer's — that causes peer to show my nick/avatar.
        if self._my_uid and uid and uid == str(self._my_uid):
            return
        with self._lock:
            prev = self._conv_meta.get(cid) or {}
            self._conv_meta[cid] = {
                **prev,
                "conversation_id": cid,
                "peer_sec_uid": sec,
                "peer_uid": uid or str(prev.get("peer_uid") or ""),
            }

    def _append_thread_cache_view(
        self,
        conversation_id: str,
        view: dict[str, Any],
        *,
        peer: dict[str, Any],
    ) -> None:
        cid = str(conversation_id or "")
        if not cid or not view:
            return
        if not self._view_belongs_to_conversation(cid, view):
            logger.warning("skip foreign cached view for %s mid=%s", cid, view.get("mid"))
            return
        mid = str(view.get("mid") or "")
        cached = dict(self._thread_cache.get(cid) or {})
        msgs = list(cached.get("messages") or [])
        if mid:
            upgraded = False
            for i, prev in enumerate(msgs):
                if str(prev.get("mid") or "") != mid:
                    continue
                msgs[i] = self._merge_message_views(prev, view)
                upgraded = True
                break
            if not upgraded:
                msgs.append(dict(view))
                msgs.sort(key=lambda m: (int(m.get("ts") or 0), str(m.get("mid") or "")))
        else:
            msgs.append(dict(view))
            msgs.sort(key=lambda m: (int(m.get("ts") or 0), str(m.get("mid") or "")))
        self._thread_cache[cid] = {
            "friendId": cid,
            "messages": msgs,
            "hasMore": bool(cached.get("hasMore")) if cached.get("source") == "history" else True,
            "nextCursor": cached.get("nextCursor"),
            "peer": {
                "uid": str(peer.get("uid") or ""),
                "friendId": cid,
                "name": str(peer.get("name") or ""),
                "avatar": str(peer.get("avatar") or ""),
                "job": str(peer.get("job") or ""),
            },
            "lastMessage": str(view.get("text") or cached.get("lastMessage") or ""),
            # Live pushes must not block a full history reload (or images vanish).
            "source": "history" if cached.get("source") == "history" else "live",
        }

    @staticmethod
    def _message_view_richness(view: dict[str, Any] | None) -> int:
        if not view:
            return 0
        score = 0
        image = view.get("image") if isinstance(view.get("image"), dict) else None
        if image:
            score += 2
            if image.get("preview") or image.get("origin"):
                score += 4
            if image.get("skey") or image.get("oid"):
                score += 3
            if image.get("mid"):
                score += 1
        audio = view.get("audio") if isinstance(view.get("audio"), dict) else None
        if audio and (audio.get("url") or audio.get("mid")):
            score += 3
        file_info = view.get("file") if isinstance(view.get("file"), dict) else None
        if file_info and file_info.get("url"):
            score += 2
        kind = str(view.get("kind") or "")
        text = str(view.get("text") or "").strip()
        if kind in ("video", "card"):
            score += 3
            if not file_info or not file_info.get("url"):
                score -= 4
        if kind == "text" and text in {"分享", "[分享]", "[分享视频]", "[分享图文]"}:
            score -= 6
        if kind in ("image", "emoji") and not image:
            score -= 5
        if kind == "voice" and not audio:
            score -= 3
        return score

    def _merge_message_views(self, prev: dict[str, Any], nxt: dict[str, Any]) -> dict[str, Any]:
        if self._message_view_richness(nxt) >= self._message_view_richness(prev):
            base = {**prev, **nxt}
        else:
            base = {**nxt, **prev}
        for key in ("image", "audio", "file"):
            a = prev.get(key) if isinstance(prev.get(key), dict) else None
            b = nxt.get(key) if isinstance(nxt.get(key), dict) else None
            if a and b:
                base[key] = {**a, **b}
            elif a and not b:
                base[key] = a
            elif b and not a:
                base[key] = b
        return base

    @staticmethod
    def _thread_needs_media_repair(messages: list[dict[str, Any]] | None) -> bool:
        share_stub_texts = {"分享", "[分享]", "[分享视频]", "[分享图文]"}
        for msg in messages or []:
            kind = str((msg or {}).get("kind") or "")
            text = str((msg or {}).get("text") or "").strip()
            # WS share pushes often land as bare「分享」text before history has itemId/cover.
            if kind == "text" and text in share_stub_texts:
                return True
            if kind in ("video", "card"):
                file_info = msg.get("file") if isinstance(msg.get("file"), dict) else None
                if not file_info or not file_info.get("url"):
                    return True
                continue
            if kind not in ("image", "emoji", "voice"):
                continue
            if kind in ("image", "emoji"):
                image = msg.get("image") if isinstance(msg.get("image"), dict) else None
                if not image:
                    return True
                has_url = bool(image.get("preview") or image.get("origin"))
                has_decrypt = bool(image.get("skey") and (image.get("oid") or image.get("mid")))
                if has_url or has_decrypt:
                    continue
                return True
            if kind == "voice":
                audio = msg.get("audio") if isinstance(msg.get("audio"), dict) else None
                if not audio or not (audio.get("url") or audio.get("mid")):
                    return True
        return False

    def _live_thread_payload(self, conversation_id: str) -> dict[str, Any] | None:
        cid = str(conversation_id or "")
        if not cid:
            return None
        cached = self._thread_cache.get(cid)
        if cached and cached.get("messages") is not None:
            peer = dict(cached.get("peer") or {})
            if not peer.get("uid"):
                peer = self._fill_peer_for_message(cid)
            label = _fallback_peer_label(uid=str(peer.get("uid") or ""), name=str(peer.get("name") or ""), job=str(peer.get("job") or ""))
            peer = {
                **peer,
                "friendId": cid,
                "name": label,
            }
            return {
                "friendId": cid,
                "peer": peer,
                "messages": list(cached.get("messages") or []),
                "hasMore": bool(cached.get("hasMore")),
                "nextCursor": cached.get("nextCursor"),
                "lastMessage": str(cached.get("lastMessage") or ""),
            }
        meta = self._ensure_conv_meta(conversation_id)
        peer_uid = str(meta.get("peer_uid") or "")
        if self._my_uid and not peer_uid:
            try:
                peer_uid = peer_uid_from_conversation(cid, self._my_uid)
            except Exception:
                peer_uid = ""
        peer = self._fill_peer_for_message(cid, peer_uid=peer_uid)
        label = _fallback_peer_label(uid=str(peer.get("uid") or peer_uid), name=str(peer.get("name") or ""), job=str(peer.get("job") or ""))
        return {
            "friendId": cid,
            "peer": {
                "uid": str(peer.get("uid") or peer_uid or ""),
                "friendId": cid,
                "name": label,
                "avatar": str(peer.get("avatar") or ""),
                "job": str(peer.get("job") or ""),
            },
            "messages": [],
            "hasMore": False,
            "nextCursor": None,
            "lastMessage": "",
        }

    def _upsert_conversation_cache_row(self, item: dict[str, Any], *, prepend: bool = True) -> None:
        """Insert or update a conversation in the server-side list cache."""
        cid = str(item.get("friendId") or "")
        if not cid or not _is_conversation_id(cid):
            return
        row = {k: v for k, v in item.items() if k != "_meta"}
        with self._lock:
            rows = list(self._conversations_cache)
        found = False
        for existing in rows:
            if str(existing.get("friendId") or "") != cid:
                continue
            for key in ("name", "avatar", "uid", "job", "lastMessage", "lastTime", "unread"):
                val = row.get(key)
                if val in (None, ""):
                    continue
                if key == "name" and _is_uidish_name(str(val), str(row.get("uid") or existing.get("uid") or "")):
                    # Don't overwrite a real nickname with a bare uid.
                    if not _is_uidish_name(str(existing.get("name") or ""), str(existing.get("uid") or "")):
                        continue
                if key == "unread" and isinstance(val, int):
                    existing[key] = val
                else:
                    existing[key] = val
            found = True
            if prepend and rows and rows[0] is not existing:
                rows = [existing] + [r for r in rows if r is not existing]
            break
        if not found:
            rows = [row] + rows if prepend else rows + [row]
        with self._lock:
            self._conversations_cache = rows
            if not self._conversations_cache_at:
                self._conversations_cache_at = time.time()

    def _merge_sticky_conversations(self, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Keep WS-discovered sessions that Douyin list API has not returned yet."""
        known = {str(i.get("friendId") or "") for i in items}
        with self._lock:
            sticky = list(self._conversations_cache)
            meta_ids = [
                cid
                for cid, meta in self._conv_meta.items()
                if cid and cid not in known and (self._seen.get(cid) or self._peers.get(cid))
            ]
        extras: list[dict[str, Any]] = []
        sticky_ids: set[str] = set()
        for row in sticky:
            cid = str(row.get("friendId") or "")
            if not cid or cid in known or cid in sticky_ids:
                continue
            sticky_ids.add(cid)
            extras.append(dict(row))
        for cid in meta_ids:
            if cid in sticky_ids or cid in known:
                continue
            meta = self._meta(cid)
            peer = self._peer(cid)
            peer_uid = str(peer.get("uid") or meta.get("peer_uid") or "")
            name = str(peer.get("name") or peer_uid or "新会话")
            extras.append(
                conversation_item(
                    index=1,
                    conversation_id=cid,
                    conversation_short_id=int(meta.get("conversation_short_id") or 0),
                    peer_uid=peer_uid,
                    peer_unique_id=str(peer.get("job") or meta.get("peer_unique_id") or ""),
                    name=name,
                    avatar=str(peer.get("avatar") or ""),
                    last_text="",
                    last_time="",
                )
            )
            extras[-1] = {k: v for k, v in extras[-1].items() if k != "_meta"}
            sticky_ids.add(cid)
        if not extras:
            return items
        # Newest sticky first, then API list.
        return extras + items

    def _fill_peer_for_message(
        self,
        conversation_id: str,
        *,
        peer_uid: str = "",
        raw_message: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Ensure peer nickname/avatar before emitting a live message."""
        cid = str(conversation_id or "")
        peer = self._peer(cid)
        uid = str(peer.get("uid") or peer_uid or "")
        name = str(peer.get("name") or "")
        avatar = str(peer.get("avatar") or "")
        if uid and (not avatar or not name or _is_uidish_name(name, uid)):
            messages = [raw_message] if raw_message else None
            try:
                row = self._resolve_peer_row(cid, messages, persist=True)
                peer = {
                    "uid": str(row.get("uid") or uid),
                    "name": str(row.get("name") or name or uid),
                    "avatar": str(row.get("avatar") or avatar),
                    "job": str(row.get("job") or peer.get("job") or ""),
                }
            except Exception:
                logger.debug("sync peer fill failed for %s", cid, exc_info=True)
                peer = {
                    "uid": uid,
                    "name": name or uid,
                    "avatar": avatar,
                    "job": str(peer.get("job") or ""),
                }
        else:
            peer = {
                "uid": uid or str(peer.get("uid") or ""),
                "name": name,
                "avatar": avatar,
                "job": str(peer.get("job") or ""),
            }
        return peer

    def _broadcast_peer_update(self, conversation_id: str, peer_row: dict[str, str], *, last_message: str = "") -> None:
        event: dict[str, Any] = {
            "type": "peer",
            "friendId": conversation_id,
            "uid": self._locked_peer_uid(conversation_id) or str(peer_row.get("uid") or ""),
            "name": str(peer_row.get("name") or ""),
            "avatar": str(peer_row.get("avatar") or ""),
            "job": str(peer_row.get("job") or ""),
            "trusted": True,
        }
        if last_message:
            event["lastMessage"] = last_message
        self._patch_peer_in_cache(conversation_id, peer_row, last_message=last_message)
        self._broadcast(event)

    def _patch_peer_in_cache(
        self,
        conversation_id: str,
        peer_row: dict[str, str],
        *,
        last_message: str = "",
    ) -> None:
        cid = str(conversation_id or "")
        if not cid:
            return
        locked = self._locked_peer_uid(cid)
        item = {
            "friendId": cid,
            "uid": locked or str(peer_row.get("uid") or ""),
            "name": str(peer_row.get("name") or ""),
            "avatar": str(peer_row.get("avatar") or ""),
            "job": str(peer_row.get("job") or ""),
        }
        if last_message:
            item["lastMessage"] = last_message
        self._upsert_conversation_cache_row(item, prepend=False)
        with self._lock:
            thread = self._thread_cache.get(cid)
            if thread is not None:
                prev = dict(thread.get("peer") or {})
                thread["peer"] = {
                    **prev,
                    "uid": item["uid"] or prev.get("uid") or "",
                    "friendId": cid,
                    "name": item["name"] or prev.get("name") or "",
                    "avatar": item["avatar"] or prev.get("avatar") or "",
                    "job": item["job"] or prev.get("job") or "",
                }

    def _enrich_peer_later(self, conversation_id: str, conversation_short_id: int) -> None:
        cid = str(conversation_id or "")
        cshort = int(conversation_short_id or 0)
        if not cid or not cshort:
            return
        if self._peer_identity_ready(cid):
            return
        with self._lock:
            if cid in self._peer_fetching:
                return
            self._peer_fetching.add(cid)

        def work() -> None:
            try:
                if self._peer_identity_ready(cid):
                    return
                peer_row = self._resolve_peer_row(cid, None, persist=True)
                if (
                    _is_uidish_name(str(peer_row.get("name") or ""), str(peer_row.get("uid") or ""))
                    or not peer_row.get("avatar")
                ):
                    recent = self._recent_messages(cid, cshort, limit=40)
                    peer_row = self._resolve_peer_row(cid, recent, persist=True)
                # unique_id (job) can resolve nickname when uid lookup fails
                job = str(peer_row.get("job") or self._peer(cid).get("job") or "")
                if job and _is_uidish_name(str(peer_row.get("name") or ""), str(peer_row.get("uid") or "")):
                    try:
                        from boss_cli.douyin.im import resolve_peer_uid, resolve_user_profile

                        found = resolve_peer_uid(self._auth, job)
                        sec = str(found.get("sec_uid") or "")
                        prof = resolve_user_profile(
                            self._auth,
                            str(found.get("uid") or peer_row.get("uid") or ""),
                            sec,
                        ) if (found.get("uid") or peer_row.get("uid")) else found
                        if prof.get("nickname") or found.get("nickname"):
                            peer_row = {
                                **peer_row,
                                "uid": str(prof.get("uid") or found.get("uid") or peer_row.get("uid") or ""),
                                "name": str(prof.get("nickname") or found.get("nickname") or peer_row.get("name") or ""),
                                "avatar": str(prof.get("avatar") or found.get("avatar") or peer_row.get("avatar") or ""),
                                "job": str(prof.get("unique_id") or found.get("unique_id") or job),
                            }
                            with self._lock:
                                prev = self._peers.get(cid) or {}
                                self._peers[cid] = {
                                    "name": peer_row["name"] or prev.get("name") or "",
                                    "avatar": peer_row["avatar"] or prev.get("avatar") or "",
                                    "uid": peer_row["uid"] or prev.get("uid") or "",
                                    "job": peer_row["job"] or prev.get("job") or "",
                                }
                            if sec:
                                self._remember_peer_sec(cid, peer_row["uid"], sec)
                    except Exception:
                        logger.debug("unique_id enrich failed for %s job=%s", cid, job, exc_info=True)
                if not peer_row.get("name") and not peer_row.get("avatar"):
                    return
                self._broadcast_peer_update(cid, peer_row)
            except Exception:
                logger.debug("peer enrich failed for %s", cid, exc_info=True)
            finally:
                with self._lock:
                    self._peer_fetching.discard(cid)

        threading.Thread(target=work, name="douyin-web-peer", daemon=True).start()

    def _enrich_peer_by_uid_later(
        self,
        conversation_id: str,
        peer_uid: str,
        raw_message: dict[str, Any] | None = None,
    ) -> None:
        """cshort=0 时通过 peer_uid + 消息中的 sec_sender 获取昵称（不依赖 conversation_short_id）。"""
        cid = str(conversation_id or "")
        if not cid or not peer_uid:
            return
        if self._peer_identity_ready(cid):
            return
        with self._lock:
            if cid in self._peer_fetching:
                return
            self._peer_fetching.add(cid)

        def work() -> None:
            try:
                if self._peer_identity_ready(cid):
                    return
                messages = [raw_message] if raw_message else None
                peer_row = self._resolve_peer_row(cid, messages, persist=True)
                job = str(
                    peer_row.get("job")
                    or self._peer(cid).get("job")
                    or self._meta(cid).get("peer_unique_id")
                    or ""
                )
                if job and _is_uidish_name(str(peer_row.get("name") or ""), str(peer_row.get("uid") or peer_uid)):
                    try:
                        from boss_cli.douyin.im import resolve_peer_uid, resolve_user_profile

                        found = resolve_peer_uid(self._auth, job)
                        sec = str(found.get("sec_uid") or "")
                        target_uid = str(found.get("uid") or peer_uid)
                        prof = resolve_user_profile(self._auth, target_uid, sec) if target_uid else found
                        nick = str(prof.get("nickname") or found.get("nickname") or "")
                        if nick:
                            peer_row = {
                                **peer_row,
                                "uid": target_uid,
                                "name": nick,
                                "avatar": str(prof.get("avatar") or found.get("avatar") or peer_row.get("avatar") or ""),
                                "job": str(prof.get("unique_id") or found.get("unique_id") or job),
                            }
                            with self._lock:
                                prev = self._peers.get(cid) or {}
                                self._peers[cid] = {
                                    "name": peer_row["name"] or prev.get("name") or "",
                                    "avatar": peer_row["avatar"] or prev.get("avatar") or "",
                                    "uid": peer_row["uid"] or prev.get("uid") or "",
                                    "job": peer_row["job"] or prev.get("job") or "",
                                }
                            if sec:
                                self._remember_peer_sec(cid, target_uid, sec)
                    except Exception:
                        logger.debug("unique_id enrich-by-uid failed for %s", cid, exc_info=True)
                if not peer_row.get("name") and not peer_row.get("avatar"):
                    return
                self._broadcast_peer_update(cid, peer_row)
            except Exception:
                logger.debug("peer enrich by uid failed for %s", cid, exc_info=True)
            finally:
                with self._lock:
                    self._peer_fetching.discard(cid)

        threading.Thread(target=work, name="douyin-web-peer-uid", daemon=True).start()

    def _schedule_list_enrich(self, items: list[dict[str, Any]]) -> None:
        for item in items:
            cid = str(item.get("friendId") or "")
            meta = self._meta(cid)
            cshort = int(meta.get("conversation_short_id") or 0)
            peer_uid = str(item.get("uid") or meta.get("peer_uid") or "")
            if not cid:
                continue
            if self._peer_identity_ready(cid):
                continue
            if cshort:
                self._enrich_peer_later(cid, cshort)
            elif peer_uid:
                self._enrich_peer_by_uid_later(cid, peer_uid, None)

    def _last_message_preview(self, conversation_id: str, conversation_short_id: int) -> tuple[str, str, int]:
        return self._preview_from_messages(
            self._recent_messages(conversation_id, conversation_short_id, limit=5)
        )

    def _build_conversation_item_light(
        self,
        conv: dict[str, Any],
        index: int,
        *,
        last_text: str = "",
        last_time: str = "",
    ) -> dict[str, Any]:
        cid = str(conv.get("conversation_id") or "")
        cshort = int(conv.get("conversation_short_id") or 0)
        peer_uid = ""
        if self._my_uid and cid:
            try:
                peer_uid = peer_uid_from_conversation(cid, self._my_uid)
            except Exception:
                peer_uid = ""
        cached = self._peer(cid)
        meta = self._meta(cid)
        avatar = str(cached.get("avatar") or "")
        job = str(cached.get("job") or meta.get("peer_unique_id") or "")
        name = _fallback_peer_label(
            uid=peer_uid or str(cached.get("uid") or meta.get("peer_uid") or ""),
            name=str(cached.get("name") or meta.get("peer_uid") or peer_uid or cid),
            job=job,
        )
        item = conversation_item(
            index=index,
            conversation_id=cid,
            conversation_short_id=cshort,
            peer_uid=peer_uid or str(cached.get("uid") or meta.get("peer_uid") or ""),
            peer_unique_id=job,
            name=name,
            avatar=avatar,
            last_text=last_text,
            last_time=last_time,
        )
        self._remember_meta(item)
        return {k: v for k, v in item.items() if k != "_meta"}

    def _enrich_conversation_items(self, items: list[dict[str, Any]]) -> None:
        for item in list(items):
            cid = str(item.get("friendId") or "")
            meta = self._meta(cid)
            cshort = int(meta.get("conversation_short_id") or 0)
            if not cid or not cshort:
                continue
            try:
                built = self._build_conversation_item(
                    {"conversation_id": cid, "conversation_short_id": cshort},
                    int(item.get("index") or 1),
                    with_preview=True,
                    resolve_profile=True,
                )
            except Exception:
                logger.debug("conv enrich failed for %s", cid, exc_info=True)
                continue
            self._broadcast({"type": "conv", **built})
            self._broadcast_peer_update(
                cid,
                {
                    "uid": str(built.get("uid") or ""),
                    "name": str(built.get("name") or ""),
                    "avatar": str(built.get("avatar") or ""),
                    "job": str(built.get("job") or ""),
                },
            )

    def _list_conversations_safe(self, *, page_size: int = 50, max_pages: int = 1) -> list[dict[str, Any]]:
        with self._imapi_lock:
            return list_conversations(self._auth, page_size=page_size, max_pages=max_pages)

    def _build_conversation_item(
        self,
        conv: dict[str, Any],
        index: int,
        *,
        with_preview: bool = True,
        resolve_profile: bool = True,
    ) -> dict[str, Any]:
        cid = str(conv.get("conversation_id") or "")
        cshort = int(conv.get("conversation_short_id") or 0)
        with self._lock:
            prev = self._conv_meta.get(cid) or {}
            locked = self._locked_peer_uid(cid)
            self._conv_meta[cid] = {
                "conversation_id": cid,
                "conversation_short_id": cshort or int(prev.get("conversation_short_id") or 0),
                "peer_uid": locked or str(prev.get("peer_uid") or ""),
                "peer_unique_id": str(prev.get("peer_unique_id") or ""),
            }
        recent: list[dict[str, Any]] = []
        if cshort and (with_preview or (resolve_profile and not self._peer_identity_ready(cid))):
            recent = self._recent_messages_locked(cid, cshort)
        if resolve_profile or self._peer_identity_ready(cid):
            peer_row = self._resolve_peer_row(cid, recent, persist=True)
        else:
            peer_uid = self._locked_peer_uid(cid) or self._peer_uid_for(cid)
            cached_peer = self._peer(cid)
            peer_row = {
                "uid": peer_uid,
                "name": _fallback_peer_label(
                    uid=peer_uid,
                    name=str(cached_peer.get("name") or ""),
                    job=str(cached_peer.get("job") or ""),
                ),
                "avatar": str(cached_peer.get("avatar") or ""),
                "job": str(cached_peer.get("job") or ""),
            }
        locked = self._locked_peer_uid(cid)
        if locked:
            peer_row = {**peer_row, "uid": locked}
        last_text, last_time, last_ts = self._preview_from_messages(recent) if with_preview and recent else ("", "", 0)
        item = conversation_item(
            index=index,
            conversation_id=cid,
            conversation_short_id=cshort,
            peer_uid=str(peer_row.get("uid") or ""),
            peer_unique_id=str(peer_row.get("job") or ""),
            name=str(peer_row.get("name") or ""),
            avatar=str(peer_row.get("avatar") or ""),
            last_text=last_text,
            last_time=last_time,
            last_ts=last_ts,
        )
        self._remember_meta(item)
        if cshort and not self._peer_identity_ready(cid):
            self._enrich_peer_later(cid, cshort)
        return {k: v for k, v in item.items() if k != "_meta"}

    def _is_self_peer_row(self, row: dict[str, Any], *, peer_uid: str = "") -> bool:
        """True when a 'peer' profile actually matches the logged-in account."""
        my_uid = str(self._my_uid or self._me.get("uid") or "")
        my_name = str(self._me.get("name") or "").strip()
        my_avatar = str(self._me.get("avatar") or "").strip()
        uid = str(row.get("uid") or peer_uid or "").strip()
        name = str(row.get("name") or row.get("nickname") or "").strip()
        avatar = str(row.get("avatar") or "").strip()
        if my_uid and uid and uid == my_uid:
            return True
        if my_name and name and name == my_name:
            return True
        if my_avatar and avatar and _urls_look_same(my_avatar, avatar):
            return True
        return False

    def _scrub_self_from_peer(self, row: dict[str, Any], *, peer_uid: str = "") -> dict[str, str]:
        cleaned = {
            "uid": str(row.get("uid") or peer_uid or ""),
            "name": str(row.get("name") or ""),
            "avatar": str(row.get("avatar") or ""),
            "job": str(row.get("job") or ""),
        }
        if not self._is_self_peer_row(cleaned, peer_uid=peer_uid):
            return cleaned
        # Drop polluted identity; keep uid/job only when they are not mine.
        my_uid = str(self._my_uid or "")
        if cleaned["uid"] == my_uid:
            cleaned["uid"] = str(peer_uid or "") if peer_uid != my_uid else ""
        cleaned["name"] = _fallback_peer_label(uid=cleaned["uid"] or peer_uid, job=cleaned["job"])
        cleaned["avatar"] = ""
        return cleaned

    def _resolve_peer_row(
        self,
        conversation_id: str,
        messages: list[dict[str, Any]] | None = None,
        *,
        persist: bool = False,
    ) -> dict[str, str]:
        cid = str(conversation_id or "")
        if not cid:
            return {"uid": "", "name": "", "avatar": "", "job": ""}
        cached = self._peer(cid)
        locked = self._locked_peer_uid(cid)
        uid = locked or str(cached.get("uid") or "")
        # Ignore cache polluted with my own identity.
        if cached and not self._is_self_peer_row(cached, peer_uid=uid):
            if (
                cached.get("name")
                and cached.get("name") != cid
                and not _is_uidish_name(str(cached.get("name") or ""), uid)
            ):
                return {
                    "uid": locked or uid or str(cached.get("uid") or ""),
                    "name": str(cached.get("name") or ""),
                    "avatar": str(cached.get("avatar") or ""),
                    "job": str(cached.get("job") or ""),
                }
        elif cached and self._is_self_peer_row(cached, peer_uid=uid):
            with self._lock:
                self._peers[cid] = {
                    "uid": uid if uid != str(self._my_uid or "") else "",
                    "name": "",
                    "avatar": "",
                    "job": str(cached.get("job") or ""),
                }
            cached = self._peer(cid)
            uid = str(cached.get("uid") or "")
        if not self._my_uid:
            self._refresh_me()
        peer_uid = locked or uid or self._peer_uid_for(cid)
        if peer_uid and peer_uid == str(self._my_uid or ""):
            peer_uid = self._locked_peer_uid(cid) or self._peer_uid_for(cid)
        meta = self._meta(cid)
        sec = str(meta.get("peer_sec_uid") or "")
        # Harvest sec_sender from peer messages only.
        if messages and peer_uid:
            for m in messages:
                if str(m.get("sender") or "") == peer_uid and m.get("sec_sender"):
                    candidate = str(m.get("sec_sender") or "").strip()
                    if candidate:
                        sec = candidate
                        self._remember_peer_sec(cid, peer_uid, sec)
                        break
        if peer_uid:
            if messages is not None:
                prof = peer_profile_for_conversation(
                    self._auth, cid, messages, sec_uid=sec
                )
            elif sec:
                prof = resolve_user_profile(self._auth, peer_uid, sec)
            else:
                prof = peer_profile_for_conversation(self._auth, cid, None, sec_uid=sec)
        else:
            prof = {}
        # If sec pointed at me, drop it and retry without sec.
        if isinstance(prof, dict) and self._is_self_peer_row(
            {
                "uid": str(prof.get("uid") or ""),
                "name": str(prof.get("nickname") or ""),
                "avatar": str(prof.get("avatar") or "") or avatar_from_user(prof),
            },
            peer_uid=peer_uid,
        ):
            with self._lock:
                prev = self._conv_meta.get(cid) or {}
                if prev.get("peer_sec_uid"):
                    self._conv_meta[cid] = {**prev, "peer_sec_uid": ""}
            if peer_uid:
                prof = peer_profile_for_conversation(self._auth, cid, messages, sec_uid="")
            else:
                prof = {}
        avatar = ""
        if isinstance(prof, dict):
            avatar = str(prof.get("avatar") or "") or avatar_from_user(prof)
        if not avatar:
            avatar = str(cached.get("avatar") or "")
        row = {
            "uid": locked or str(prof.get("uid") or peer_uid or ""),
            "name": _display_peer_name(prof) if prof else _fallback_peer_label(uid=peer_uid),
            "avatar": avatar,
            "job": str(prof.get("unique_id") or ""),
        }
        if _is_uidish_name(str(row.get("name") or ""), str(row.get("uid") or "")):
            row["name"] = _fallback_peer_label(
                uid=str(row.get("uid") or ""),
                name=str(row.get("name") or ""),
                job=str(row.get("job") or ""),
            )
        row = self._scrub_self_from_peer(row, peer_uid=peer_uid)
        if persist and (row.get("name") or row.get("avatar") or row.get("uid")):
            with self._lock:
                prev_peer = self._peers.get(cid) or {}
                self._peers[cid] = {
                    "name": row.get("name") or prev_peer.get("name") or "",
                    "avatar": row.get("avatar") or prev_peer.get("avatar") or "",
                    "uid": row.get("uid") or str(prev_peer.get("uid") or ""),
                    "job": row.get("job") or prev_peer.get("job") or "",
                }
                meta = self._conv_meta.get(cid) or {}
                self._conv_meta[cid] = {
                    **meta,
                    "conversation_id": cid,
                    "peer_uid": row.get("uid") or str(meta.get("peer_uid") or ""),
                    "peer_unique_id": row.get("job") or str(meta.get("peer_unique_id") or ""),
                }
        return row

    def _meta(self, conversation_id: str) -> dict[str, Any]:
        with self._lock:
            return dict(self._conv_meta.get(conversation_id) or {})

    def _peer(self, conversation_id: str) -> dict[str, Any]:
        with self._lock:
            return dict(self._peers.get(conversation_id) or {})

    def _load_thread(
        self,
        conversation_id: str,
        *,
        count: int = 40,
        anchor_index: int = 0,
        update_seen: bool = True,
    ) -> dict[str, Any]:
        conversation_id = str(conversation_id or "")
        count = min(max(int(count), 10), 80)
        if not self._my_uid:
            self._refresh_me()
        meta = self._ensure_conv_meta(conversation_id)
        cshort = int(meta.get("conversation_short_id") or 0)
        if not cshort:
            raise ValueError("unknown conversation")
        with self._imapi_lock:
            raw = get_messages_by_conversation(
                self._auth,
                conversation_id,
                cshort,
                limit=count,
                anchor_index=int(anchor_index or 0),
            )
        if not self._messages_belong_to_conversation(conversation_id, raw):
            logger.warning(
                "history peer mismatch for %s cshort=%s — clearing poisoned short id",
                conversation_id,
                cshort,
            )
            self._clear_poisoned_conversation(conversation_id)
            raise ValueError("conversation short id mismatch")
        locked_peer = self._locked_peer_uid(conversation_id)
        self._claim_cshort(conversation_id, cshort)
        peer_prof = peer_profile_for_conversation(self._auth, conversation_id, raw)
        peer_name = _display_peer_name(peer_prof) if isinstance(peer_prof, dict) else str(meta.get("peer_uid") or "")
        peer_avatar = avatar_from_user(peer_prof) if isinstance(peer_prof, dict) else ""
        prof_uid = str(peer_prof.get("uid") or "") if isinstance(peer_prof, dict) else ""
        if locked_peer and prof_uid and prof_uid != locked_peer and prof_uid != str(self._my_uid or ""):
            logger.warning(
                "history profile uid mismatch for %s locked=%s got=%s",
                conversation_id,
                locked_peer,
                prof_uid,
            )
            self._clear_poisoned_conversation(conversation_id)
            raise ValueError("conversation peer mismatch")
        peer = {
            "uid": locked_peer or prof_uid or str(meta.get("peer_uid") or ""),
            "friendId": conversation_id,
            "name": peer_name,
            "avatar": peer_avatar,
            "job": str(peer_prof.get("unique_id") or "") if isinstance(peer_prof, dict) else "",
        }
        with self._lock:
            self._peers[conversation_id] = dict(peer)
        self._remember_meta(conversation_item(
            index=0,
            conversation_id=conversation_id,
            conversation_short_id=cshort,
            peer_uid=peer["uid"],
            peer_unique_id=peer["job"],
            name=peer_name,
            avatar=peer_avatar,
        ))
        ordered = sort_messages(raw)
        messages: list[dict[str, Any]] = []
        seen = self._seen.setdefault(conversation_id, set())
        for msg in ordered:
            view = history_message(
                self._auth,
                msg,
                my_uid=self._my_uid,
                peer_name=peer_name,
                peer_avatar=peer_avatar,
                my_name=str(self._me.get("name") or "我"),
                my_avatar=str(self._me.get("avatar") or ""),
            )
            if not view:
                continue
            if not self._view_belongs_to_conversation(conversation_id, view):
                continue
            if view.get("mine") and view.get("avatar"):
                self._remember_my_avatar(str(view.get("avatar") or ""))
            mid = str(view.get("mid") or "")
            if mid and update_seen:
                seen.add(mid)
            messages.append(view)
        indices: list[int] = []
        for msg in ordered:
            try:
                indices.append(int(msg.get("index_in_conversation") or 0))
            except (TypeError, ValueError):
                continue
        min_index = min(indices) if indices else 0
        has_more = len(ordered) >= count and min_index > 0
        preview = messages[-1]["text"] if messages else ""
        return {
            "friendId": conversation_id,
            "peer": peer,
            "messages": messages,
            "hasMore": has_more,
            "nextCursor": min_index if has_more else None,
            "lastMessage": preview,
        }

    def _fetch_peer_later(self, conversation_id: str, conversation_short_id: int) -> None:
        cid = str(conversation_id or "")
        if not cid or not conversation_short_id:
            return
        with self._lock:
            if cid in self._peer_fetching:
                return
            self._peer_fetching.add(cid)

        def work() -> None:
            try:
                payload = self._load_thread(cid, count=40, anchor_index=0, update_seen=False)
                payload = {**payload, "source": "history"}
                payload = self._merge_history_with_live_cache(cid, payload)
                with self._lock:
                    self._thread_cache[cid] = payload
                peer = payload.get("peer") or {}
                self._broadcast({
                    "type": "peer",
                    "friendId": cid,
                    "uid": str(peer.get("uid") or ""),
                    "name": str(peer.get("name") or ""),
                    "avatar": str(peer.get("avatar") or ""),
                    "job": str(peer.get("job") or ""),
                })
                self._broadcast({"type": "thread", **{k: v for k, v in payload.items() if k != "source"}})
            except Exception:
                logger.debug("peer/thread prefetch failed", exc_info=True)
            finally:
                with self._lock:
                    self._peer_fetching.discard(cid)

        threading.Thread(target=work, name="douyin-web-peer", daemon=True).start()

    def api_me(self) -> dict[str, Any]:
        if not self._me.get("uid"):
            self._refresh_me()
        from boss_cli.douyin.credentials import im_cred_status, load_im_cred
        from boss_cli.douyin.im import _apply_cred, _send_cred_missing

        cred_flags = im_cred_status()
        missing_file = [k for k, ok in cred_flags.items() if not ok]
        missing_runtime: list[str] = []
        try:
            local = load_im_cred(sessionid=str(self._auth.cookie.get("sessionid") or ""))
            if local:
                _apply_cred(self._auth, local)
            missing_runtime = _send_cred_missing(self._auth)
        except Exception:
            missing_runtime = missing_file or ["DY_TICKET"]
        ready = not missing_runtime and not missing_file
        return {
            "ok": True,
            "schema_version": "1",
            "data": {
                "me": self._me,
                "mqtt": self._poll_status,
                "sendCred": {
                    "ready": ready,
                    "missing": missing_runtime or missing_file,
                    "file": "im_cred.json",
                },
            },
        }

    def api_conversations(self, offset: int, limit: int, *, scope: str = "all") -> dict[str, Any]:
        """List conversations (full inbox, newest first).

        scope=recent is kept for compatibility but behaves the same as all.
        Live WS sessions are merged via SSE and _merge_local_conversations.
        """
        offset = max(0, int(offset))
        limit = min(max(1, int(limit or 100)), 100)
        if not self._my_uid:
            self._refresh_me()

        with self._lock:
            cache_age = time.time() - float(self._conversations_cache_at or 0)
            cached = list(self._conversations_cache) if self._conversations_cache else []

        if offset == 0 and cached and cache_age < CONV_CACHE_TTL_S:
            self._refresh_inbox_async(announce_new=False)
            full = self._sort_conversations_by_recent(
                [self._fill_item_last_activity(it, network=False) for it in self._merge_local_conversations(cached)]
            )
        else:
            full = self._build_inbox_items()
            with self._lock:
                self._conversations_cache = list(full)
                self._conversations_cache_at = time.time()

        with self._lock:
            self._conversations_cache = list(full)

        # Enrich the full inbox first; only then filter incomplete profiles for UI.
        self._schedule_list_enrich(full)
        if full:
            threading.Thread(
                target=self._enrich_conversation_items,
                args=(list(full[: min(len(full), INBOX_CANDIDATE_LIMIT)]),),
                name="douyin-web-conv-enrich",
                daemon=True,
            ).start()

        visible = self._filter_list_ready(self._dedupe_conversations_by_peer(list(full)))
        refresh_n = min(len(visible), 10)
        for i in range(refresh_n):
            visible[i] = self._refresh_row_preview_from_api(dict(visible[i]))
        total = len(visible)
        sliced = visible[offset : offset + limit]
        next_offset = offset + len(sliced)
        return {
            "ok": True,
            "schema_version": "1",
            "data": {
                "conversations": sliced,
                "total": total,
                "offset": offset,
                "limit": limit,
                "scope": "all",
                "nextOffset": next_offset if next_offset < total else None,
            },
        }

    def _build_inbox_items(self) -> list[dict[str, Any]]:
        """Fetch inbox candidates, attach last activity, sort by recency (no trim)."""
        # 对齐小红书（limit=100）：拉 2 页最多 100 个历史会话，不只显示 1 页 50 个
        raw = self._list_conversations_safe(page_size=50, max_pages=2)
        for conv in raw:
            self._register_conv_raw(conv)
        with self._lock:
            self._inbox_order = [
                str(c.get("conversation_id") or "")
                for c in raw
                if c.get("conversation_id")
            ]
        items: list[dict[str, Any]] = []
        for j, conv in enumerate(raw[:INBOX_CANDIDATE_LIMIT]):
            try:
                built = self._build_conversation_item(
                    conv,
                    j + 1,
                    with_preview=True,
                    resolve_profile=False,
                )
            except Exception:
                logger.debug("build inbox item failed", exc_info=True)
                built = self._build_conversation_item_light(conv, j + 1)
            items.append(self._fill_item_last_activity(built))
        items = self._merge_local_conversations(items)
        items = [self._fill_item_last_activity(it) for it in items]
        items = [
            it for it in items
            if _is_conversation_id(str(it.get("friendId") or ""))
        ]
        items = self._sort_conversations_by_recent(items)
        # Resolve real nicknames/avatars for the most recent chats (first paint target).
        for i, row in enumerate(items[:RECENT_INBOX_LIMIT]):
            cid = str(row.get("friendId") or "")
            cshort = int(self._meta(cid).get("conversation_short_id") or 0)
            if not cid or not cshort or self._peer_identity_ready(cid):
                continue
            try:
                built = self._build_conversation_item(
                    {"conversation_id": cid, "conversation_short_id": cshort},
                    int(row.get("index") or i + 1),
                    with_preview=False,
                    resolve_profile=True,
                )
                for key in ("name", "avatar", "uid", "job", "lastMessage", "lastTime", "lastTs"):
                    val = built.get(key)
                    if val not in (None, ""):
                        row[key] = val
            except Exception:
                logger.debug("recent inbox profile resolve failed for %s", cid, exc_info=True)
        # Keep incomplete rows in cache so background enrich can fill nickname/avatar.
        return items

    def api_messages(
        self,
        conversation_id: str,
        *,
        count: int = 40,
        anchor_index: int = 0,
    ) -> dict[str, Any]:
        conversation_id = str(conversation_id or "")
        anchor_index = int(anchor_index or 0)
        meta = self._meta(conversation_id)
        cshort = int(meta.get("conversation_short_id") or 0)
        if anchor_index == 0:
            # 对齐小红书 web_im（load_chats）：每次打开会话先刷新会话列表，
            # 保证最新消息不漏拉，不直接显示旧缓存。
            try:
                self._refresh_inbox_list(announce_new=False)
            except Exception:
                logger.debug("refresh inbox before history failed", exc_info=True)
            cached = self._thread_cache.get(conversation_id)
            # Only reuse a complete history cache. Live/WS stubs are incomplete and
            # hide older image/voice messages if we short-circuit here.
            cache_complete = bool(
                cached
                and cached.get("messages") is not None
                and cached.get("source") == "history"
                and not self._thread_needs_media_repair(list(cached.get("messages") or []))
            )
            if cache_complete:
                # 小红书方案：刷新收件箱后若发现该会话有比缓存更新的消息，
                # 丢弃旧缓存强制重拉最新历史（不显示旧历史）。
                inbox_ts = self._inbox_last_ts(conversation_id)
                cache_last_ts = max(
                    (int(m.get("ts") or 0) for m in (cached.get("messages") or [])),
                    default=0,
                )
                if inbox_ts and inbox_ts > cache_last_ts:
                    with self._lock:
                        self._thread_cache.pop(conversation_id, None)
                    cache_complete = False
            if cache_complete:
                cached_msgs = self._filter_views_for_conversation(
                    conversation_id,
                    list(cached.get("messages") or []),
                )
                if len(cached_msgs) != len(cached.get("messages") or []):
                    # Poisoned mid-stream cache — force a fresh history fetch.
                    with self._lock:
                        self._thread_cache.pop(conversation_id, None)
                    cache_complete = False
                elif not cached_msgs and (cached.get("messages") or []):
                    with self._lock:
                        self._thread_cache.pop(conversation_id, None)
                    cache_complete = False
            if cache_complete:
                self._mark_seen_from_views(conversation_id, cached_msgs)
                self.set_active_conversation(conversation_id)
                live_peer = self._peer(conversation_id)
                peer = dict(cached.get("peer") or {})
                if live_peer:
                    for key in ("uid", "name", "avatar", "job"):
                        val = live_peer.get(key)
                        if val and (
                            key != "name"
                            or not _is_uidish_name(
                                str(val),
                                str(live_peer.get("uid") or peer.get("uid") or ""),
                            )
                        ):
                            peer[key] = val
                        elif val and key != "name" and not peer.get(key):
                            peer[key] = val
                peer["friendId"] = conversation_id
                locked = self._locked_peer_uid(conversation_id)
                if locked:
                    peer["uid"] = locked
                peer_uid = str(peer.get("uid") or meta.get("peer_uid") or "")
                if not self._peer_identity_ready(conversation_id):
                    if cshort:
                        self._enrich_peer_later(conversation_id, cshort)
                    elif peer_uid:
                        self._enrich_peer_by_uid_later(conversation_id, peer_uid, None)
                return {
                    "ok": True,
                    "schema_version": "1",
                    "data": {
                        "friendId": conversation_id,
                        "peer": peer,
                        "messages": cached_msgs,
                        "hasMore": bool(cached.get("hasMore")),
                        "nextCursor": cached.get("nextCursor"),
                        "source": "history",
                    },
                }
        try:
            payload = self._load_thread(
                conversation_id,
                count=count,
                anchor_index=anchor_index,
                update_seen=True,
            )
        except ValueError:
            # cshort 未知时先刷收件箱再试，避免空 live stub 盖掉历史图片/语音。
            if anchor_index == 0:
                try:
                    self._refresh_inbox_list(announce_new=False)
                    meta = self._ensure_conv_meta(conversation_id)
                    cshort = int(meta.get("conversation_short_id") or 0)
                    if cshort:
                        payload = self._load_thread(
                            conversation_id,
                            count=count,
                            anchor_index=0,
                            update_seen=True,
                        )
                    else:
                        raise ValueError("unknown conversation")
                except Exception:
                    live = self._live_thread_payload(conversation_id)
                    if live is not None:
                        live = {**live, "source": "live"}
                        self._mark_seen_from_views(conversation_id, list(live.get("messages") or []))
                        # Do not replace a richer history cache with empty/live stub.
                        prev_cache = self._thread_cache.get(conversation_id) or {}
                        if prev_cache.get("source") == "history" and prev_cache.get("messages"):
                            live_msgs = self._filter_views_for_conversation(
                                conversation_id,
                                list(live.get("messages") or []),
                            )
                            if live_msgs:
                                seen = {str(m.get("mid") or "") for m in (prev_cache.get("messages") or []) if m.get("mid")}
                                extras = [m for m in live_msgs if m.get("mid") and str(m.get("mid")) not in seen]
                                if extras:
                                    merged = sorted(
                                        list(prev_cache.get("messages") or []) + extras,
                                        key=lambda m: (int(m.get("ts") or 0), str(m.get("mid") or "")),
                                    )
                                    prev_cache = {**prev_cache, "messages": merged}
                                    self._thread_cache[conversation_id] = prev_cache
                            self.set_active_conversation(conversation_id)
                            return {
                                "ok": True,
                                "schema_version": "1",
                                "data": {
                                    "friendId": conversation_id,
                                    "peer": prev_cache.get("peer") or live.get("peer") or {},
                                    "messages": list(prev_cache.get("messages") or []),
                                    "hasMore": bool(prev_cache.get("hasMore")),
                                    "nextCursor": prev_cache.get("nextCursor"),
                                    "source": "history",
                                },
                            }
                        self._thread_cache[conversation_id] = live
                        self.set_active_conversation(conversation_id)
                        return {
                            "ok": True,
                            "schema_version": "1",
                            "data": {
                                "friendId": conversation_id,
                                "peer": live.get("peer") or {},
                                "messages": list(live.get("messages") or []),
                                "hasMore": bool(live.get("hasMore")),
                                "nextCursor": live.get("nextCursor"),
                                "source": "live",
                            },
                        }
                    return {
                        "ok": False,
                        "schema_version": "1",
                        "data": None,
                        "error": {"code": "invalid_params", "message": "未知会话，请刷新列表后重试"},
                    }
            else:
                return {
                    "ok": False,
                    "schema_version": "1",
                    "data": None,
                    "error": {"code": "invalid_params", "message": "未知会话，请刷新列表后重试"},
                }
        if anchor_index == 0:
            # Merge any newer live-only messages that arrived while history loaded.
            prev = self._thread_cache.get(conversation_id) or {}
            if prev.get("messages"):
                payload = self._merge_history_with_live_cache(conversation_id, payload)
            payload = {**payload, "source": "history"}
            self._thread_cache[conversation_id] = payload
        self.set_active_conversation(conversation_id)
        return {
            "ok": True,
            "schema_version": "1",
            "data": {
                "friendId": conversation_id,
                "peer": payload["peer"],
                "messages": payload["messages"],
                "hasMore": payload["hasMore"],
                "nextCursor": payload["nextCursor"],
                "source": payload.get("source") or ("history" if anchor_index == 0 else ""),
            },
        }

    def api_send(self, conversation_id: str, text: str) -> dict[str, Any]:
        text = (text or "").strip()
        if not text:
            return {
                "ok": False,
                "schema_version": "1",
                "data": None,
                "error": {"code": "invalid_params", "message": "消息内容不能为空"},
            }
        if len(text) > 2000:
            return {
                "ok": False,
                "schema_version": "1",
                "data": None,
                "error": {"code": "invalid_params", "message": "消息过长"},
            }
        conversation_id = str(conversation_id or "")
        if not self._my_uid:
            self._refresh_me()

        # 确保 peer_uid 正确（从 conversation_id 解析，不依赖 meta 缓存）
        peer_uid = ""
        if self._my_uid and conversation_id:
            try:
                peer_uid = peer_uid_from_conversation(conversation_id, self._my_uid)
            except Exception:
                peer_uid = ""

        meta = self._ensure_conv_meta(conversation_id)
        cshort = int(meta.get("conversation_short_id") or 0)
        # meta 中的 peer_uid 优先（可能已通过收件箱刷新补全）
        if not peer_uid:
            peer_uid = str(meta.get("peer_uid") or "") or str(self._peer(conversation_id).get("uid") or "")

        # cshort=0 时先同步刷新收件箱，尝试获取 conversation_short_id
        if not cshort:
            try:
                self._refresh_inbox_list(announce_new=False)
                meta = self._ensure_conv_meta(conversation_id)
                cshort = int(meta.get("conversation_short_id") or 0)
                if not peer_uid:
                    peer_uid = str(meta.get("peer_uid") or "")
            except Exception:
                logger.debug("refresh inbox before send failed", exc_info=True)

        peer = self._peer(conversation_id)
        logger.info(
            "send message: cid=%s cshort=%d peer_uid=%s text_len=%d",
            conversation_id,
            cshort,
            peer_uid,
            len(text),
        )
        if not peer_uid and not cshort:
            return {
                "ok": False,
                "schema_version": "1",
                "data": None,
                "error": {
                    "code": "invalid_params",
                    "message": "会话信息不完整，请先打开该会话或等待列表刷新后再发",
                },
            }
        try:
            ensure_send_cred(self._auth, headed=False)
            # Always pass peer_uid so create_conversation can run when ticket/cshort missing.
            try:
                result = send_text(
                    self._auth,
                    text,
                    conversation_id=conversation_id,
                    conversation_short_id=cshort,
                    to_user_id=peer_uid,
                )
            except Exception as first_exc:
                # One retry after reloading im_cred.json (transient ticket / network blips).
                logger.info("send retry after: %s", first_exc)
                ensure_send_cred(self._auth, headed=False)
                result = send_text(
                    self._auth,
                    text,
                    conversation_id=conversation_id,
                    conversation_short_id=cshort,
                    to_user_id=peer_uid,
                )
        except Exception as exc:
            logger.warning("send failed: %s", exc, exc_info=True)
            return {
                "ok": False,
                "schema_version": "1",
                "data": None,
                "error": {"code": "api_error", "message": str(exc)},
            }

        # 发送后用返回的 cid/cshort 更新 meta（create_conversation 可能返回新值）
        ret_cid = str(result.get("conversation_id") or conversation_id)
        ret_cshort = int(result.get("conversation_short_id") or cshort or 0)
        if ret_cid:
            with self._lock:
                prev = self._conv_meta.get(ret_cid) or self._conv_meta.get(conversation_id) or {}
                self._conv_meta[ret_cid] = {
                    "conversation_id": ret_cid,
                    "conversation_short_id": ret_cshort or int(prev.get("conversation_short_id") or 0),
                    "peer_uid": peer_uid or str(prev.get("peer_uid") or ""),
                    "peer_unique_id": str(prev.get("peer_unique_id") or ""),
                }
            if ret_cid != conversation_id:
                logger.info("send remapped conv cid %s -> %s cshort=%d", conversation_id, ret_cid, ret_cshort)

        if not result.get("ok", True):
            err_msg = str(result.get("error_desc") or result.get("message") or "发送失败")
            logger.warning("send returned not-ok: %s", err_msg)
            return {
                "ok": False,
                "schema_version": "1",
                "data": None,
                "error": {"code": "api_error", "message": err_msg},
            }

        event = live_message(
            conversation_id=ret_cid,
            peer_uid=peer_uid or str(peer.get("uid") or ""),
            text=text,
            mine=True,
            from_uid=self._my_uid,
            avatar=str(self._me.get("avatar") or ""),
        )
        mid = str(result.get("server_message_id") or result.get("client_message_id") or f"local-{time.time_ns()}")
        event["mid"] = mid
        with self._lock:
            self._seen.setdefault(ret_cid, set()).add(mid)
            if conversation_id and conversation_id != ret_cid:
                self._seen.setdefault(conversation_id, set()).add(mid)
        self._upsert_conversation_cache_row(
            {
                "friendId": ret_cid,
                "uid": peer_uid or str(peer.get("uid") or ""),
                "name": str(peer.get("name") or ""),
                "avatar": str(peer.get("avatar") or ""),
                "lastMessage": text,
            },
            prepend=True,
        )
        self.set_active_conversation(ret_cid)
        self._broadcast(event)
        return {"ok": True, "schema_version": "1", "data": event}

    def _download_media_bytes(self, url: str) -> bytes:
        safe = allowed_media_url(url)
        if not safe:
            return b""
        try:
            import httpx
        except ImportError:
            return b""
        cookie = self.credential.cookie
        try:
            with httpx.Client(timeout=30.0, follow_redirects=True) as client:
                resp = client.get(
                    safe,
                    headers={
                        "Cookie": cookie,
                        "Referer": "https://www.douyin.com/",
                        "User-Agent": self._auth.client.user_agent,
                    },
                )
            if resp.status_code >= 400:
                return b""
            data = resp.content or b""
            if not data or len(data) > MEDIA_MAX_BYTES:
                return b""
            return data
        except Exception:
            logger.debug("douyin media download failed for %s", url, exc_info=True)
            return b""

    def _download_display_image(self, url: str) -> tuple[bytes, str] | None:
        from .im_media import sniff_content_type

        last_heic: tuple[bytes, str] | None = None
        for candidate in media_url_fallbacks(url):
            raw = self._download_media_bytes(candidate)
            if not raw:
                continue
            ctype = sniff_content_type(raw, candidate)
            if ctype.startswith("image/") and ctype not in {"image/heic", "image/heif"}:
                return raw, ctype
            if ctype in {"image/heic", "image/heif"}:
                last_heic = (raw, ctype)
        return last_heic

    def fetch_media(
        self,
        url: str,
        *,
        filename: str = "",
        skey: str = "",
        oid: str = "",
        mid: str = "",
    ) -> tuple[bytes, str] | None:
        mid = str(mid or "").strip()
        if mid:
            hit = cached_bytes(mid)
            if hit:
                return hit

        candidates: list[str] = []
        fetch_url = (url or "").strip()
        if fetch_url:
            candidates.extend(media_url_fallbacks(fetch_url) or [fetch_url])
        if mid:
            for alt in image_urls_for_mid(mid):
                for item in media_url_fallbacks(alt) or [alt]:
                    if item not in candidates:
                        candidates.append(item)
        if oid:
            oid_url = f"https://p3.douyinpic.com/obj/{oid}"
            if oid_url not in candidates:
                candidates.append(oid_url)
        if not candidates and not mid:
            return None

        skey = str(skey or "")
        oid = str(oid or "")

        # Stickers / avatars / emoji are usually plain images on CDN.
        if fetch_url and not skey and not oid:
            from .im_media import store_bytes

            displayed = self._download_display_image(fetch_url)
            if displayed:
                raw, ctype = displayed
                if ctype.startswith("image/") and ctype not in {"image/heic", "image/heif"}:
                    return store_bytes(mid, raw, ctype) if mid else (raw, ctype)

        # Encrypted IM photos (type=27): download CDN + AES-GCM decrypt with skey,
        # matching spider/js dy_im_openable.py. Fall back to inline_pic via mid cache.
        from .im_media import store_bytes

        for candidate in candidates:
            raw = self._download_media_bytes(candidate)
            if not raw:
                continue
            resolved = resolve_media_bytes(
                raw,
                url=candidate,
                skey=skey,
                oid=oid,
                mid=mid,
            )
            if resolved:
                return resolved

        if mid:
            resolved = resolve_media_bytes(
                b"",
                url=fetch_url,
                skey=skey,
                oid=oid,
                mid=mid,
            )
            if resolved:
                return resolved
        return None

    def _register_conv_raw(self, conv: dict[str, Any]) -> str:
        cid = str(conv.get("conversation_id") or "")
        if not cid:
            return ""
        cshort = int(conv.get("conversation_short_id") or 0)
        with self._lock:
            self._conv_raw_by_id[cid] = dict(conv)
            prev = self._conv_meta.get(cid) or {}
            prev_peer = self._peers.get(cid) or {}
            if cshort or not prev:
                peer_uid = self._locked_peer_uid(cid)
                if not peer_uid and self._my_uid:
                    try:
                        peer_uid = peer_uid_from_conversation(cid, self._my_uid)
                    except Exception:
                        peer_uid = peer_uid or str(prev.get("peer_uid") or "")
                self._conv_meta[cid] = {
                    "conversation_id": cid,
                    "conversation_short_id": cshort or int(prev.get("conversation_short_id") or 0),
                    "peer_uid": peer_uid or str(prev.get("peer_uid") or ""),
                    "peer_unique_id": str(prev.get("peer_unique_id") or ""),
                }
                if peer_uid:
                    self._sync_locked_peer_meta(cid)
        if cshort:
            self._claim_cshort(cid, cshort)
        return cid

    def _refresh_inbox_list(self, *, announce_new: bool = True) -> list[dict[str, Any]]:
        if not self._inbox_lock.acquire(blocking=False):
            return []
        try:
            return self._refresh_inbox_list_locked(announce_new=announce_new)
        finally:
            self._inbox_lock.release()

    def _log_inbox_health(self, *, raw_count: int = 0, cache_count: int = 0) -> None:
        """Log when inbox sessions exist but would have been hidden by strict profile filters."""
        try:
            with self._lock:
                cached = list(self._conversations_cache)
            merged = self._merge_local_conversations(cached)
            visible = self._filter_list_ready(self._dedupe_conversations_by_peer(list(merged)))
            raw_n = int(raw_count or len(self._inbox_order))
            cache_n = int(cache_count or len(merged))
            vis_n = len(visible)
            logger.info(
                "inbox health: api=%d cache=%d visible=%d ws_status=%s",
                raw_n,
                cache_n,
                vis_n,
                self._poll_status,
            )
            if raw_n > 0 and vis_n == 0:
                logger.warning(
                    "inbox: %d 个会话但侧栏可见 0 条（多为资料未补全）；请确认 uid/ticket 与当前账号一致",
                    raw_n,
                )
        except Exception:
            logger.debug("inbox health log failed", exc_info=True)

    def _refresh_inbox_list_locked(self, *, announce_new: bool = True) -> list[dict[str, Any]]:
        if not self._my_uid:
            self._refresh_me()
        try:
            raw = self._list_conversations_safe(page_size=50, max_pages=1)
        except Exception:
            logger.debug("inbox list refresh failed", exc_info=True)
            return []
        with self._lock:
            prev_ids = set(self._conv_meta.keys())
        for conv in raw:
            self._register_conv_raw(conv)
        with self._lock:
            self._inbox_order = [
                str(c.get("conversation_id") or "")
                for c in raw
                if c.get("conversation_id")
            ]
        if announce_new:
            for conv in raw:
                cid = str(conv.get("conversation_id") or "")
                if not cid or cid in prev_ids:
                    continue
                cshort = int(conv.get("conversation_short_id") or 0)
                peer_uid = ""
                if self._my_uid:
                    try:
                        peer_uid = peer_uid_from_conversation(cid, self._my_uid)
                    except Exception:
                        peer_uid = ""
                item = conversation_item(
                    index=1,
                    conversation_id=cid,
                    conversation_short_id=cshort,
                    peer_uid=peer_uid,
                    name=peer_uid or "新会话",
                )
                self._remember_meta(item)
                self._broadcast({"type": "conv", **{k: v for k, v in item.items() if k != "_meta"}})
                if cshort:
                    self._enrich_peer_later(cid, cshort)
                    # Pull the greeting / latest message for brand-new sessions.
                    threading.Thread(
                        target=self._poll_conversation_catchup,
                        args=(cid,),
                        name="douyin-web-new-conv",
                        daemon=True,
                    ).start()
        if announce_new and raw:
            try:
                full = self._build_inbox_items()
            except Exception:
                logger.debug("rebuild inbox cache failed", exc_info=True)
                full = [
                    self._build_conversation_item_light(conv, idx + 1)
                    for idx, conv in enumerate(raw[:INBOX_CANDIDATE_LIMIT])
                ]
                full = self._sort_conversations_by_recent(self._merge_local_conversations(full))
            with self._lock:
                self._conversations_cache = full
                self._conversations_cache_at = time.time()
            for conv in raw[:INBOX_CANDIDATE_LIMIT]:
                cid = str(conv.get("conversation_id") or "")
                cshort = int(conv.get("conversation_short_id") or 0)
                if cid and cshort:
                    self._enrich_peer_later(cid, cshort)
        self._log_inbox_health(raw_count=len(raw))
        return raw

    def _refresh_inbox_async(self, *, announce_new: bool = True) -> None:
        threading.Thread(
            target=self._refresh_inbox_safe,
            kwargs={"announce_new": announce_new},
            name="douyin-web-inbox",
            daemon=True,
        ).start()

    def _refresh_inbox_safe(self, *, announce_new: bool = True) -> None:
        try:
            self._refresh_inbox_list(announce_new=announce_new)
        except Exception:
            logger.debug("inbox refresh failed", exc_info=True)

    def _enqueue_ws_message(self, raw: dict[str, Any]) -> None:
        try:
            self._ws_msg_queue.put_nowait(dict(raw))
        except queue.Full:
            logger.warning("douyin ws message queue full, dropping frame")

    def _ws_message_worker(self) -> None:
        while not self._stop.is_set():
            try:
                raw = self._ws_msg_queue.get(timeout=0.5)
            except queue.Empty:
                continue
            try:
                self._handle_ws_message(raw)
            except Exception:
                logger.debug("ws message worker failed", exc_info=True)

    def _ws_set_status(self, status: str, *, detail: str = "") -> None:
        self._poll_status = status
        payload: dict[str, Any] = {"type": "status", "mqtt": status, "me": self._me}
        if detail:
            payload["detail"] = detail
        self._broadcast(payload)

    def _handle_ws_message(self, raw: dict[str, Any]) -> None:
        conversation_id = str(raw.get("conversation_id") or "")
        if not conversation_id:
            return
        if not self._my_uid:
            self._refresh_me()

        cshort = 0
        try:
            cshort = int(raw.get("conversation_short_id") or 0)
        except (TypeError, ValueError):
            cshort = 0

        with self._lock:
            known = conversation_id in self._conv_meta
            prev = self._conv_meta.get(conversation_id) or {}

        logger.info(
            "ws msg: cid=%s cshort=%d known=%s mt=%s mid=%s",
            conversation_id,
            cshort,
            known,
            raw.get("message_type"),
            raw.get("server_message_id") or raw.get("index_in_conversation") or "",
        )

        # 从 conversation_id 解析 peer_uid（即使 cshort=0 也能解析）
        peer_uid = str(prev.get("peer_uid") or "")
        if not peer_uid and self._my_uid:
            try:
                peer_uid = peer_uid_from_conversation(conversation_id, self._my_uid)
            except Exception:
                peer_uid = ""

        if cshort or not known:
            with self._lock:
                self._conv_meta[conversation_id] = {
                    "conversation_id": conversation_id,
                    "conversation_short_id": cshort or int(prev.get("conversation_short_id") or 0),
                    "peer_uid": peer_uid or str(prev.get("peer_uid") or ""),
                    "peer_unique_id": str(prev.get("peer_unique_id") or ""),
                    "peer_sec_uid": str(prev.get("peer_sec_uid") or ""),
                }
        sender = str(raw.get("sender") or "")
        sec_sender = str(raw.get("sec_sender") or "")
        # Only remember sec_sender from the *peer*, never from my own outbound messages.
        if sec_sender and sender and self._my_uid and sender != str(self._my_uid):
            self._remember_peer_sec(conversation_id, sender, sec_sender)

        # 新会话：即使 cshort=0 也广播基础会话项，并异步刷新收件箱补全 cshort
        if not known:
            # Resolve nickname/avatar BEFORE broadcasting so the list isn't stuck on uid.
            peer_boot = self._fill_peer_for_message(
                conversation_id,
                peer_uid=peer_uid,
                raw_message=raw,
            )
            boot_name = str(peer_boot.get("name") or "")
            if _is_uidish_name(boot_name, peer_uid):
                boot_name = str(peer_boot.get("job") or "") or _fallback_peer_label(uid=peer_uid) or "新会话"
            item = conversation_item(
                index=1,
                conversation_id=conversation_id,
                conversation_short_id=cshort,
                peer_uid=str(peer_boot.get("uid") or peer_uid or ""),
                peer_unique_id=str(peer_boot.get("job") or ""),
                name=boot_name,
                avatar=str(peer_boot.get("avatar") or ""),
            )
            public_item = {k: v for k, v in item.items() if k != "_meta"}
            # Persist into list cache BEFORE inbox refresh, otherwise refresh races and drops it.
            self._upsert_conversation_cache_row(public_item, prepend=True)
            self._broadcast({"type": "conv", **public_item})
            self._refresh_inbox_async(announce_new=True)
            if cshort:
                self._enrich_peer_later(conversation_id, cshort)
            elif peer_uid:
                self._enrich_peer_by_uid_later(conversation_id, peer_uid, raw)

        meta = self._ensure_conv_meta(conversation_id)
        if not known:
            cshort_resolved = int(meta.get("conversation_short_id") or cshort or 0)
            if cshort_resolved:
                threading.Thread(
                    target=self._poll_conversation_catchup,
                    args=(conversation_id,),
                    name="douyin-web-new-ws-catchup",
                    daemon=True,
                ).start()
        peer = self._fill_peer_for_message(
            conversation_id,
            peer_uid=peer_uid,
            raw_message=raw,
        )
        peer_name = str(peer.get("name") or meta.get("peer_uid") or peer_uid or "")
        peer_avatar = str(peer.get("avatar") or "")

        # 确保 mid 存在（WS推送可能 server_message_id 为空，用 content hash 兜底）
        mid = str(raw.get("server_message_id") or raw.get("index_in_conversation") or "")
        if not mid:
            content = str(raw.get("content") or "")
            mid = f"ws-{abs(hash((conversation_id, content, int(raw.get('create_time_ms') or 0))))}"
            raw = dict(raw)
            raw["server_message_id"] = mid

        # 对图片/语音消息，主动缓存媒体URL（确保 /api/media 代理能找到）
        mt = int(raw.get("message_type") or 0)
        if mt in (5, 27, 17):
            try:
                from boss_cli.douyin.im import parse_media_urls
                from .im_media import remember_image_urls, remember_inline_pic

                media = parse_media_urls(str(raw.get("content") or ""))
                urls = list(media.get("urls") or [])
                raw_obj = media.get("raw") if isinstance(media.get("raw"), dict) else {}
                if urls and mid:
                    remember_image_urls(mid, urls)
                inline = str(raw_obj.get("inline_pic") or "")
                if inline and mid:
                    remember_inline_pic(mid, inline)
            except Exception:
                logger.debug("cache media urls for ws message failed", exc_info=True)

        view = history_message(
            self._auth,
            raw,
            my_uid=self._my_uid,
            peer_name=peer_name,
            peer_avatar=peer_avatar,
            my_name=str(self._me.get("name") or "我"),
            my_avatar=str(self._me.get("avatar") or ""),
            resolve_profiles=False,
        )
        if not view:
            return
        self._emit_live_view(conversation_id, view, peer=peer, meta=meta, raw_message=raw)
        # WS 图片/分享正文经常缺 CDN / itemId：立刻用会话历史补齐，避免永久停在 [图片]/「分享」。
        needs_share_repair = mt in (8, 77, 105, 110) and self._thread_needs_media_repair([view])
        needs_image_repair = mt in (5, 27) and self._thread_needs_media_repair([view])
        if needs_share_repair or needs_image_repair:
            repair_mid = str(view.get("mid") or mid or "")
            if repair_mid:
                with self._lock:
                    self._seen.setdefault(conversation_id, set()).discard(repair_mid)
            cshort_for_catchup = int(meta.get("conversation_short_id") or cshort or 0)
            if cshort_for_catchup:
                threading.Thread(
                    target=self._poll_conversation_catchup,
                    args=(conversation_id,),
                    name="douyin-web-media-catchup",
                    daemon=True,
                ).start()
        cshort_final = int(meta.get("conversation_short_id") or cshort or 0)
        if cshort_final and not self._peer_identity_ready(conversation_id):
            self._enrich_peer_later(conversation_id, cshort_final)
        elif not cshort_final and peer_uid and not self._peer_identity_ready(conversation_id):
            self._enrich_peer_by_uid_later(conversation_id, peer_uid, raw)

    def _ws_loop(self) -> None:
        reconnect_delay = WS_RECONNECT_MIN_S
        while not self._stop.is_set():
            try:
                if not self._my_uid:
                    self._refresh_me()
                device_id = resolve_device_id(self._auth)
                if not device_id:
                    device_id = str(self._my_uid or "").strip()
                if not device_id:
                    raise RuntimeError("缺少 device_id，无法连接 frontier-im（请重新 grab-ticket --qr）")
                logger.info("frontier-im device_id=%s", device_id)
                self._ws_set_status("connecting")

                def on_connected() -> None:
                    nonlocal reconnect_delay
                    reconnect_delay = WS_RECONNECT_MIN_S
                    self._ws_set_status("online")
                    self._refresh_inbox_async(announce_new=True)
                    threading.Thread(
                        target=self._log_inbox_health,
                        name="douyin-web-inbox-health",
                        daemon=True,
                    ).start()

                run_im_ws_loop(
                    self._auth,
                    device_id=device_id,
                    cookie_str=self.credential.cookie,
                    on_message=self._enqueue_ws_message,
                    stop=self._stop,
                    on_connected=on_connected,
                    on_refresh_list=lambda: self._refresh_inbox_async(announce_new=True),
                )
                if self._stop.is_set():
                    break
                raise RuntimeError("frontier-im 连接断开")
            except Exception as exc:
                if self._stop.is_set():
                    break
                logger.warning(
                    "douyin im ws disconnected: %s; reconnecting in %.1fs (delay cap %.1fs)",
                    exc,
                    reconnect_delay,
                    WS_RECONNECT_MAX_S,
                    exc_info=logger.isEnabledFor(logging.DEBUG),
                )
                self._ws_set_status("reconnecting", detail=str(exc))
                # 重连前刷新账号信息（防止 uid 变化或 cookie 过期导致的持续失败）
                try:
                    self._refresh_me()
                except Exception:
                    logger.debug("refresh_me before ws reconnect failed", exc_info=True)
                if self._stop.wait(reconnect_delay):
                    return
                reconnect_delay = min(WS_RECONNECT_MAX_S, reconnect_delay * 2)
        self._poll_status = "stopped"

    def _emit_live_view(
        self,
        conversation_id: str,
        view: dict[str, Any],
        *,
        peer: dict[str, Any],
        meta: dict[str, Any],
        raw_message: dict[str, Any] | None = None,
    ) -> None:
        mid = str(view.get("mid") or "")
        if not mid:
            return
        locked_peer = self._locked_peer_uid(conversation_id)
        if raw_message and not self._messages_belong_to_conversation(conversation_id, [raw_message]):
            logger.warning("skip foreign ws message for %s mid=%s", conversation_id, mid)
            self._clear_poisoned_conversation(conversation_id)
            return
        if not self._view_belongs_to_conversation(conversation_id, view):
            logger.warning("skip foreign live view for %s mid=%s", conversation_id, mid)
            return
        seen = self._seen.setdefault(conversation_id, set())
        if mid in seen:
            return
        seen.add(mid)
        if len(seen) > 8000:
            seen.clear()
            seen.add(mid)

        peer_uid = locked_peer or str(peer.get("uid") or meta.get("peer_uid") or "")
        peer_name = str(peer.get("name") or "")
        peer_avatar = str(peer.get("avatar") or "")
        # 新会话常只有 uid：尽量用消息里的 sec_sender 立刻补昵称/头像
        if (
            not view.get("mine")
            and (
                not peer_name
                or _is_uidish_name(peer_name, peer_uid)
                or not peer_avatar
            )
        ):
            try:
                msgs = [raw_message] if raw_message else None
                resolved = self._resolve_peer_row(conversation_id, msgs, persist=True)
                if resolved.get("name") and not _is_uidish_name(
                    str(resolved.get("name") or ""),
                    str(resolved.get("uid") or peer_uid),
                ):
                    peer_name = str(resolved.get("name") or peer_name)
                if resolved.get("avatar"):
                    peer_avatar = str(resolved.get("avatar") or peer_avatar)
                if resolved.get("uid"):
                    peer_uid = str(resolved.get("uid") or peer_uid)
                peer = {
                    **peer,
                    "uid": peer_uid,
                    "name": peer_name or peer.get("name") or "",
                    "avatar": peer_avatar or peer.get("avatar") or "",
                    "job": str(resolved.get("job") or peer.get("job") or ""),
                }
                if peer_name and not _is_uidish_name(peer_name, peer_uid):
                    self._broadcast_peer_update(conversation_id, {
                        "uid": peer_uid,
                        "name": peer_name,
                        "avatar": peer_avatar,
                        "job": str(peer.get("job") or ""),
                    })
            except Exception:
                logger.debug("live peer resolve failed for %s", conversation_id, exc_info=True)

        display_name = peer_name
        if not view.get("mine"):
            if _is_uidish_name(display_name, peer_uid):
                display_name = str(view.get("name") or "")
            if _is_uidish_name(display_name, peer_uid):
                display_name = str(peer.get("job") or "")  # unique_id fallback
            # Keep a visible label even when profile API only returned avatar.
            if _is_uidish_name(display_name, peer_uid) or not display_name:
                display_name = str(peer.get("job") or peer_uid or "新会话")
            scrubbed = self._scrub_self_from_peer(
                {
                    "uid": peer_uid,
                    "name": display_name,
                    "avatar": peer_avatar,
                    "job": str(peer.get("job") or ""),
                },
                peer_uid=peer_uid,
            )
            peer_uid = str(scrubbed.get("uid") or peer_uid)
            display_name = str(scrubbed.get("name") or display_name)
            peer_avatar = str(scrubbed.get("avatar") or "")
            peer = {**peer, **scrubbed}
            if display_name and (
                not peer_name
                or _is_uidish_name(peer_name, peer_uid)
            ):
                # Push nickname into UI even if it is unique_id / temporary label.
                self._broadcast_peer_update(
                    conversation_id,
                    {
                        "uid": peer_uid,
                        "name": display_name,
                        "avatar": peer_avatar,
                        "job": str(peer.get("job") or ""),
                    },
                )

        event = live_message(
            conversation_id=conversation_id,
            peer_uid=peer_uid,
            text=str(view.get("text") or ""),
            mine=bool(view.get("mine")),
            name=display_name if not view.get("mine") else "",
            from_uid=str(view.get("fromUid") or ""),
            avatar=(
                str(view.get("avatar") or peer_avatar or "")
                if not view.get("mine")
                else str(self._me.get("avatar") or view.get("avatar") or "")
            ),
            mid=mid,
            ts=int(view.get("ts") or 0),
            kind=str(view.get("kind") or "text"),
            image=view.get("image"),
            audio=view.get("audio"),
            file=view.get("file"),
        )
        if view.get("mine") and event.get("avatar"):
            self._remember_my_avatar(str(event.get("avatar") or ""))
        self._upsert_conversation_cache(
            conversation_id,
            event,
            peer={
                "uid": peer_uid,
                "name": display_name or peer_name,
                "avatar": peer_avatar,
                "job": str(peer.get("job") or ""),
            },
        )
        self._append_thread_cache_view(
            conversation_id,
            view,
            peer={
                "uid": peer_uid,
                "name": display_name or peer_name,
                "avatar": peer_avatar,
                "job": str(peer.get("job") or ""),
            },
        )
        # Always push full message events (list + open chat). History flood is prevented by priming.
        self._broadcast(event)
        if self._auto_reply and not view.get("mine"):
            self._schedule_auto_reply(conversation_id, view, raw_message=raw_message)

    def _message_age_ms(self, view: dict[str, Any], raw_message: dict[str, Any] | None) -> int:
        """Best-effort age of inbound message in milliseconds (0 if unknown)."""
        raw = raw_message or {}
        for key in ("create_time_ms", "create_time", "ts"):
            try:
                val = int(raw.get(key) or 0)
            except (TypeError, ValueError):
                val = 0
            if val <= 0:
                continue
            return int(time.time() * 1000) - (val if val > 10_000_000_000 else val * 1000)
        try:
            ts = int(view.get("ts") or 0)
        except (TypeError, ValueError):
            ts = 0
        if ts <= 0:
            return 0
        return int(time.time() * 1000) - (ts if ts > 10_000_000_000 else ts * 1000)

    def _schedule_auto_reply(
        self,
        conversation_id: str,
        view: dict[str, Any],
        *,
        raw_message: dict[str, Any] | None = None,
    ) -> None:
        """Peer message → greeting once, then contact once; no further auto-replies."""
        cid = str(conversation_id or "").strip()
        mid = str(view.get("mid") or "").strip()
        if not cid or not mid:
            return
        raw = raw_message or {}
        try:
            mt = int(raw.get("message_type") or 0)
        except (TypeError, ValueError):
            mt = 0
        # Skip read receipts / system noise.
        if mt in {50001, 50002}:
            return
        age_ms = self._message_age_ms(view, raw)
        # Avoid blasting history after restart / catchup (keep ~2 minutes live window).
        if age_ms > 120_000:
            return
        with self._lock:
            prev_state = self._auto_reply_conv_state.get(cid, "")
            if prev_state == "done":
                return
            if mid in self._auto_reply_mids or mid in self._auto_reply_busy:
                return
            if cid in self._auto_reply_conv_busy:
                return
            reply_text = auto_reply_for_conversation_state(prev_state)
            if not reply_text:
                return
            if len(self._auto_reply_mids) > 4000:
                self._auto_reply_mids.clear()
            self._auto_reply_busy.add(mid)
            self._auto_reply_mids.add(mid)
            self._auto_reply_conv_busy.add(cid)
            next_state = "done" if prev_state == "greeted" else "greeted"
            self._auto_reply_conv_state[cid] = next_state
            state_snapshot = dict(self._auto_reply_conv_state)
        _save_auto_reply_conv_state(state_snapshot, self._my_uid or self._credential_uid)
        threading.Thread(
            target=self._run_auto_reply,
            args=(cid, mid, reply_text, prev_state),
            name=f"douyin-auto-reply-{mid[:12]}",
            daemon=True,
        ).start()

    def _run_auto_reply(
        self,
        conversation_id: str,
        mid: str,
        text: str,
        prev_state: str = "",
    ) -> None:
        cid = str(conversation_id or "").strip()
        try:
            if self._stop.is_set():
                return
            delay_s = random.uniform(5.0, 8.0)
            logger.info(
                "auto-reply wait %.1fs cid=%s mid=%s prev=%r text=%r",
                delay_s,
                cid,
                mid,
                prev_state,
                (text or "")[:40],
            )
            if self._stop.wait(delay_s):
                return
            result = self.api_send(cid, text)
            ok = bool(result.get("ok"))
            err = ""
            if not ok:
                err = str((result.get("error") or {}).get("message") or result)
                with self._lock:
                    if prev_state:
                        self._auto_reply_conv_state[cid] = prev_state
                    else:
                        self._auto_reply_conv_state.pop(cid, None)
                    state_snapshot = dict(self._auto_reply_conv_state)
                _save_auto_reply_conv_state(state_snapshot, self._my_uid or self._credential_uid)
            logger.info(
                "auto-reply ok=%s cid=%s %s",
                ok,
                cid,
                (text[:50] + ("…" if len(text) > 50 else ""))
                + (f" err={err[:80]}" if err else ""),
            )
        except Exception:
            logger.warning("auto-reply failed cid=%s mid=%s", cid, mid, exc_info=True)
            with self._lock:
                if prev_state:
                    self._auto_reply_conv_state[cid] = prev_state
                else:
                    self._auto_reply_conv_state.pop(cid, None)
                state_snapshot = dict(self._auto_reply_conv_state)
            _save_auto_reply_conv_state(state_snapshot, self._my_uid or self._credential_uid)
        finally:
            with self._lock:
                self._auto_reply_busy.discard(mid)
                self._auto_reply_conv_busy.discard(cid)

    def _upsert_conversation_cache(
        self,
        conversation_id: str,
        event: dict[str, Any],
        *,
        peer: dict[str, Any] | None = None,
    ) -> None:
        cid = str(conversation_id or "")
        if not cid or not _is_conversation_id(cid):
            return
        peer = peer or {}
        # Sidebar cache must only contain real conversation ids (never bare uids).
        with self._lock:
            rows = [
                r
                for r in list(self._conversations_cache)
                if _is_conversation_id(str(r.get("friendId") or ""))
            ]
        found = False
        try:
            event_ts = int(event.get("ts") or 0)
        except (TypeError, ValueError):
            event_ts = 0
        if event_ts and event_ts < 10_000_000_000:
            event_ts *= 1000
        for row in rows:
            if str(row.get("friendId") or "") != cid:
                continue
            found = True
            incoming_ts = event_ts or int(row.get("lastTs") or 0)
            current_ts = int(row.get("lastTs") or 0)
            incoming_text = str(event.get("text") or "")
            if incoming_text and (not current_ts or incoming_ts >= current_ts):
                row["lastMessage"] = incoming_text
                row["lastTime"] = str(event.get("time") or row.get("lastTime") or "")
                if incoming_ts:
                    row["lastTs"] = incoming_ts
            if not event.get("mine"):
                row["unread"] = int(row.get("unread") or 0) + 1
            name = str(peer.get("name") or event.get("name") or "")
            uid = str(peer.get("uid") or event.get("uid") or row.get("uid") or "")
            if name and not _is_uidish_name(name, uid):
                row["name"] = name
            av = str(peer.get("avatar") or event.get("avatar") or "")
            if av:
                row["avatar"] = av
            if uid:
                row["uid"] = self._locked_peer_uid(cid) or uid
            job = str(peer.get("job") or "")
            if job:
                row["job"] = job
            break
        if not found:
            name = str(peer.get("name") or event.get("name") or "")
            uid = str(peer.get("uid") or event.get("uid") or "")
            if _is_uidish_name(name, uid):
                name = str(peer.get("job") or uid or "新会话")
            rows.insert(
                0,
                conversation_item(
                    index=1,
                    conversation_id=cid,
                    conversation_short_id=int(self._meta(cid).get("conversation_short_id") or 0),
                    peer_uid=uid,
                    peer_unique_id=str(peer.get("job") or ""),
                    name=name or "新会话",
                    avatar=str(peer.get("avatar") or event.get("avatar") or ""),
                    last_text=str(event.get("text") or ""),
                    last_time=str(event.get("time") or ""),
                    last_ts=event_ts or int(time.time() * 1000),
                ),
            )
            rows[0].pop("_meta", None)
            rows[0]["unread"] = 0 if event.get("mine") else 1
        rows = self._sort_conversations_by_recent(rows)
        with self._lock:
            self._conversations_cache = rows
            if not self._conversations_cache_at:
                self._conversations_cache_at = time.time()

    def _patch_conversation_cache(self, conversation_id: str, event: dict[str, Any]) -> None:
        self._upsert_conversation_cache(conversation_id, event)

    def _merge_local_conversations(self, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Keep WS-discovered sessions that Douyin list API has not returned yet."""
        seen = {str(it.get("friendId") or "") for it in items}
        with self._lock:
            cached = list(self._conversations_cache)
            meta_ids = [
                cid
                for cid, meta in self._conv_meta.items()
                if cid and cid not in seen
            ]
        extras: list[dict[str, Any]] = []
        for row in cached:
            cid = str(row.get("friendId") or "")
            if not _is_conversation_id(cid) or cid in seen:
                continue
            extras.append(dict(row))
            seen.add(cid)
        for cid in meta_ids:
            if not _is_conversation_id(cid) or cid in seen:
                continue
            meta = self._meta(cid)
            peer = self._peer(cid)
            peer_uid = str(peer.get("uid") or meta.get("peer_uid") or "")
            name = str(peer.get("name") or "")
            if _is_uidish_name(name, peer_uid):
                name = str(peer.get("job") or peer_uid or "新会话")
            extras.append(
                {
                    k: v
                    for k, v in conversation_item(
                        index=1,
                        conversation_id=cid,
                        conversation_short_id=int(meta.get("conversation_short_id") or 0),
                        peer_uid=peer_uid,
                        peer_unique_id=str(peer.get("job") or meta.get("peer_unique_id") or ""),
                        name=name or "新会话",
                        avatar=str(peer.get("avatar") or ""),
                    ).items()
                    if k != "_meta"
                }
            )
            seen.add(cid)
        if not extras:
            return items
        return extras + items

    def _active_poll_loop(self) -> None:
        while not self._stop.is_set():
            if self._stop.wait(ACTIVE_POLL_INTERVAL_S):
                break
            with self._lock:
                cid = str(self._active_conv or "")
            if not cid:
                continue
            try:
                self._poll_active_conversation(cid)
            except Exception:
                logger.debug("active poll failed for %s", cid, exc_info=True)

    def _inbox_poll_loop(self) -> None:
        cursor = 0
        ticks = 0
        while not self._stop.is_set():
            if self._stop.wait(INBOX_POLL_INTERVAL_S):
                break
            ticks += 1
            if ticks % max(1, INBOX_LIST_EVERY) == 0:
                self._refresh_inbox_async(announce_new=True)
            with self._lock:
                active = str(self._active_conv or "")
                order = list(self._inbox_order) or list(self._conv_meta.keys())
            if not order:
                continue
            targets: list[str] = []
            n = len(order)
            for _ in range(n):
                cid = str(order[cursor % n] or "")
                cursor += 1
                if not cid or cid == active:
                    continue
                meta = self._meta(cid)
                if int(meta.get("conversation_short_id") or 0):
                    targets.append(cid)
                if len(targets) >= INBOX_POLL_LIMIT:
                    break
            for cid in targets:
                if self._stop.is_set():
                    break
                if not self._imapi_lock.acquire(blocking=False):
                    break
                self._imapi_lock.release()
                try:
                    self._poll_active_conversation(cid)
                except Exception:
                    logger.debug("inbox poll failed for %s", cid, exc_info=True)

    def _prime_seen_from_raw(
        self,
        conversation_id: str,
        raw: list[dict[str, Any]],
        *,
        keep_recent_ms: int = 0,
    ) -> bool:
        """Mark history as seen without emitting. Returns True if this was first prime.

        When keep_recent_ms > 0, messages newer than that window stay unseen so they can be emitted
        (used for brand-new conversations).
        """
        cid = str(conversation_id or "")
        if not cid:
            return False
        seen = self._seen.setdefault(cid, set())
        if seen:
            return False
        cutoff = 0
        if keep_recent_ms > 0:
            cutoff = int(time.time() * 1000) - int(keep_recent_ms)
        for msg in raw:
            mid = str(msg.get("server_message_id") or msg.get("index_in_conversation") or "")
            if not mid:
                continue
            if cutoff:
                ts = int(msg.get("create_time_ms") or 0)
                if ts and ts >= cutoff:
                    continue
            seen.add(mid)
        return True

    def _poll_active_conversation(
        self,
        conversation_id: str,
        *,
        allow_recent_catchup: bool = False,
    ) -> None:
        conversation_id = str(conversation_id or "")
        meta = self._ensure_conv_meta(conversation_id)
        cshort = int(meta.get("conversation_short_id") or 0)
        if not cshort:
            return
        if not self._my_uid:
            self._refresh_me()
        peer = self._peer(conversation_id)
        peer_name = str(peer.get("name") or meta.get("peer_uid") or self._peer_uid_for(conversation_id) or "")
        peer_avatar = str(peer.get("avatar") or "")
        with self._imapi_lock:
            raw = get_messages_by_conversation(
                self._auth,
                conversation_id,
                cshort,
                limit=ACTIVE_POLL_MSG_LIMIT,
                anchor_index=0,
            )
        if not self._messages_belong_to_conversation(conversation_id, raw):
            logger.warning("active poll peer mismatch for %s cshort=%s", conversation_id, cshort)
            self._clear_poisoned_conversation(conversation_id)
            return
        if not self._seen.get(conversation_id):
            if allow_recent_catchup:
                self._prime_seen_from_raw(
                    conversation_id,
                    raw,
                    keep_recent_ms=RECENT_CATCHUP_MS,
                )
                # If nothing fell in the recent window, still surface the newest message once.
                ordered = sort_messages(raw)
                seen = self._seen.setdefault(conversation_id, set())
                if ordered and all(
                    str(m.get("server_message_id") or m.get("index_in_conversation") or "") in seen
                    for m in ordered
                    if str(m.get("server_message_id") or m.get("index_in_conversation") or "")
                ):
                    newest_mid = str(
                        ordered[-1].get("server_message_id")
                        or ordered[-1].get("index_in_conversation")
                        or ""
                    )
                    if newest_mid:
                        seen.discard(newest_mid)
            else:
                self._prime_seen_from_raw(conversation_id, raw)
                return
        for msg in reversed(sort_messages(raw)):
            mid = str(msg.get("server_message_id") or msg.get("index_in_conversation") or "")
            if not mid:
                continue
            seen = self._seen.setdefault(conversation_id, set())
            if mid in seen:
                break
            view = history_message(
                self._auth,
                msg,
                my_uid=self._my_uid,
                peer_name=peer_name,
                peer_avatar=peer_avatar,
                my_name=str(self._me.get("name") or "我"),
                my_avatar=str(self._me.get("avatar") or ""),
                resolve_profiles=False,
            )
            if not view:
                seen.add(mid)
                continue
            self._emit_live_view(conversation_id, view, peer=peer, meta=meta, raw_message=msg)


def make_handler(app: DouyinWebApp):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt: str, *args) -> None:  # noqa: A003
            logger.debug("%s - " + fmt, self.address_string(), *args)

        def handle(self) -> None:
            try:
                super().handle()
            except Exception as exc:
                if not is_client_gone(exc):
                    raise

        def finish(self) -> None:
            try:
                super().finish()
            except Exception as exc:
                if not is_client_gone(exc):
                    raise

        def _send(self, status: int, content_type: str, body: bytes, extra: dict[str, str] | None = None) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            if extra:
                for key, value in extra.items():
                    self.send_header(key, value)
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def _read_json(self) -> dict[str, Any]:
            length = int(self.headers.get("Content-Length") or 0)
            if length <= 0:
                return {}
            if length > MAX_POST_BYTES:
                raise ValueError("body too large")
            raw = self.rfile.read(length)
            data = json.loads(raw.decode("utf-8"))
            if not isinstance(data, dict):
                raise ValueError("JSON object required")
            return data

        def do_HEAD(self) -> None:  # noqa: N802
            self.do_GET()

        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            path = unquote(parsed.path)
            query = parse_qs(parsed.query)

            if path in ("/", "/index.html"):
                self._send(200, "text/html; charset=utf-8", (STATIC_DIR / "index.html").read_bytes())
                return
            if path == "/app.css":
                self._send(200, "text/css; charset=utf-8", (STATIC_DIR / "app.css").read_bytes())
                return
            if path == "/app.js":
                self._send(200, "application/javascript; charset=utf-8", (STATIC_DIR / "app.js").read_bytes())
                return
            if path == "/favicon.ico":
                self._send(204, "image/x-icon", b"")
                return
            if path == "/api/events":
                self._sse()
                return
            if path == "/api/me":
                try:
                    self._send(*_json_bytes(app.api_me()))
                except Exception as exc:
                    self._send(*_json_bytes(
                        {"ok": False, "schema_version": "1", "data": None, "error": {"code": "api_error", "message": str(exc)}},
                        400,
                    ))
                return
            if path == "/api/conversations":
                offset = int((query.get("offset") or ["0"])[0] or 0)
                limit = int((query.get("limit") or ["60"])[0] or 60)
                scope = str((query.get("scope") or ["all"])[0] or "all")
                try:
                    self._send(*_json_bytes(app.api_conversations(offset, limit, scope=scope)))
                except Exception as exc:
                    logger.exception("conversations failed")
                    self._send(*_json_bytes(
                        {"ok": False, "schema_version": "1", "data": None, "error": {"code": "unknown_error", "message": str(exc)}},
                        500,
                    ))
                return
            if path.startswith("/api/conversations/") and path.endswith("/messages"):
                ident = unquote(path[len("/api/conversations/") : -len("/messages")])
                if not ident:
                    self._send(*_json_bytes(
                        {"ok": False, "schema_version": "1", "data": None, "error": {"code": "invalid_params", "message": "无效会话"}},
                        400,
                    ))
                    return
                count = int((query.get("count") or ["40"])[0] or 40)
                anchor = int((query.get("maxMsgId") or ["0"])[0] or 0)
                try:
                    self._send(*_json_bytes(app.api_messages(ident, count=count, anchor_index=anchor)))
                except Exception as exc:
                    self._send(*_json_bytes(
                        {"ok": False, "schema_version": "1", "data": None, "error": {"code": "api_error", "message": str(exc)}},
                        400,
                    ))
                return
            if path in ("/api/avatar", "/api/media"):
                url = query_param(parsed.query, "u")
                filename = query_param(parsed.query, "filename")
                skey = query_param(parsed.query, "skey")
                oid = query_param(parsed.query, "oid")
                mid = query_param(parsed.query, "mid")
                download = (query.get("dl") or ["0"])[0] == "1"
                fetched = app.fetch_media(url, filename=filename, skey=skey, oid=oid, mid=mid)
                if not fetched:
                    self._send(404, "text/plain; charset=utf-8", "文件无法打开".encode("utf-8"))
                    return
                data, content_type = fetched
                extra = {"Cache-Control": "private, max-age=3600"}
                is_pdf = content_type == "application/pdf"
                is_image = content_type.startswith("image/")
                is_audio = content_type.startswith("audio/")
                inline = (is_pdf or is_image or is_audio) and not download
                extra["Content-Disposition"] = content_disposition(
                    filename or ("file.pdf" if is_pdf else "file"),
                    inline=inline,
                )
                self._send(200, content_type, data, extra=extra)
                return
            self._send(404, "text/plain; charset=utf-8", b"not found")

        def do_POST(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            path = unquote(parsed.path)
            if path == "/api/active":
                try:
                    body = self._read_json()
                except (ValueError, json.JSONDecodeError) as exc:
                    self._send(*_json_bytes(
                        {"ok": False, "schema_version": "1", "data": None, "error": {"code": "invalid_params", "message": str(exc)}},
                        400,
                    ))
                    return
                self._send(*_json_bytes(app.api_set_active(str(body.get("conversationId") or ""))))
                return
            if path.startswith("/api/conversations/") and path.endswith("/messages"):
                ident = unquote(path[len("/api/conversations/") : -len("/messages")])
                if not ident:
                    self._send(*_json_bytes(
                        {"ok": False, "schema_version": "1", "data": None, "error": {"code": "invalid_params", "message": "无效会话"}},
                        400,
                    ))
                    return
                try:
                    body = self._read_json()
                except (ValueError, json.JSONDecodeError) as exc:
                    self._send(*_json_bytes(
                        {"ok": False, "schema_version": "1", "data": None, "error": {"code": "invalid_params", "message": str(exc)}},
                        400,
                    ))
                    return
                result = app.api_send(ident, str(body.get("text") or ""))
                status = 200 if result.get("ok") else 400
                self._send(*_json_bytes(result, status))
                return
            self._send(404, "text/plain; charset=utf-8", b"not found")

        def _sse(self) -> None:
            q = app.subscribe()
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.send_header("X-Accel-Buffering", "no")
            self.end_headers()
            try:
                while True:
                    try:
                        event = q.get(timeout=15)
                    except queue.Empty:
                        self.wfile.write(b": ping\n\n")
                        self.wfile.flush()
                        continue
                    payload = json.dumps(event, ensure_ascii=False)
                    self.wfile.write(f"data: {payload}\n\n".encode("utf-8"))
                    self.wfile.flush()
            except Exception as exc:
                if not is_client_gone(exc):
                    raise
            finally:
                self.close_connection = True
                app.unsubscribe(q)

    return Handler


def serve_douyin_web(
    credential: DouyinCredential,
    host: str,
    port: int,
    *,
    auto_reply: bool = True,
    auto_replies: list[str] | None = None,
) -> QuietHTTPServer:
    app = DouyinWebApp(
        credential,
        auto_reply=auto_reply,
        auto_replies=auto_replies,
    )
    handler = make_handler(app)
    server = QuietHTTPServer((host, port), handler)
    server.web_app = app  # type: ignore[attr-defined]
    return server
