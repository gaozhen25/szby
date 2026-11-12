# -*- coding: utf-8 -*-
"""小红书私信 · 纯 WebSocket 直发（免浏览器、免 UI 自动化）。

逆向结论（2026-08 抓包 + 前端 JS 分析）：
- 私信发送主链路走 WebSocket 长连接 apppush-rws.xiaohongshu.com/rwp（IM 协议），
  消息体是「明文 protobuf」序列化后 base64，并非加密。
- 鉴权 sid 来自服务端接口 GET edith.xiaohongshu.com/api/sns/web/v1/celestial/lt
  （需 x-s/x-t 签名 + c_device_id 头），返回 data.a_lt 即 sid（有效期约 2.8h）。
- HTTP 回退端点 /api/im/web/short_link/send_message 的 message 字段才是 AES 加密，
  未实现，此处只实现 WS 主链路。

WS 帧协议：
  v=1, t=0 PING 心跳 {"v":1,"t":0}
  t=2 SIGNAL: {"v":1,"t":2,"m":msgId,"b":{"d":{"a":ackMode,"s":type,"b":payload}}}
      s=0 LOGIN / s=1 BIZ_REGISTER / ...
  t=3 DATA:   {"v":1,"t":3,"m":msgId,"b":{"d":{"a":2,"c":"sendMessage","biz":"im",
                "b":"<base64(protobuf)>","e":{},"s":"rrmp.b.i"}}}
"""
from __future__ import annotations

import base64
import datetime
import json
import logging
import ssl
import time
import uuid
from typing import Any, Dict, Iterator, Optional

import requests
import websocket

from .help import sign_headers
from .client import DEFAULT_UA
from boss_cli.constants import XHS_WS_DEVICE_FILE

logger = logging.getLogger("xhs.im_ws")

LT_HOST = "https://edith.xiaohongshu.com"
LT_URI = "/api/sns/web/v1/celestial/lt"
LONG_LINK_HOST = "wss://apppush-rws.xiaohongshu.com/rwp"

# 固定 device_id 持久化文件：让 WS 直发使用同一台"可信设备"身份
import os as _os

_DEVICE_ID_FILE = str(XHS_WS_DEVICE_FILE)


def get_device_id(uid: str = "") -> str:
    """按账号获取固定 device_id：首次生成后持久化复用；也兼容显式指定。"""
    store: Dict[str, str] = {}
    if _os.path.exists(_DEVICE_ID_FILE):
        try:
            with open(_DEVICE_ID_FILE) as f:
                store = json.load(f)
        except Exception:
            store = {}
    key = str(uid or "default")
    did = store.get(key) or store.get("default")
    if not did:
        did = str(uuid.uuid4())
        store[key] = did
        try:
            _os.makedirs(_os.path.dirname(_DEVICE_ID_FILE), exist_ok=True)
            with open(_DEVICE_ID_FILE, "w") as f:
                json.dump(store, f, ensure_ascii=False, indent=2)
        except Exception:
            pass
    return did


# ---------- protobuf 基础编码 ----------

def _varint(n: int) -> bytes:
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        if n:
            out.append(b | 0x80)
        else:
            out.append(b)
            return bytes(out)


def _proto_varint(field: int, value: int) -> bytes:
    return _varint((field << 3) | 0) + _varint(value)


def _proto_bytes(field: int, value: bytes) -> bytes:
    return _varint((field << 3) | 2) + _varint(len(value)) + value


def _proto_str(field: int, value: str) -> bytes:
    return _proto_bytes(field, value.encode("utf-8"))


# ---------- 消息 protobuf 构造 ----------

def build_send_message_proto(
    from_uid: str,
    to_uid: str,
    content: str,
    nickname: str,
    client_msg_id: Optional[str] = None,
) -> bytes:
    """构造文本私信 protobuf（与页面 WS 帧 b 字段解码结果一致）。"""
    client_msg_id = client_msg_id or str(uuid.uuid4())
    ts_ms = int(time.time() * 1000)
    inner = b"".join(
        [
            _proto_str(1, client_msg_id),
            _proto_varint(2, ts_ms),
            _proto_str(3, ""),
            _proto_str(4, from_uid),
            _proto_str(5, to_uid),
            _proto_str(6, content),
            _proto_varint(7, 1),  # contentType: 1=文本
            _proto_str(8, nickname),
            _proto_varint(9, 0),
            _proto_str(11, ""),
            _proto_varint(12, 1),
        ]
    )
    outer = _proto_varint(1, 1) + _proto_bytes(9, inner)
    return outer


# ---------- 鉴权 token ----------

def fetch_login_token(
    cookie: str, device_id: Optional[str] = None
) -> Dict[str, Any]:
    """GET /api/sns/web/v1/celestial/lt，返回 {a_lt, r_lt, expired_time, device_id}。"""
    device_id = device_id or str(uuid.uuid4())
    signed = sign_headers(LT_URI, cookie, data={}, method="GET")
    headers = {
        "c_device_id": device_id,
        "user-agent": DEFAULT_UA,
        "referer": "https://www.xiaohongshu.com/",
        "accept": "application/json, text/plain, */*",
        "x-s": signed["x-s"],
        "x-t": signed["x-t"],
        "x-s-common": signed["x-s-common"],
        "x-b3-traceid": signed["x-b3-traceid"],
        "cookie": cookie,
    }
    resp = requests.get(LT_HOST + LT_URI, headers=headers, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    if not data.get("success") or data.get("code") != 0:
        raise RuntimeError(
            f"获取登录 token 失败: {json.dumps(data, ensure_ascii=False)[:300]}"
        )
    d = data.get("data") or {}
    d["device_id"] = device_id
    return d


# ---------- WS 发送 ----------

def _recv_json(ws: websocket.WebSocket, timeout: float = 10.0) -> Dict[str, Any]:
    ws.settimeout(timeout)
    raw = ws.recv()
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", "replace")
    return json.loads(raw)


def _send_signal(
    ws: websocket.WebSocket,
    signal_type: int,
    payload: Dict[str, Any],
    ack_mode: int = 1,
) -> str:
    msg_id = str(uuid.uuid4())
    frame = {
        "v": 1,
        "t": 2,
        "m": msg_id,
        "b": {"d": {"a": ack_mode, "s": signal_type, "b": payload}},
    }
    ws.send(json.dumps(frame, ensure_ascii=False, separators=(",", ":")))
    return msg_id


def _ws_sslopt() -> Dict[str, Any]:
    sslopt: Dict[str, Any] = {}
    try:
        import certifi

        sslopt["ca_certs"] = certifi.where()
    except Exception:
        sslopt["cert_reqs"] = ssl.CERT_NONE
    return sslopt


def _open_im_ws(
    cookie: str,
    from_uid: str,
    *,
    sid: Optional[str] = None,
    device_id: Optional[str] = None,
    connect_timeout: float = 10.0,
) -> "tuple[websocket.WebSocket, str, str, Dict[str, Any], Dict[str, Any]]":
    """取 sid -> 连 WS -> LOGIN -> BIZ_REGISTER(im)。返回 (ws, sid, device_id, auth_ack, reg_ack)。"""
    device_id = device_id or get_device_id(from_uid)
    if not sid:
        token = fetch_login_token(cookie, device_id)
        sid = token.get("a_lt") or ""
        device_id = token.get("device_id") or device_id
        if not sid:
            raise RuntimeError("celestial/lt 未返回 a_lt sid")
    fingerprint = str(int(time.time() * 1000))

    ws = websocket.create_connection(
        LONG_LINK_HOST,
        timeout=connect_timeout,
        sslopt=_ws_sslopt(),
        header={"User-Agent": DEFAULT_UA, "Origin": "https://www.xiaohongshu.com"},
    )
    try:
        login_payload = {
            "appId": "xhs-pc",
            "authInfo": {
                "authType": "generic",
                "sid": sid,
                "uid": from_uid,
                "domain": "red",
            },
            "deviceInfo": {
                "deviceId": device_id,
                "fingerprint": fingerprint,
                "platform": "browser",
                "os": "web",
                "osVersion": "10.15",
                "deviceName": "Chrome",
                "appVersion": "131.0.0.0",
                "userAgent": DEFAULT_UA,
            },
            "serviceTag": "",
            "bizInfos": [{"bizName": "im", "serializeType": "protobuf"}],
            "roomInfos": [],
            "tagInfo": [],
            "extInfo": {},
            "state": 1,
        }
        _send_signal(ws, 0, login_payload)
        auth_ack = _recv_json(ws)
        _send_signal(
            ws,
            1,
            {
                "bizInfo": {"bizName": "im", "serializeType": "protobuf"},
                "register": True,
            },
        )
        reg_ack = _recv_json(ws)
        return ws, sid, device_id, auth_ack, reg_ack
    except Exception:
        try:
            ws.close()
        except Exception:
            pass
        raise


def _extract_ack_message_id(ack: Optional[Dict[str, Any]]) -> Optional[str]:
    """从发送 ack 帧的 b.a.b（base64 protobuf）里解析服务端 message_id。
    结构（抓包验证）：外层 f5 -> {f1: message_id, f2: from.to.session, f3: ts, f4: 'ok88'}。
    """
    try:
        a = (ack or {}).get("b") or {}
        if isinstance(a, dict):
            a = a.get("a") or {}
        payload = (a or {}).get("b")
        if isinstance(payload, str):
            raw = base64.b64decode(payload)
            inner = _proto_field_bytes(raw, 5) or raw
            mid = _proto_field_bytes(inner, 1)
            if mid:
                return mid.decode("utf-8", "replace")
    except Exception:
        pass
    return None


def send_text_ws(
    cookie: str,
    from_uid: str,
    to_uid: str,
    content: str,
    nickname: str,
    *,
    sid: Optional[str] = None,
    device_id: Optional[str] = None,
    connect_timeout: float = 10.0,
) -> Dict[str, Any]:
    """通过 WebSocket 长连接直发一条文本私信。

    cookie: xhs 登录 cookie（含 web_session）
    from_uid / to_uid: 双方 user_id
    nickname: 我的昵称（发信人展示名）
    返回 ack 信息（含服务端 message_id 等）。
    """
    # 1) 连接 + 握手
    ws, sid, device_id, auth_ack, reg_ack = _open_im_ws(
        cookie,
        from_uid,
        sid=sid,
        device_id=device_id,
        connect_timeout=connect_timeout,
    )
    try:
        # 2) 构造并发送消息 DATA 帧
        proto = build_send_message_proto(from_uid, to_uid, content, nickname)
        data_frame = {
            "v": 1,
            "t": 3,
            "m": str(uuid.uuid4()),
            "b": {
                "d": {
                    "a": 2,
                    "c": "sendMessage",
                    "biz": "im",
                    "b": base64.b64encode(proto).decode("ascii"),
                    "e": {},
                    "s": "rrmp.b.i",
                }
            },
        }
        ws.send(json.dumps(data_frame, ensure_ascii=False, separators=(",", ":")))

        # 3) 等 ack（可能先来心跳或其它帧，过滤到含成功标识的帧）
        ack = None
        deadline = time.time() + 15
        while time.time() < deadline:
            try:
                frame = _recv_json(ws, timeout=5)
            except Exception:
                break
            t = frame.get("t")
            if t == 0:
                continue
            if t == 2:
                continue  # SIGNAL ack，非发送确认
            ack = frame
            break

        message_id = _extract_ack_message_id(ack)
        # 成功判定：收到 DATA ack 且解析出 message_id（c==0）
        ok = bool(message_id)
        if ack:
            try:
                code = ((ack.get("b") or {}).get("a") or {}).get("c")
                ok = ok or (code == 0)
            except Exception:
                pass

        return {
            "ok": ok,
            "via": "ws",
            "ack": ack,
            "login_ack": auth_ack,
            "register_ack": reg_ack,
            "message_id": message_id,
        }
    finally:
        try:
            ws.close()
        except Exception:
            pass


# ---------- WS 实时接收 ----------

def _proto_field_bytes(buf: bytes, field: int) -> Optional[bytes]:
    """取 protobuf 中某字段的 bytes 值（跳过其它字段）。"""
    i = 0
    n = len(buf)

    def rvarint() -> int:
        nonlocal i
        r = 0
        shift = 0
        while True:
            b = buf[i]
            i += 1
            r |= (b & 0x7F) << shift
            if not (b & 0x80):
                return r
            shift += 7

    while i < n:
        try:
            tag = rvarint()
        except IndexError:
            return None
        f = tag >> 3
        wt = tag & 7
        if wt == 0:
            val = rvarint()
            if f == field:
                return str(val).encode()
        elif wt == 2:
            ln = rvarint()
            val = buf[i : i + ln]
            i += ln
            if f == field:
                return val
        elif wt == 1:
            if f == field:
                return buf[i : i + 8]
            i += 8
        elif wt == 5:
            if f == field:
                return buf[i : i + 4]
            i += 4
        else:
            return None
    return None


def _proto_field_varint(buf: bytes, field: int) -> int:
    val = _proto_field_bytes(buf, field)
    try:
        return int(val.decode("utf-8")) if val else 0
    except Exception:
        return 0


def _parse_pushed_message(b64_payload: str) -> Optional[Dict[str, Any]]:
    """解析下行推送消息（t=4 帧 b.d.b[].d 的 base64 protobuf）。

    结构：外层 f4 -> inner{f1:client_uuid, f2:message_id, f3:timestamp_ms,
    f5:JSON(含 content/sender/receiver/store_id/message_type 等)}。
    content 字段可能是「双层 JSON」：外层 JSON 的 content 是一个 JSON 字符串。
    """
    try:
        raw = base64.b64decode(b64_payload or "")
    except Exception:
        return None
    inner = _proto_field_bytes(raw, 4) or raw
    client_uuid = _proto_field_bytes(inner, 1) or b""
    message_id = _proto_field_bytes(inner, 2) or b""
    ts_ms = _proto_field_varint(inner, 3)
    payload = _proto_field_bytes(inner, 5) or b""
    info: Dict[str, Any] = {}
    try:
        info = json.loads(payload.decode("utf-8", "replace"))
    except Exception:
        pass
    content = info.get("content") or ""
    text = content
    nickname = ""
    raw_inner: Any = None
    if isinstance(content, str) and content.strip().startswith("{"):
        try:
            inner_c = json.loads(content)
            raw_inner = inner_c
            text = inner_c.get("content") or content
            nickname = inner_c.get("nickname") or ""
        except Exception:
            pass
    ts = info.get("timestamp") or ts_ms or 0
    try:
        ts = int(ts)
    except Exception:
        ts = 0
    when = ""
    if ts > 0:
        when = datetime.datetime.fromtimestamp(ts / 1000.0).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
    return {
        "client_uuid": client_uuid.decode("utf-8", "replace"),
        "message_id": message_id.decode("utf-8", "replace"),
        "time": when,
        "timestamp_ms": ts,
        "sender": str(info.get("sender") or ""),
        "receiver": str(info.get("receiver") or ""),
        "store_id": info.get("store_id"),
        "text": text,
        "nickname": nickname,
        "message_type": info.get("message_type"),
        "outgoing": info.get("outgoing"),
        "revoked": info.get("revoked"),
        "sync_chat": info.get("sync_chat"),
        "raw_info": info,
        "raw_inner": raw_inner,
    }


def _send_push_ack(ws: websocket.WebSocket, push_m: str) -> None:
    """回推确认：与浏览器一致 b.a={"c":0,"m":"success"}。"""
    frame = {
        "v": 1,
        "t": 4,
        "m": push_m,
        "b": {"a": {"c": 0, "m": "success"}},
    }
    try:
        ws.send(json.dumps(frame, ensure_ascii=False, separators=(",", ":")))
    except Exception:
        pass


def receive_messages_ws(
    cookie: str,
    from_uid: str,
    *,
    sid: Optional[str] = None,
    device_id: Optional[str] = None,
    connect_timeout: float = 10.0,
    ping_interval: float = 20.0,
    ack_push: bool = True,
    seconds: int = 0,
) -> Iterator[Dict[str, Any]]:
    """建立 WS 长连接持续监听下行私信推送（实时接收）。

    - t=0 心跳：客户端发起，收到回声忽略
    - t=2 SIGNAL ack：忽略
    - t=4 DATA 推送：解析 b.d.b[] 消息，回 ack，yield 每条消息
    seconds>0 时监听 N 秒后结束；0=一直监听。
    """
    ws, sid, device_id, auth_ack, reg_ack = _open_im_ws(
        cookie,
        from_uid,
        sid=sid,
        device_id=device_id,
        connect_timeout=connect_timeout,
    )
    logger.info(
        "ws connected sid_len=%s device=%s auth=%s reg=%s",
        len(sid),
        device_id,
        (auth_ack.get("b") or {}).get("c"),
        (reg_ack.get("b") or {}).get("c"),
    )
    try:
        last_ping = time.time()
        start = time.time()
        while True:
            if seconds > 0 and (time.time() - start) >= seconds:
                break
            try:
                frame = _recv_json(ws, timeout=min(5.0, max(1.0, ping_interval - 5)))
            except websocket.WebSocketTimeoutException:
                if time.time() - last_ping >= ping_interval:
                    try:
                        ws.send(json.dumps({"v": 1, "t": 0}, separators=(",", ":")))
                        last_ping = time.time()
                    except Exception:
                        break
                continue
            except Exception:
                break
            t = frame.get("t")
            if t == 0:
                continue  # 心跳回声
            if t == 2:
                continue  # SIGNAL ack
            if t == 4:
                d = (frame.get("b") or {}).get("d") or {}
                push_m = str(frame.get("m") or "")
                items = d.get("b") or []
                for item in items:
                    msg = _parse_pushed_message(item.get("d") or "")
                    if msg:
                        yield msg
                if ack_push and push_m and items:
                    _send_push_ack(ws, push_m)
                continue
            # 其它帧忽略
    finally:
        try:
            ws.close()
        except Exception:
            pass
