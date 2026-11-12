"""Local HTTP + MQTT bridge for the recruiter chat UI."""

from __future__ import annotations

import errno
import json
import logging
import queue
import random
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote, unquote, urlparse

from ..auth import Credential
from ..constants import RECRUITER_AUTO_WECHAT_FILE
from ..client import BossClient
from ..exceptions import BossApiError
from ..mqtt_chat import IDENTITY_BOSS, BossMQTTChat
from .payload import (
    allowed_avatar_url,
    chronological,
    clean_boss_tags,
    conversation_item,
    guess_mime,
    history_message,
    live_message,
    mqtt_is_mine,
    public_me,
    query_param,
    safe_peer_name,
)

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).resolve().parent / "static"
MAX_POST_BYTES = 16_384
MEDIA_MAX_BYTES = 32_000_000
_CLIENT_GONE_ERRNO = {
    errno.ECONNRESET,
    errno.EPIPE,
    errno.ETIMEDOUT,
    errno.ECONNABORTED,
}


def is_client_gone(exc: BaseException | None) -> bool:
    """True when the browser closed the tab, refreshed, or dropped SSE."""
    if isinstance(exc, (ConnectionResetError, BrokenPipeError, ConnectionAbortedError, TimeoutError)):
        return True
    if isinstance(exc, OSError) and getattr(exc, "errno", None) in _CLIENT_GONE_ERRNO:
        return True
    return False



DEFAULT_AUTO_WECHAT_GREETING = "还在看工作吗？方便聊聊吗？"
DEFAULT_AUTO_WECHAT_TEXT = "我们通过平台交换下联系方式，方便后续沟通"

# BOSS 系统消息发送方 uid（如 1000 系统通知）不是真实候选人。
# 真实候选人 uid 均为 9 位以上大数；低于此阈值视为系统/无效会话，跳过自动加微信。
_SYSTEM_UID_THRESHOLD = 1_000_000


def _is_system_peer(uid: int | str | None) -> bool:
    try:
        return int(uid) < _SYSTEM_UID_THRESHOLD
    except (TypeError, ValueError):
        return True


def _read_auto_wechat_file() -> dict[str, Any]:
    path = RECRUITER_AUTO_WECHAT_FILE
    try:
        if not path.exists():
            return {}
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        logger.debug("load auto-wechat state failed", exc_info=True)
        return {}


def _normalize_conv(conv: dict) -> dict[str, str]:
    out: dict[str, str] = {}
    for cid, state in (conv or {}).items():
        key = str(cid or "").strip()
        val = str(state or "").strip()
        if key and val in {"greeted", "done", "skip"}:
            out[key] = val
    return out


def _load_auto_wechat_state(account_key: str = "") -> dict[str, str]:
    """读取某账号的自动加微信状态（按登录 userId 分桶）。

    不同账号互相隔离：新账号登录后从零开始，不会被旧账号的
    done/greeted 记录跳过。旧格式数据（无 accounts 字段）归属
    legacy 桶，仅 account_key="legacy" 时返回。
    """
    data = _read_auto_wechat_file()
    accounts = data.get("accounts")
    if isinstance(accounts, dict):
        bucket = accounts.get(account_key or "default")
        if isinstance(bucket, dict) and isinstance(bucket.get("conversations"), dict):
            return _normalize_conv(bucket["conversations"])
        return {}
    # 旧格式（无 accounts）→ 归属 legacy 桶
    if account_key == "legacy":
        conv = data.get("conversations")
        if isinstance(conv, dict):
            return _normalize_conv(conv)
        ids = data.get("done")
        return {str(x): "done" for x in (ids or []) if str(x).strip()}
    return {}


def _save_auto_wechat_state(state: dict[str, str], account_key: str = "") -> None:
    """保存某账号的自动加微信状态（按登录 userId 分桶）。"""
    data = _read_auto_wechat_file()
    accounts = data.get("accounts")
    if not isinstance(accounts, dict):
        # 迁移旧格式（无 accounts）到 legacy 桶，避免丢失
        accounts = {}
        legacy = _normalize_conv(data.get("conversations") or {})
        if not legacy and data.get("done"):
            legacy = {str(x): "done" for x in data["done"] if str(x).strip()}
        if legacy:
            accounts["legacy"] = {"conversations": legacy}
    accounts[account_key or "default"] = {"conversations": dict(sorted(state.items()))}
    data["accounts"] = accounts
    data.pop("conversations", None)
    data.pop("done", None)
    try:
        RECRUITER_AUTO_WECHAT_FILE.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8",
        )
    except Exception:
        logger.debug("save auto-wechat state failed", exc_info=True)


class RecruiterWebApp:
    def __init__(
        self,
        credential: Credential,
        *,
        start_mqtt: bool = True,
        auto_wechat: bool = True,
        auto_wechat_text: str = DEFAULT_AUTO_WECHAT_TEXT,
        auto_wechat_greeting: str = DEFAULT_AUTO_WECHAT_GREETING,
    ):
        self.credential = credential
        self._lock = threading.Lock()
        self._mqtt: BossMQTTChat | None = None
        self._subs: list[queue.Queue] = []
        self._stop = threading.Event()
        self._peers: dict[int, dict[str, Any]] = {}
        self._peer_fetching: set[int] = set()
        self._me: dict[str, Any] = {"uid": 0, "name": "我", "avatar": ""}
        self._my_encrypt_uid = ""
        self._mqtt_status = "connecting"
        self._mqtt_thread: threading.Thread | None = None
        self._auto_wechat = bool(auto_wechat)
        self._auto_wechat_greeting = (auto_wechat_greeting or DEFAULT_AUTO_WECHAT_GREETING).strip() or DEFAULT_AUTO_WECHAT_GREETING
        self._auto_wechat_text = (auto_wechat_text or DEFAULT_AUTO_WECHAT_TEXT).strip() or DEFAULT_AUTO_WECHAT_TEXT
        self._auto_wechat_account_key = ""
        self._auto_wechat_conv_state: dict[str, str] = {}
        self._auto_wechat_busy: set[str] = set()
        if start_mqtt:
            self._mqtt_thread = threading.Thread(target=self._mqtt_loop, name="boss-web-mqtt", daemon=True)
            self._mqtt_thread.start()

    def stop(self) -> None:
        self._stop.set()
        with self._lock:
            chat = self._mqtt
            self._mqtt = None
        if chat is not None:
            try:
                chat.__exit__(None, None, None)
            except Exception:
                logger.debug("MQTT close failed", exc_info=True)
        self._broadcast({"type": "status", "mqtt": "stopped"})

    def _with_client(self, action):
        with BossClient(self.credential) as client:
            return action(client)

    def _broadcast(self, event: dict[str, Any]) -> None:
        payload = dict(event)
        with self._lock:
            subs = list(self._subs)
        for q in subs:
            try:
                q.put_nowait(payload)
            except Exception:
                logger.debug("SSE queue put failed", exc_info=True)

    def subscribe(self) -> queue.Queue:
        q: queue.Queue = queue.Queue(maxsize=200)
        with self._lock:
            self._subs.append(q)
        q.put({"type": "status", "mqtt": self._mqtt_status, "me": self._me})
        return q

    def unsubscribe(self, q: queue.Queue) -> None:
        with self._lock:
            if q in self._subs:
                self._subs.remove(q)

    def _remember_peer(self, item: dict[str, Any]) -> None:
        uid = int(item.get("uid") or 0)
        friend_id = int(item.get("friendId") or uid or 0)
        if not uid and not friend_id:
            return
        rec = {
            "uid": uid or friend_id,
            "friendId": friend_id or uid,
            "name": item.get("name") or "",
            "avatar": item.get("avatar") or "",
            "encryptGeekId": item.get("encryptGeekId") or "",
            "job": item.get("job") or "",
        }
        with self._lock:
            prev: dict[str, Any] = {}
            if uid:
                prev.update(self._peers.get(uid) or {})
            if friend_id:
                prev.update(self._peers.get(friend_id) or {})
            for key in ("name", "avatar", "encryptGeekId", "job"):
                if not rec.get(key) and prev.get(key):
                    rec[key] = prev[key]
            if uid:
                self._peers[uid] = rec
            if friend_id and friend_id != uid:
                self._peers[friend_id] = rec

    def _peer(self, uid: int) -> dict[str, Any]:
        with self._lock:
            return dict(self._peers.get(int(uid or 0)) or {})

    def _hydrate_peer(self, peer_uid: int) -> dict[str, Any]:
        peer = self._peer(peer_uid)
        need_name = not peer.get("name") or str(peer.get("name") or "").isdigit()
        need_avatar = not peer.get("avatar")
        if need_name:
            try:
                from ..index_cache import find_recruiter_by_uid
                cached = find_recruiter_by_uid(peer_uid) or {}
            except Exception:
                cached = {}
            if cached.get("name"):
                self._remember_peer({
                    "uid": int(cached.get("uid") or peer_uid or 0),
                    "friendId": int(cached.get("friendId") or cached.get("uid") or peer_uid or 0),
                    "name": cached.get("name") or "",
                    "encryptGeekId": cached.get("encryptGeekId") or "",
                    "job": cached.get("job") or "",
                    "avatar": peer.get("avatar") or "",
                })
                peer = self._peer(peer_uid) or peer
                need_name = not peer.get("name") or str(peer.get("name") or "").isdigit()
        if peer_uid and (need_name or need_avatar):
            self._fetch_peer_later(peer_uid)
        return self._peer(peer_uid) or peer

    def _fetch_peer_later(self, peer_uid: int) -> None:
        peer_uid = int(peer_uid or 0)
        if not peer_uid:
            return
        if not (getattr(self.credential, "cookies", None) or {}):
            return
        with self._lock:
            if peer_uid in self._peer_fetching:
                return
            self._peer_fetching.add(peer_uid)

        def work() -> None:
            try:
                details = self._with_client(lambda c: c.get_boss_friend_details([peer_uid]))
                found = (details.get("friendList") or [None])[0] or {}
                if not found:
                    return
                item = conversation_item(found, index=0)
                self._remember_peer(item)
                self._broadcast({
                    "type": "peer",
                    "uid": item.get("uid"),
                    "friendId": item.get("friendId"),
                    "name": item.get("name") or "",
                    "avatar": item.get("avatar") or "",
                    "job": item.get("job") or "",
                })
            except Exception:
                logger.debug("peer hydrate failed", exc_info=True)
            finally:
                with self._lock:
                    self._peer_fetching.discard(peer_uid)

        threading.Thread(target=work, name="boss-web-peer", daemon=True).start()

    def api_me(self) -> dict[str, Any]:
        if self._me.get("uid"):
            return {"ok": True, "schema_version": "1", "data": {"me": self._me, "mqtt": self._mqtt_status}}
        info = self._with_client(lambda c: c.get_user_info())
        me = public_me(info)
        self._me = me
        self._my_encrypt_uid = str(info.get("encryptUserId") or self._my_encrypt_uid or "")
        return {"ok": True, "schema_version": "1", "data": {"me": me, "mqtt": self._mqtt_status}}

    def api_conversations(self, offset: int, limit: int) -> dict[str, Any]:
        offset = max(0, int(offset))
        limit = min(max(1, int(limit)), 100)

        def _load(c: BossClient) -> tuple[list[dict[str, Any]], int]:
            friend_data = c.get_boss_friend_list()
            friend_list = friend_data.get("result") or []
            total = len(friend_list)
            sliced = friend_list[offset : offset + limit]
            ids = [int(f["friendId"]) for f in sliced if f.get("friendId")]
            details = c.get_boss_friend_details(ids) if ids else {"friendList": []}
            detail_list = details.get("friendList") or []
            by_id: dict[int, dict[str, Any]] = {}
            for item in detail_list:
                fid = int(item.get("friendId") or item.get("uid") or 0)
                uid = int(item.get("uid") or fid or 0)
                if fid:
                    by_id[fid] = item
                if uid:
                    by_id[uid] = item
            last_msgs = c.get_boss_last_messages(ids) if ids else []
            msg_map: dict[int, dict[str, Any]] = {}
            if isinstance(last_msgs, list):
                for msg in last_msgs:
                    uid = int(msg.get("uid") or 0)
                    if uid:
                        msg_map[uid] = msg
            items = []
            for i, raw in enumerate(sliced, offset + 1):
                fid = int(raw.get("friendId") or raw.get("uid") or 0)
                merged = dict(raw)
                extra = by_id.get(fid) or {}
                merged.update({k: v for k, v in extra.items() if v not in (None, "")})
                uid = int(merged.get("uid") or fid or 0)
                last = msg_map.get(uid, {})
                last_text = ""
                last_time = ""
                info = last.get("lastMsgInfo") if isinstance(last, dict) else None
                if isinstance(info, dict):
                    last_text = str(info.get("showText") or info.get("text") or "")
                last_text = clean_boss_tags(last_text)
                last_time = str((last or {}).get("lastTime") or "")
                item = conversation_item(merged, index=i, last_text=last_text, last_time=last_time)
                self._remember_peer(item)
                public = {k: v for k, v in item.items() if k != "encryptGeekId"}
                items.append(public)
            return items, total

        items, total = self._with_client(_load)
        next_offset = offset + len(items)
        return {
            "ok": True,
            "schema_version": "1",
            "data": {
                "conversations": items,
                "total": total,
                "offset": offset,
                "limit": limit,
                "nextOffset": next_offset if next_offset < total else None,
            },
        }

    def api_messages(self, friend_id: int, *, count: int = 40, max_msg_id: int = 0) -> dict[str, Any]:
        friend_id = int(friend_id)
        count = min(max(int(count), 10), 80)
        max_msg_id = int(max_msg_id or 0)

        def _load(c: BossClient) -> dict[str, Any]:
            if not self._me.get("uid"):
                self._me = public_me(c.get_user_info())
            history = c.get_boss_chat_history(gid=friend_id, count=count, max_msg_id=max_msg_id)
            return history

        history = self._with_client(_load)
        my_uid = int(self._me.get("uid") or 0)
        peer = self._hydrate_peer(friend_id)
        peer_uid = int(peer.get("uid") or friend_id or 0)
        raw = history.get("messages") or []
        messages = chronological([
            history_message(m, my_uid=my_uid, peer_uid=peer_uid) for m in raw
        ])
        next_cursor = None
        mids = [m.get("mid") for m in messages if isinstance(m.get("mid"), int)]
        if history.get("hasMore") and mids:
            next_cursor = min(mids)
        return {
            "ok": True,
            "schema_version": "1",
            "data": {
                "friendId": friend_id,
                "peer": peer,
                "messages": messages,
                "hasMore": bool(history.get("hasMore")),
                "nextCursor": next_cursor,
            },
        }

    def api_send(self, friend_id: int, text: str) -> dict[str, Any]:
        text = (text or "").strip()
        if not text:
            return {"ok": False, "schema_version": "1", "data": None, "error": {"code": "invalid_params", "message": "消息内容不能为空"}}
        if len(text) > 2000:
            return {"ok": False, "schema_version": "1", "data": None, "error": {"code": "invalid_params", "message": "消息过长"}}
        friend_id = int(friend_id)
        peer = self._peer(friend_id)
        to_uid = int(peer.get("uid") or friend_id)
        to_enc = str(peer.get("encryptGeekId") or "")
        if not to_enc:
            def _fill(c: BossClient) -> dict[str, Any]:
                details = c.get_boss_friend_details([friend_id])
                found = (details.get("friendList") or [None])[0] or {}
                item = conversation_item(found, index=0)
                self._remember_peer(item)
                return item

            try:
                filled = self._with_client(_fill)
            except BossApiError as exc:
                return {"ok": False, "schema_version": "1", "data": None, "error": {"code": "api_error", "message": str(exc)}}
            to_uid = int(filled.get("uid") or friend_id)
            to_enc = str(filled.get("encryptGeekId") or "")
        if not to_enc:
            return {
                "ok": False,
                "schema_version": "1",
                "data": None,
                "error": {"code": "invalid_params", "message": "缺少对方加密 ID，消息无法投递到手机。请刷新会话列表后再试。"},
            }
        errors: list[str] = []
        sent = False
        with self._lock:
            chat = self._mqtt
        my_uid = int(self._me.get("uid") or 0)
        if chat is not None:
            try:
                if not my_uid or not self._my_encrypt_uid:
                    info = self._with_client(lambda c: c.get_user_info())
                    self._me = public_me(info)
                    self._my_encrypt_uid = str(info.get("encryptUserId") or "")
                    my_uid = int(self._me.get("uid") or 0)
                if not my_uid or not self._my_encrypt_uid:
                    raise RuntimeError("缺少当前用户 uid/encryptUserId")
                chat.send(
                    from_uid=my_uid,
                    from_encrypt_uid=self._my_encrypt_uid,
                    to_uid=to_uid,
                    to_encrypt_uid=to_enc,
                    text=text,
                )
                sent = True
            except Exception as exc:
                errors.append(str(exc))
                logger.warning("MQTT send via live connection failed: %s", exc)
        if not sent:
            try:
                self._with_client(
                    lambda c: c.send_boss_message(to_uid=to_uid, to_encrypt_uid=to_enc, text=text)
                )
                sent = True
            except BossApiError as exc:
                return {"ok": False, "schema_version": "1", "data": None, "error": {"code": "api_error", "message": str(exc)}}
            except Exception as exc:
                msg = str(exc)
                if errors:
                    msg = f"{errors[-1]}；{msg}"
                return {"ok": False, "schema_version": "1", "data": None, "error": {"code": "api_error", "message": msg}}
        event = live_message(
            uid=to_uid,
            friend_id=friend_id,
            text=text,
            mine=True,
            name=peer.get("name") or "",
            avatar=str(peer.get("avatar") or ""),
            from_uid=my_uid,
        )
        self._broadcast(event)
        return {"ok": True, "schema_version": "1", "data": event}

    def fetch_avatar(self, url: str) -> tuple[bytes, str] | None:
        return self.fetch_media(url)

    def fetch_media(self, url: str, *, filename: str = "") -> tuple[bytes, str] | None:
        safe = allowed_avatar_url(url)
        if not safe:
            return None
        try:
            import httpx
        except ImportError:
            return None
        try:
            cookies = dict(getattr(self.credential, "cookies", None) or {})
            with httpx.Client(timeout=30.0, follow_redirects=True, cookies=cookies) as client:
                resp = client.get(
                    safe,
                    headers={
                        "Referer": "https://www.zhipin.com/",
                        "User-Agent": (
                            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36"
                        ),
                    },
                )
            if resp.status_code >= 400:
                return None
            data = resp.content or b""
            if not data or len(data) > MEDIA_MAX_BYTES:
                return None
            hinted = (resp.headers.get("content-type") or "").split(";")[0].strip().lower()
            content_type = _sniff_media_type(data, url, filename, hinted)
            if not _allowed_media_type(content_type, url, filename):
                return None
            return data, content_type
        except Exception:
            logger.debug("media proxy failed", exc_info=True)
            return None

    def _mqtt_loop(self) -> None:
        reconnect_delay = 2.0
        while not self._stop.is_set():
            try:
                page_token, wt2, user_info, cookies = self._with_client(
                    lambda c: (*c.get_ws_auth(), c.session_cookies()),
                )
                self._me = public_me(user_info)
                self._my_encrypt_uid = str(user_info.get("encryptUserId") or self._my_encrypt_uid or "")
                my_uid = int(self._me.get("uid") or 0)
                self._activate_auto_wechat_account(my_uid)
                self._mqtt_status = "connecting"
                self._broadcast({"type": "status", "mqtt": self._mqtt_status, "me": self._me})
                with BossMQTTChat(
                    page_token, wt2, cookies=cookies, timeout=15.0, identity=IDENTITY_BOSS,
                ) as chat:
                    with self._lock:
                        self._mqtt = chat
                    if my_uid:
                        try:
                            chat.announce_online(my_uid)
                        except Exception:
                            logger.debug("presence failed", exc_info=True)
                    self._mqtt_status = "online"
                    self._broadcast({"type": "status", "mqtt": self._mqtt_status, "me": self._me})
                    reconnect_delay = 2.0
                    while not self._stop.is_set():
                        frame = chat.poll_protocol(timeout=0.5)
                        if frame:
                            self._handle_mqtt_frame(frame, my_uid)
                        if chat.dropped:
                            raise RuntimeError("MQTT 连接断开")
            except Exception as exc:
                self._mqtt_status = "reconnecting"
                with self._lock:
                    self._mqtt = None
                self._broadcast({"type": "status", "mqtt": self._mqtt_status, "detail": str(exc)})
                if self._stop.wait(reconnect_delay):
                    return
                reconnect_delay = min(30.0, reconnect_delay * 2)
        self._mqtt_status = "stopped"

    def _handle_mqtt_frame(self, frame: dict[str, Any], my_uid: int) -> None:
        if frame.get("type") != 1:
            return
        for msg in frame.get("messages") or []:
            from_obj = msg.get("from") or {}
            to_obj = msg.get("to") or {}
            from_uid = int(from_obj.get("uid") or 0)
            to_uid = int(to_obj.get("uid") or 0)
            mine = mqtt_is_mine(
                from_uid=from_uid,
                to_uid=to_uid,
                flag=int(msg.get("flag") or 0),
                my_uid=my_uid,
                from_name=str(from_obj.get("name") or ""),
                my_encrypt=self._my_encrypt_uid,
                my_name=str(self._me.get("name") or ""),
            )
            peer_uid = to_uid if mine else from_uid
            if my_uid and peer_uid == my_uid:
                peer_uid = from_uid if from_uid != my_uid else to_uid
            parsed = history_message(msg, my_uid=my_uid, peer_uid=peer_uid)
            peer = self._hydrate_peer(peer_uid)
            name = str(peer.get("name") or "")
            if not mine:
                incoming = safe_peer_name(
                    str(from_obj.get("name") or ""),
                    my_name=str(self._me.get("name") or ""),
                    my_encrypt=self._my_encrypt_uid,
                )
                if incoming and (not name or name.isdigit()):
                    name = incoming
                    self._remember_peer({
                        **peer,
                        "uid": peer_uid,
                        "friendId": peer.get("friendId") or peer_uid,
                        "name": name,
                    })
            friend_id = int(peer.get("friendId") or peer_uid)
            event = live_message(
                uid=peer_uid,
                friend_id=friend_id,
                text=str(parsed.get("text") or ""),
                mine=mine,
                name=str(name or ""),
                avatar=str(peer.get("avatar") or ""),
                mid=parsed.get("mid") or msg.get("mid"),
                time_raw=msg.get("time"),
                from_uid=from_uid,
                kind=str(parsed.get("kind") or "text"),
                image=parsed.get("image"),
                resume=parsed.get("resume"),
                file=parsed.get("file"),
                audio=parsed.get("audio"),
            )
            self._broadcast(event)
            if self._auto_wechat and not mine and peer_uid:
                self._schedule_auto_wechat(friend_id=friend_id, peer_uid=peer_uid)



    def _activate_auto_wechat_account(self, uid: int) -> None:
        """登录账号确定后，把自动加微信状态切换到该账号的桶（多账号隔离）。

        不同登录账号各自独立记录 greeted/done，新账号从零开始。
        """
        key = str(int(uid or 0))
        if not key:
            return
        with self._lock:
            if key != self._auto_wechat_account_key:
                self._auto_wechat_account_key = key
                self._auto_wechat_conv_state = _load_auto_wechat_state(key)

    def _schedule_auto_wechat(self, *, friend_id: int, peer_uid: int) -> None:
        """对方新消息：问候 → 换联系方式+交换微信，每会话只走一遍。

        系统消息（friendId=1000 等）或已失败(skip)/已完成(done)的会话不触发。
        """
        key = str(int(friend_id or peer_uid or 0))
        if not self._auto_wechat or key in {"", "0"}:
            return
        if _is_system_peer(friend_id or peer_uid):
            logger.info("auto-wechat skip system peer friendId=%s", friend_id)
            return
        with self._lock:
            prev_state = self._auto_wechat_conv_state.get(key, "")
            if prev_state in {"done", "skip"}:
                return
            if key in self._auto_wechat_busy:
                return
            if prev_state == "greeted":
                step = "contact"
                next_state = "done"
            else:
                step = "greeting"
                next_state = "greeted"
            self._auto_wechat_busy.add(key)
            self._auto_wechat_conv_state[key] = next_state
            state_snapshot = dict(self._auto_wechat_conv_state)
        _save_auto_wechat_state(state_snapshot, self._auto_wechat_account_key)
        threading.Thread(
            target=self._run_auto_wechat,
            args=(int(friend_id or peer_uid), int(peer_uid or friend_id), key, step, prev_state),
            name=f"boss-auto-wechat-{key}",
            daemon=True,
        ).start()

    def _mark_auto_wechat_failed(self, key: str) -> None:
        """发送失败（系统消息/无效会话/接口异常）→ 标记 skip，不再反复重试。"""
        with self._lock:
            self._auto_wechat_conv_state[key] = "skip"
            state_snapshot = dict(self._auto_wechat_conv_state)
        _save_auto_wechat_state(state_snapshot, self._auto_wechat_account_key)

    def _revert_auto_wechat_state(self, key: str, prev_state: str) -> None:
        with self._lock:
            if prev_state:
                self._auto_wechat_conv_state[key] = prev_state
            else:
                self._auto_wechat_conv_state.pop(key, None)
            state_snapshot = dict(self._auto_wechat_conv_state)
        _save_auto_wechat_state(state_snapshot, self._auto_wechat_account_key)

    def _run_auto_wechat(
        self,
        friend_id: int,
        peer_uid: int,
        key: str,
        step: str,
        prev_state: str = "",
    ) -> None:
        try:
            if self._stop.is_set():
                return
            delay_s = random.uniform(5.0, 8.0)
            logger.info(
                "auto-wechat wait %.1fs step=%s friendId=%s",
                delay_s,
                step,
                friend_id,
            )
            if self._stop.wait(delay_s):
                self._revert_auto_wechat_state(key, prev_state)
                return

            if step == "greeting":
                text = self._auto_wechat_greeting
                logger.info("auto-wechat greeting friendId=%s text=%r", friend_id, text[:40])
                send_result = self.api_send(friend_id, text)
                if not send_result.get("ok"):
                    err = (send_result.get("error") or {}).get("message") or send_result
                    logger.warning("auto-wechat greeting failed friendId=%s: %s", friend_id, err)
                    self._mark_auto_wechat_failed(key)
                else:
                    logger.info("auto-wechat greeting sent friendId=%s", friend_id)
                return

            text = self._auto_wechat_text
            logger.info("auto-wechat contact friendId=%s text=%r", friend_id, text[:40])
            send_result = self.api_send(friend_id, text)
            if not send_result.get("ok"):
                err = (send_result.get("error") or {}).get("message") or send_result
                logger.warning("auto-wechat contact text failed friendId=%s: %s", friend_id, err)
                self._mark_auto_wechat_failed(key)
                return
            logger.info("auto-wechat contact text sent friendId=%s", friend_id)

            if self._stop.is_set():
                return

            def _exchange(c: BossClient) -> dict[str, Any]:
                details = c.get_boss_friend_details([friend_id])
                friend_list = details.get("friendList") or []
                friend = friend_list[0] if friend_list else {}
                uid = int(friend.get("uid") or peer_uid or friend_id)
                friend_source = int(friend.get("friendSource") or 0)
                security_id = str(friend.get("securityId") or "")
                name = str(friend.get("name") or "")
                if not security_id:
                    raise RuntimeError(f"缺少 securityId (friendId={friend_id})")
                unique_id = f"{uid}-{friend_source}"
                return c.boss_exchange_request(
                    security_id=security_id,
                    unique_id=unique_id,
                    exchange_type=2,
                    name=name,
                )

            try:
                self._with_client(_exchange)
                logger.info("auto-wechat exchange requested friendId=%s", friend_id)
            except Exception as exc:
                logger.warning("auto-wechat exchange failed friendId=%s: %s", friend_id, exc)
        except Exception:
            logger.warning("auto-wechat failed friendId=%s step=%s", friend_id, step, exc_info=True)
            self._mark_auto_wechat_failed(key)
        finally:
            with self._lock:
                self._auto_wechat_busy.discard(key)



def _sniff_media_type(data: bytes, url: str, filename: str, hinted: str) -> str:
    if data[:4] == b"%PDF":
        return "application/pdf"
    if data[:3] == b"ID3" or data[:2] in (b"\xff\xfb", b"\xff\xf3"):
        return "audio/mpeg"
    if data[:4] == b"RIFF" and data[8:12] == b"WAVE":
        return "audio/wav"
    if data[:2] == b"PK":
        guessed = guess_mime(filename, url, "")
        if guessed:
            return guessed
        return "application/zip"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    guessed = guess_mime(filename, url, hinted)
    return guessed or hinted or "application/octet-stream"


def _allowed_media_type(content_type: str, url: str, filename: str) -> bool:
    ctype = (content_type or "").lower()
    if ctype.startswith(("image/", "audio/", "video/")):
        return True
    if ctype in {
        "application/pdf",
        "application/msword",
        "application/vnd.ms-excel",
        "application/vnd.ms-powerpoint",
        "application/zip",
        "application/octet-stream",
        "text/plain",
    }:
        return True
    if ctype.startswith("application/vnd.openxmlformats-officedocument"):
        return True
    blob = f"{filename} {url}".lower().split("?")[0]
    return any(blob.endswith(ext) for ext in (
        ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
        ".zip", ".txt", ".mp3", ".m4a", ".amr", ".wav", ".png", ".jpg", ".jpeg", ".gif", ".webp",
    ))


def content_disposition(filename: str, *, inline: bool) -> str:
    name = Path(filename or "file").name.replace('"', "").replace("\n", "")
    if not name:
        name = "file"
    kind = "inline" if inline else "attachment"
    ascii_name = name.encode("ascii", "replace").decode("ascii").replace("?", "_")
    return f"{kind}; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(name)}"


def _json_bytes(payload: dict[str, Any], status: int = 200) -> tuple[int, str, bytes]:
    return status, "application/json; charset=utf-8", json.dumps(payload, ensure_ascii=False).encode("utf-8")


def make_handler(app: RecruiterWebApp):
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
                html = (STATIC_DIR / "index.html").read_bytes()
                self._send(200, "text/html; charset=utf-8", html)
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
                except BossApiError as exc:
                    self._send(*_json_bytes(
                        {"ok": False, "schema_version": "1", "data": None, "error": {"code": "api_error", "message": str(exc)}},
                        400,
                    ))
                return
            if path == "/api/conversations":
                offset = int((query.get("offset") or ["0"])[0] or 0)
                limit = int((query.get("limit") or ["60"])[0] or 60)
                try:
                    self._send(*_json_bytes(app.api_conversations(offset, limit)))
                except BossApiError as exc:
                    self._send(*_json_bytes(
                        {"ok": False, "schema_version": "1", "data": None, "error": {"code": "api_error", "message": str(exc)}},
                        400,
                    ))
                except Exception as exc:
                    logger.exception("conversations failed")
                    self._send(*_json_bytes(
                        {"ok": False, "schema_version": "1", "data": None, "error": {"code": "unknown_error", "message": str(exc)}},
                        500,
                    ))
                return
            if path.startswith("/api/conversations/") and path.endswith("/messages"):
                ident = path[len("/api/conversations/") : -len("/messages")]
                if not ident.isdigit():
                    self._send(*_json_bytes(
                        {"ok": False, "schema_version": "1", "data": None, "error": {"code": "invalid_params", "message": "无效会话"}},
                        400,
                    ))
                    return
                count = int((query.get("count") or ["40"])[0] or 40)
                max_msg_id = int((query.get("maxMsgId") or ["0"])[0] or 0)
                try:
                    self._send(*_json_bytes(app.api_messages(int(ident), count=count, max_msg_id=max_msg_id)))
                except BossApiError as exc:
                    self._send(*_json_bytes(
                        {"ok": False, "schema_version": "1", "data": None, "error": {"code": "api_error", "message": str(exc)}},
                        400,
                    ))
                return
            if path in ("/api/avatar", "/api/media"):
                url = query_param(parsed.query, "u")
                filename = query_param(parsed.query, "filename")
                download = (query.get("dl") or ["0"])[0] == "1"
                fetched = app.fetch_media(url, filename=filename)
                if not fetched:
                    self._send(404, "text/plain; charset=utf-8", "文件无法打开".encode("utf-8"))
                    return
                data, content_type = fetched
                extra = {"Cache-Control": "private, max-age=3600"}
                is_pdf = content_type == "application/pdf"
                is_image = content_type.startswith("image/")
                inline = (is_pdf or is_image) and not download
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
            if path.startswith("/api/conversations/") and path.endswith("/messages"):
                ident = path[len("/api/conversations/") : -len("/messages")]
                if not ident.isdigit():
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
                result = app.api_send(int(ident), str(body.get("text") or ""))
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
                        event = q.get(timeout=20)
                        line = f"data: {json.dumps(event, ensure_ascii=False)}\n\n".encode("utf-8")
                        self.wfile.write(line)
                        self.wfile.flush()
                    except queue.Empty:
                        self.wfile.write(b": ping\n\n")
                        self.wfile.flush()
            except Exception as exc:
                if not is_client_gone(exc):
                    raise
            finally:
                self.close_connection = True
                app.unsubscribe(q)

    return Handler


class QuietHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def handle_error(self, request, client_address) -> None:  # noqa: ARG002
        if is_client_gone(sys.exc_info()[1]):
            logger.debug("client disconnected %s", client_address)
            return
        super().handle_error(request, client_address)


def serve_recruiter_web(
    credential: Credential,
    host: str,
    port: int,
    *,
    auto_wechat: bool = True,
    auto_wechat_text: str = DEFAULT_AUTO_WECHAT_TEXT,
    auto_wechat_greeting: str = DEFAULT_AUTO_WECHAT_GREETING,
) -> ThreadingHTTPServer:
    app = RecruiterWebApp(
        credential,
        auto_wechat=auto_wechat,
        auto_wechat_text=auto_wechat_text,
        auto_wechat_greeting=auto_wechat_greeting,
    )
    handler = make_handler(app)
    server = QuietHTTPServer((host, port), handler)
    server.web_app = app  # type: ignore[attr-defined]
    return server
