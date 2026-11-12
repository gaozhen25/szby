"""Douyin IM real-time receive via frontier-im WebSocket (push, not HTTP poll).

Reference: DouYin_Spider/dy_apis/douyin_recv_msg.py and frontier-im framing.
"""

from __future__ import annotations

import asyncio
import gzip
import hashlib
import logging
import threading
from typing import Any, Callable

from .protocol import ImAuth, _decode_fields, _message_create_time_ms as _fallback_create_time_ms

logger = logging.getLogger(__name__)

_APP_KEY = "e1bd35ec9db7b8d846de66ed140b1ad9"
_FPID = "9"
_SALT = "f8a69f1719916z"
_WS_ORIGIN = "https://www.douyin.com"
_LIST_REFRESH_S = 30.0
_SKIP_MSG_TYPES = {50001, 50002}


def resolve_device_id(auth: ImAuth) -> str:
    """frontier-im 的 device_id：固定用账号 uid。

    实测浏览器扫码会话经常没有 tt_webid；用随机 webid 会触发 HTTP 400。
    用账号自身 uid 与官方 PC 私信 / DouYin_Spider 一致，且跨重启稳定。
    """
    uid = str(getattr(auth, "uid", "") or "").strip()
    if uid.isdigit() and len(uid) >= 10:
        return uid
    # 极端兜底：凭证里偶发带了数字 webid 时再用（正常路径不应走到这里）
    cookie = getattr(auth, "cookie", None) or {}
    for key in ("tt_webid", "tt_webid_v2", "webid", "web_id", "device_id"):
        val = str(cookie.get(key) or "").strip().strip('"')
        if val and val.isdigit() and len(val) >= 10:
            return val
    return ""


def compute_access_key(device_id: str) -> str:
    raw = f"{_FPID}{_APP_KEY}{device_id}{_SALT}"
    return hashlib.md5(raw.encode("utf-8")).hexdigest()


def build_ws_url(device_id: str, *, token: str = "") -> str:
    """Build frontier-im URL. DouYin_Spider includes session token for push delivery."""
    access_key = compute_access_key(device_id)
    query = f"aid=6383&device_platform=douyin_pc&fpid={_FPID}&device_id={device_id}"
    if token:
        query += f"&token={token}"
    query += f"&access_key={access_key}&version_code=360000&xsack=0&xaack=0&xsqos=0&qos_sdk_version=2"
    return f"wss://frontier-im.douyin.com/ws/v2?{query}"


def _first(fields: dict[int, list[Any]], key: int, default: Any = None) -> Any:
    vals = fields.get(key) or []
    return vals[0] if vals else default


def _as_str(value: Any) -> str:
    if isinstance(value, bytes):
        try:
            return value.decode("utf-8")
        except Exception:
            return ""
    if value is None:
        return ""
    return str(value)


def _safe_int(value: Any, default: int = 0) -> int:
    """安全地把 protobuf 字段值转成 int；bytes/str 非数字时返回 default。"""
    if value is None:
        return default
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, (bytes, bytearray)):
        try:
            text = bytes(value).decode("utf-8", "replace").strip()
        except Exception:
            return default
    else:
        text = str(value).strip()
    if not text:
        return default
    try:
        return int(text)
    except (TypeError, ValueError):
        try:
            return int(float(text))
        except (TypeError, ValueError):
            return default


def _ext_map(fields: dict[int, list[Any]]) -> dict[str, str]:
    out: dict[str, str] = {}
    for entry in fields.get(9, []):
        if not isinstance(entry, bytes):
            continue
        kv = _decode_fields(entry)
        key = _as_str(_first(kv, 1, b""))
        if key:
            out[key] = _as_str(_first(kv, 2, b""))
    return out


def _body_create_time_ms(fields: dict[int, list[Any]]) -> int:
    ext = _ext_map(fields)
    for key in ("s:server_message_create_time", "a:im_client_send_msg_time"):
        raw = ext.get(key)
        if not raw:
            continue
        try:
            return int(float(raw))
        except (TypeError, ValueError):
            continue
    return _fallback_create_time_ms(fields)


def _message_body_to_raw(body: bytes) -> dict[str, Any] | None:
    m = _decode_fields(body)
    conv_id = _as_str(_first(m, 1, b""))
    if not conv_id:
        return None

    content_val = _first(m, 8, b"")
    if isinstance(content_val, bytes):
        content = content_val.decode("utf-8", "replace")
    else:
        content = _as_str(content_val)

    msg_type = _safe_int(_first(m, 6, 0))
    if msg_type in _SKIP_MSG_TYPES:
        return None

    return {
        "conversation_id": conv_id,
        "conversation_type": _safe_int(_first(m, 2, 0)),
        "server_message_id": _as_str(_first(m, 3, b"")),
        "index_in_conversation": _as_str(_first(m, 4, b"")),
        # Field 5 is the in-conversation sort index, not conversation_short_id.
        # Writing it into the send cache makes the next private message fail.
        "message_type": msg_type,
        "sender": _as_str(_first(m, 7, b"")),
        "content": content,
        "sec_sender": _as_str(_first(m, 14, b"")),
        "create_time_ms": _body_create_time_ms(m),
    }


def _collect_message_bodies(blob: bytes, *, depth: int = 0) -> list[bytes]:
    """从推送帧 payload 中提取消息体 bytes。

    优先从标准路径 field 500(notify) → field 5(message) 提取；
    若标准路径无结果，再扫描顶层字段中符合消息体格式的 bytes。
    严格去重，避免递归遍历导致同一条消息被重复解析。
    """
    if depth > 2 or not blob:
        return []
    found: list[bytes] = []
    seen_ids: set[int] = set()

    def _add(val: bytes) -> None:
        if not isinstance(val, bytes) or len(val) < 12:
            return
        # 用 bytes 内容的 hash 去重，避免同一条消息被重复添加
        key = hash(val)
        if key in seen_ids:
            return
        # 验证是否是合法消息体（必须有 conversation_id field 1）
        try:
            parsed = _message_body_to_raw(val)
        except Exception:
            parsed = None
        if not parsed:
            return
        seen_ids.add(key)
        found.append(val)

    fields = _decode_fields(blob)

    # 标准路径：field 500(notify) → field 5(message)
    notify_raw = _first(fields, 500)
    if isinstance(notify_raw, bytes):
        try:
            notify = _decode_fields(notify_raw)
            message_raw = _first(notify, 5)
            if isinstance(message_raw, bytes):
                _add(message_raw)
        except Exception:
            logger.debug("collect: parse notify field 500 failed", exc_info=True)

    # 如果标准路径找到了，不再扫描其他字段（避免重复）
    if found:
        return found

    # 标准路径无结果时，扫描顶层字段中符合消息体格式的 bytes（不递归）
    for vals in fields.values():
        for val in vals:
            if isinstance(val, bytes):
                _add(val)

    return found


def decode_push_frame(raw: bytes) -> list[dict[str, Any]]:
    """PushFrame -> list of message dicts (same shape as get_messages_by_conversation)."""
    frame = _decode_fields(raw)
    payload_type = _as_str(_first(frame, 7, b""))
    payload_encoding = _as_str(_first(frame, 6, b""))
    payload = _first(frame, 8, b"")
    if not isinstance(payload, bytes) or not payload:
        return []
    if payload_encoding == "gzip" or payload[:2] == b"\x1f\x8b":
        try:
            payload = gzip.decompress(payload)
        except Exception:
            logger.debug("gzip decompress failed", exc_info=True)
    if payload_type and payload_type not in ("pb", ""):
        return []

    resp = _decode_fields(payload)
    body_raw = _first(resp, 6)
    if not isinstance(body_raw, bytes):
        return []

    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for message_raw in _collect_message_bodies(body_raw):
        parsed = _message_body_to_raw(message_raw)
        if not parsed:
            continue
        mid = str(parsed.get("server_message_id") or "")
        dedup = mid or str(hash(message_raw))
        if dedup in seen:
            continue
        seen.add(dedup)
        out.append(parsed)
    return out


async def _receive_loop(
    auth: ImAuth,
    *,
    device_id: str,
    cookie_str: str,
    on_message: Callable[[dict[str, Any]], None],
    stop: threading.Event,
    on_connected: Callable[[], None] | None = None,
    on_refresh_list: Callable[[], None] | None = None,
) -> None:
    import websockets

    token = str(auth.cookie.get("sessionid") or auth.token or "")
    url = build_ws_url(device_id, token=token)
    headers = {
        "Cookie": cookie_str,
        "User-Agent": auth.client.user_agent,
        "Origin": _WS_ORIGIN,
        "Sec-WebSocket-Protocol": "binary, base64, pbbp2",
    }
    last_refresh = asyncio.get_running_loop().time()
    logger.info(
        "douyin im ws connecting endpoint=frontier-im.douyin.com device_id=%s authenticated=%s",
        device_id,
        bool(token),
    )

    async with websockets.connect(
        url,
        additional_headers=headers,
        subprotocols=["binary", "base64", "pbbp2"],
        max_size=None,
        open_timeout=15,
        # Windows NAT / sleep can drop idle TCP; keep pings frequent and
        # tolerate a longer wait for pong before tearing the socket down.
        ping_interval=15,
        ping_timeout=120,
    ) as ws:
        logger.info("douyin im ws connected endpoint=frontier-im.douyin.com")
        if on_connected:
            on_connected()
        while not stop.is_set():
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=5.0)
            except asyncio.TimeoutError:
                now = asyncio.get_running_loop().time()
                if on_refresh_list and (now - last_refresh) >= _LIST_REFRESH_S:
                    try:
                        on_refresh_list()
                    except Exception:
                        logger.debug("inbox refresh during ws failed", exc_info=True)
                    last_refresh = now
                continue
            if isinstance(raw, (bytes, bytearray)):
                raw_bytes = bytes(raw)
                try:
                    msgs = decode_push_frame(raw_bytes)
                except Exception:
                    logger.warning(
                        "ws decode_push_frame failed for %d-byte frame, skipping",
                        len(raw_bytes),
                        exc_info=True,
                    )
                    msgs = []
                if not msgs:
                    logger.info(
                        "ws recv %d bytes, decoded 0 messages (frame may be ack/heartbeat or format changed)",
                        len(raw_bytes),
                    )
                else:
                    logger.info("ws recv %d bytes, decoded %d messages", len(raw_bytes), len(msgs))
                for msg in msgs:
                    try:
                        on_message(msg)
                    except Exception:
                        logger.debug("ws on_message handler failed", exc_info=True)
            else:
                logger.info("ws recv non-binary frame: %r", raw[:200] if raw else raw)


def run_im_ws_loop(
    auth: ImAuth,
    *,
    device_id: str,
    cookie_str: str,
    on_message: Callable[[dict[str, Any]], None],
    stop: threading.Event,
    on_connected: Callable[[], None] | None = None,
    on_disconnected: Callable[[str], None] | None = None,
    on_refresh_list: Callable[[], None] | None = None,
) -> None:
    """Blocking WS loop for a background thread; reconnect is handled by the caller."""

    async def _run_once() -> None:
        await _receive_loop(
            auth,
            device_id=device_id,
            cookie_str=cookie_str,
            on_message=on_message,
            stop=stop,
            on_connected=on_connected,
            on_refresh_list=on_refresh_list,
        )

    try:
        asyncio.run(_run_once())
    except Exception as exc:
        if on_disconnected:
            on_disconnected(str(exc))
        else:
            raise
