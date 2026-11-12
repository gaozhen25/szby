"""MQTT-over-WSS chat for geek (job seeker) and recruiter (boss) sides.

BOSS 直聘 sends text DMs over MQTT, not HTTP.
Protocol details match public unofficial clients (e.g. zhipin-geek):

- Server: wss://ws6.zhipin.com/chatws (fallbacks: ws.zhipin.com, ws2.zhipin.com)
- Auth: username = page_token + "|0" (geek) or "|1" (recruiter), password = wt2
- Topic: chat (QoS 1)
- Payload: hand-encoded Protobuf TechwolfChatProtocol
- Message flag low 2 bits: 0=geek, 1=boss
"""

from __future__ import annotations

import json
import logging
import queue
import threading
import time
import uuid

logger = logging.getLogger(__name__)


def _varint(value: int) -> bytes:
    bits: list[int] = []
    value = int(value)
    if value < 0:
        raise ValueError("protobuf varint must be non-negative")
    while True:
        b = value & 0x7F
        value >>= 7
        if value:
            bits.append(b | 0x80)
        else:
            bits.append(b)
            break
    return bytes(bits)


def _field(field_num: int, wire_type: int, data: bytes) -> bytes:
    return _varint((field_num << 3) | wire_type) + data


def _field_varint(field_num: int, value: int) -> bytes:
    return _field(field_num, 0, _varint(value))


def _field_bytes(field_num: int, data: bytes) -> bytes:
    return _field(field_num, 2, _varint(len(data)) + data)


def _field_string(field_num: int, text: str) -> bytes:
    return _field_bytes(field_num, text.encode("utf-8"))


def encode_user(uid: int, encrypt_uid: str = "", source: int = 0) -> bytes:
    """TechwolfUser { uid=1, name=2, source=7 }."""
    buf = _field_varint(1, uid)
    if encrypt_uid:
        buf += _field_string(2, encrypt_uid)
    if source:
        buf += _field_varint(7, source)
    return buf


def encode_body(text: str) -> bytes:
    """TechwolfMessageBody { type=1, templateId=2, text=3 }."""
    return _field_varint(1, 1) + _field_varint(2, 1) + _field_string(3, text)


def encode_message(
    from_uid: int,
    from_encrypt_uid: str,
    to_uid: int,
    to_encrypt_uid: str,
    text: str,
    temp_id: int,
    flag: int = 0,
    time_ms: int | None = None,
) -> bytes:
    """TechwolfMessage { from=1, to=2, type=3, mid=4, time=5, body=6, cmid=11, flag=15 }.

    Recruiter-sent history uses flag=65537 (identity 1 | 0x10000), not flag=1.
    """
    if time_ms is None:
        time_ms = int(time.time() * 1000)
    buf = _field_bytes(1, encode_user(from_uid, from_encrypt_uid))
    buf += _field_bytes(2, encode_user(to_uid, to_encrypt_uid))
    buf += _field_varint(3, 1)
    buf += _field_varint(4, temp_id)
    buf += _field_varint(5, int(time_ms))
    buf += _field_bytes(6, encode_body(text))
    buf += _field_varint(11, temp_id)
    if flag:
        buf += _field_varint(15, flag)
    return buf


def encode_chat_protocol(message_bytes: bytes) -> bytes:
    """TechwolfChatProtocol { type=1, messages=3 }."""
    return _field_varint(1, 1) + _field_bytes(3, message_bytes)


def build_text_message(
    from_uid: int,
    from_encrypt_uid: str,
    to_uid: int,
    to_encrypt_uid: str,
    text: str,
    temp_id: int | None = None,
    flag: int = 0,
) -> bytes:
    """Build a complete Protobuf-encoded text chat payload."""
    if temp_id is None:
        temp_id = int(time.time() * 1000)
    return encode_chat_protocol(
        encode_message(
            from_uid, from_encrypt_uid, to_uid, to_encrypt_uid, text, temp_id, flag=flag,
            time_ms=temp_id,
        )
    )


def encode_presence(uid: int, presence_type: int = 1) -> bytes:
    """TechwolfChatProtocol type=2 with TechwolfPresence { type=1 online, uid }."""
    inner = _field_varint(1, presence_type) + _field_varint(2, int(uid))
    return _field_varint(1, 2) + _field_bytes(4, inner)


def _decode_varint(buf: bytes, pos: int) -> tuple[int, int]:
    result = 0
    shift = 0
    while pos < len(buf):
        b = buf[pos]
        pos += 1
        result |= (b & 0x7F) << shift
        if not (b & 0x80):
            return result, pos
        shift += 7
        if shift > 70:
            break
    raise ValueError("truncated protobuf varint")


def iter_fields(buf: bytes):
    """Yield (field_number, value, wire_type) from a protobuf message."""
    pos = 0
    while pos < len(buf):
        try:
            tag, pos = _decode_varint(buf, pos)
        except ValueError:
            break
        field_num = tag >> 3
        wire = tag & 7
        if wire == 0:
            value, pos = _decode_varint(buf, pos)
            yield field_num, value, 0
        elif wire == 2:
            length, pos = _decode_varint(buf, pos)
            yield field_num, buf[pos : pos + length], 2
            pos += length
        elif wire == 1:
            yield field_num, buf[pos : pos + 8], 1
            pos += 8
        elif wire == 5:
            yield field_num, buf[pos : pos + 4], 5
            pos += 4
        else:
            break


def _utf8(data: bytes) -> str:
    return data.decode("utf-8", "replace")


def _nested_string(buf: bytes, field_num: int) -> str:
    for number, value, wire in iter_fields(buf):
        if number == field_num and wire == 2:
            return _utf8(value)
    return ""


BODY_TYPE_LABELS = {
    1: "text",
    2: "语音",
    3: "图片",
    4: "动作",
    5: "图文",
    6: "通知",
    7: "对话框",
    8: "职位",
    9: "简历",
    12: "文件",
}


def parse_user(buf: bytes) -> dict:
    user = {"uid": 0, "name": "", "company": ""}
    for number, value, wire in iter_fields(buf):
        if number == 1 and wire == 0:
            user["uid"] = int(value)
        elif number == 2 and wire == 2:
            user["name"] = _utf8(value)
        elif number == 4 and wire == 2:
            user["company"] = _utf8(value)
    return user


def parse_body(buf: bytes) -> dict:
    body: dict = {"type": 0, "templateId": 0, "text": "", "headTitle": ""}
    for number, value, wire in iter_fields(buf):
        if number == 1 and wire == 0:
            body["type"] = int(value)
        elif number == 2 and wire == 0:
            body["templateId"] = int(value)
        elif number == 3 and wire == 2:
            body["text"] = _utf8(value)
        elif number == 11 and wire == 2:
            body["headTitle"] = _utf8(value)
        elif number == 6 and wire == 2:
            aid = 0
            extend = ""
            for inner_n, inner_v, inner_w in iter_fields(value):
                if inner_n == 1 and inner_w == 0:
                    aid = int(inner_v)
                elif inner_n == 2 and inner_w == 2:
                    extend = _utf8(inner_v)
            action_text = ""
            if extend:
                try:
                    extra = json.loads(extend)
                except json.JSONDecodeError:
                    extra = None
                if isinstance(extra, dict):
                    action_text = str(extra.get("text") or extra.get("sourceTitle") or extra.get("title") or "")
                elif not action_text:
                    action_text = extend
            body["text"] = body["text"] or action_text or f"[动作 {aid}]".strip()
        elif number == 4 and wire == 2:
            sound = {"url": "", "duration": 0}
            for inner_n, inner_v, inner_w in iter_fields(value):
                if inner_n == 1 and inner_w == 2:
                    sound["url"] = _utf8(inner_v)
                elif inner_n == 2 and inner_w == 0:
                    sound["duration"] = int(inner_v)
            body["sound"] = sound
            if sound["url"] and not body["text"]:
                dur = int(sound["duration"] or 0)
                body["text"] = f"[语音 {dur}秒]" if dur else "[语音]"
        elif number == 5 and wire == 2:
            tiny = ""
            origin = ""
            for inner_n, inner_v, inner_w in iter_fields(value):
                if inner_n == 1 and inner_w == 2:
                    tiny = _nested_string(inner_v, 1)
                elif inner_n == 2 and inner_w == 2:
                    origin = _nested_string(inner_v, 1)
            if tiny or origin:
                body["image"] = {
                    "tinyImage": {"url": tiny},
                    "originImage": {"url": origin or tiny},
                }
                body["text"] = body["text"] or "[图片]"
        elif number == 8 and wire == 2:
            title = _nested_string(value, 1)
            url = _nested_string(value, 4) or _nested_string(value, 2)
            body["text"] = body["text"] or title
            if url:
                body["file"] = {"url": url, "name": title or "附件"}
        elif number == 9 and wire == 2:
            body["text"] = body["text"] or _nested_string(value, 1)
        elif number == 10 and wire == 2:
            title = _nested_string(value, 1)
            salary = _nested_string(value, 3)
            if title:
                body["text"] = body["text"] or f"[职位] {title} {salary}".strip()
    if not body["text"]:
        label = BODY_TYPE_LABELS.get(body["type"], f"类型{body['type']}")
        if body["type"] and body["type"] != 1:
            body["text"] = body["headTitle"] or f"[{label}]"
        else:
            body["text"] = body["headTitle"]
    return body


def parse_message(buf: bytes) -> dict:
    msg: dict = {
        "from": {"uid": 0, "name": ""},
        "to": {"uid": 0, "name": ""},
        "type": 0,
        "mid": None,
        "time": 0,
        "body": {"type": 0, "text": ""},
        "cmid": None,
        "flag": 0,
    }
    for number, value, wire in iter_fields(buf):
        if number == 1 and wire == 2:
            msg["from"] = parse_user(value)
        elif number == 2 and wire == 2:
            msg["to"] = parse_user(value)
        elif number == 3 and wire == 0:
            msg["type"] = int(value)
        elif number == 4 and wire == 0:
            msg["mid"] = int(value)
        elif number == 5 and wire == 0:
            msg["time"] = int(value)
        elif number == 6 and wire == 2:
            msg["body"] = parse_body(value)
        elif number == 11 and wire == 0:
            msg["cmid"] = int(value)
        elif number == 15 and wire == 0:
            msg["flag"] = int(value)
    return msg


def decode_chat_protocol(buf: bytes) -> dict:
    """Decode a TechwolfChatProtocol payload into a plain dict."""
    proto: dict = {"type": 0, "messages": []}
    for number, value, wire in iter_fields(buf):
        if number == 1 and wire == 0:
            proto["type"] = int(value)
        elif number == 3 and wire == 2:
            proto["messages"].append(parse_message(value))
    return proto


IDENTITY_GEEK = 0
IDENTITY_BOSS = 1
# Recruiter-originated chat history uses this flag (low 2 bits still = boss).
FLAG_BOSS_SENT = IDENTITY_BOSS | 0x10000


class BossMQTTChat:
    """MQTT over WSS client for sending and receiving chat."""

    WS_SERVERS = ("ws6.zhipin.com", "ws.zhipin.com", "ws2.zhipin.com")
    PORT = 443
    PATH = "/chatws"
    TOPIC = "chat"
    SUBSCRIBE_TOPICS = ("chat", "/chatws")

    def __init__(
        self,
        page_token: str,
        wt2: str,
        cookies: dict[str, str] | None = None,
        timeout: float = 12.0,
        identity: int = IDENTITY_GEEK,
    ):
        self._page_token = page_token
        self._wt2 = wt2
        self._cookies = cookies or {}
        self._timeout = timeout
        self._identity = int(identity)
        self._client = None
        self._connected = threading.Event()
        self._dropped = threading.Event()
        self._error: str | None = None
        self._incoming: queue.Queue = queue.Queue()

    def _make_client(self):
        try:
            import paho.mqtt.client as mqtt
        except ImportError as exc:
            raise RuntimeError("聊天需要 paho-mqtt。请执行: uv sync") from exc

        client_id = f"ws-{uuid.uuid4().hex[:16].upper()}"
        try:
            client = mqtt.Client(
                callback_api_version=mqtt.CallbackAPIVersion.VERSION1,
                client_id=client_id,
                transport="websockets",
            )
        except AttributeError:
            client = mqtt.Client(client_id=client_id, transport="websockets")

        client.tls_set()
        cookie_str = "; ".join(f"{k}={v}" for k, v in self._cookies.items() if v)
        client.ws_set_options(
            path=self.PATH,
            headers={
                "Origin": "https://www.zhipin.com",
                "Cookie": cookie_str,
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/145.0.0.0 Safari/537.36"
                ),
            },
        )
        client.username_pw_set(
            username=f"{self._page_token}|{self._identity}",
            password=self._wt2,
        )
        client.on_connect = self._on_connect
        client.on_disconnect = self._on_disconnect
        client.on_message = self._on_message
        return client

    def _on_connect(self, client, userdata, flags, rc):  # noqa: ARG002
        if rc == 0:
            for topic in self.SUBSCRIBE_TOPICS:
                try:
                    client.subscribe(topic, qos=1)
                except Exception:
                    logger.debug("MQTT subscribe %s failed", topic, exc_info=True)
            logger.debug("MQTT connected")
            self._dropped.clear()
            self._connected.set()
            return
        self._error = f"MQTT 认证失败 (rc={rc})"
        self._connected.set()

    def _on_disconnect(self, client, userdata, rc):  # noqa: ARG002
        logger.debug("MQTT disconnected: rc=%s", rc)
        if rc != 0:
            self._dropped.set()

    def _on_message(self, client, userdata, msg):  # noqa: ARG002
        payload = bytes(msg.payload or b"")
        if not payload:
            return
        try:
            decoded = decode_chat_protocol(payload)
        except Exception:
            logger.debug("MQTT payload decode failed (%d bytes)", len(payload), exc_info=True)
            return
        decoded["topic"] = getattr(msg, "topic", "")
        decoded["raw_size"] = len(payload)
        self._incoming.put(decoded)

    def _stop_client(self) -> None:
        if not self._client:
            return
        try:
            self._client.loop_stop()
        except Exception:
            logger.debug("MQTT loop_stop failed", exc_info=True)
        try:
            self._client.disconnect()
        except Exception:
            logger.debug("MQTT disconnect failed", exc_info=True)
        self._client = None

    def __enter__(self) -> BossMQTTChat:
        last_error: Exception | None = None
        for server in self.WS_SERVERS:
            self._connected.clear()
            self._error = None
            try:
                self._client = self._make_client()
                self._dropped.clear()
                logger.debug("Connecting MQTT %s:%s%s", server, self.PORT, self.PATH)
                self._client.connect(server, self.PORT, keepalive=25)
                self._client.loop_start()
                if not self._connected.wait(timeout=self._timeout):
                    self._stop_client()
                    last_error = TimeoutError(f"连接 {server} 超时")
                    continue
                if self._error:
                    self._stop_client()
                    last_error = RuntimeError(self._error)
                    continue
                return self
            except Exception as exc:
                last_error = exc
                self._stop_client()
        raise RuntimeError(f"MQTT 连接失败: {last_error}")

    def __exit__(self, *args) -> None:  # noqa: ANN002
        self._stop_client()

    def send(
        self,
        from_uid: int,
        from_encrypt_uid: str,
        to_uid: int,
        to_encrypt_uid: str,
        text: str,
    ) -> None:
        if not self._client:
            raise RuntimeError("MQTT 未连接")
        flag = FLAG_BOSS_SENT if self._identity == IDENTITY_BOSS else self._identity
        payload = build_text_message(
            from_uid, from_encrypt_uid, to_uid, to_encrypt_uid, text, flag=flag,
        )
        last_error: Exception | None = None
        published = False
        for topic in (self.TOPIC, "/chatws"):
            try:
                result = self._client.publish(topic, payload, qos=1, retain=False)
                if not published:
                    result.wait_for_publish(timeout=min(float(self._timeout), 5.0))
                    if getattr(result, "rc", 0) not in (0, None):
                        last_error = RuntimeError(f"MQTT 发布失败 (topic={topic} rc={result.rc})")
                        continue
                    published = True
                    logger.debug("MQTT published topic=%s mid=%s", topic, result.mid)
            except Exception as exc:
                last_error = exc
                logger.debug("MQTT publish %s failed", topic, exc_info=True)
        if not published:
            raise last_error or RuntimeError("MQTT 发布失败")

    def _publish(self, payload: bytes) -> None:
        if not self._client:
            raise RuntimeError("MQTT 未连接")
        result = self._client.publish(self.TOPIC, payload, qos=1, retain=False)
        result.wait_for_publish(timeout=self._timeout)
        if getattr(result, "rc", 0) not in (0, None):
            raise RuntimeError(f"MQTT 发布失败 (rc={result.rc})")

    def announce_online(self, uid: int) -> None:
        """Send presence=online so the server starts pushing inbound messages."""
        self._publish(encode_presence(uid, presence_type=1))

    def poll_protocol(self, timeout: float = 0.5) -> dict | None:
        """Return the next decoded protocol frame, or None if nothing arrived."""
        try:
            return self._incoming.get(timeout=timeout)
        except queue.Empty:
            return None

    @property
    def dropped(self) -> bool:
        return self._dropped.is_set()


def _listen_clock(ts: int) -> str:
    from datetime import datetime

    if ts and ts > 10_000_000_000:
        ts = int(ts / 1000)
    try:
        when = datetime.fromtimestamp(ts) if ts else datetime.now()
    except (OSError, OverflowError, ValueError):
        when = datetime.now()
    return when.strftime("%H:%M:%S")


def run_mqtt_listen(
    *,
    page_token: str,
    wt2: str,
    cookies: dict[str, str],
    my_uid: int | None,
    identity: int = IDENTITY_GEEK,
    duration: int = 0,
    poll_seconds: int = 0,
    show_all: bool = False,
    backlog: bool = False,
    on_message,
    lookup_peer=None,
    refresh_peers=None,
    poll_once=None,
    on_status=None,
    on_reconnect=None,
    connect_timeout: float = 15.0,
) -> None:
    """Connect, announce online, and dispatch inbound chat frames until timeout/Ctrl+C."""
    seen_mids: set[int] = set()
    last_poll = 0.0
    last_name_refresh = 0.0
    started = time.time()
    reconnect_delay = 2.0
    token = page_token
    secret = wt2
    jar = cookies
    uid = my_uid

    def _status(text: str) -> None:
        if on_status:
            on_status(text)

    def _handle(frame: dict) -> None:
        nonlocal last_name_refresh
        if frame.get("type") != 1:
            return
        for msg in frame.get("messages") or []:
            mid = msg.get("mid")
            if isinstance(mid, int):
                if mid in seen_mids:
                    continue
                seen_mids.add(mid)
                if len(seen_mids) > 4000:
                    seen_mids.clear()
            from_obj = msg.get("from") or {}
            from_uid = int(from_obj.get("uid") or 0)
            from_name = str(from_obj.get("name") or "")
            is_me = bool(uid and from_uid == uid)
            if is_me and not show_all:
                continue
            msg_time = int(msg.get("time") or 0)
            msg_unix = msg_time / 1000 if msg_time > 10_000_000_000 else msg_time
            if not backlog and msg_unix and msg_unix < started - 120:
                continue
            name = from_name
            if not is_me and lookup_peer:
                cached = lookup_peer(from_uid)
                if cached:
                    name = name or cached
                elif refresh_peers and time.time() - last_name_refresh > 30:
                    last_name_refresh = time.time()
                    try:
                        refresh_peers()
                    except Exception:
                        logger.debug("listen peer refresh failed", exc_info=True)
                    cached = lookup_peer(from_uid) if lookup_peer else None
                    if cached:
                        name = name or cached
            if not name:
                name = "我" if is_me else (str(from_uid) if from_uid else "对方")
            body = msg.get("body") or {}
            on_message({
                "time": _listen_clock(msg_time),
                "direction": "我" if is_me else "对方",
                "name": name,
                "uid": from_uid,
                "mid": mid,
                "text": body.get("text") or body.get("headTitle") or "[非文本消息]",
            })

    while True:
        if duration > 0 and time.time() - started >= duration:
            _status("已到设定时长，结束接听")
            return
        try:
            with BossMQTTChat(
                token, secret, cookies=jar, timeout=connect_timeout, identity=identity,
            ) as chat:
                if uid:
                    try:
                        chat.announce_online(int(uid))
                    except Exception as exc:
                        logger.debug("presence failed: %s", exc)
                reconnect_delay = 2.0
                while True:
                    if duration > 0 and time.time() - started >= duration:
                        _status("已到设定时长，结束接听")
                        return
                    frame = chat.poll_protocol(timeout=0.5)
                    if frame:
                        _handle(frame)
                    if chat.dropped:
                        raise RuntimeError("MQTT 连接断开")
                    if poll_seconds > 0 and poll_once and time.time() - last_poll >= poll_seconds:
                        last_poll = time.time()
                        try:
                            poll_once()
                        except Exception:
                            logger.debug("listen poll failed", exc_info=True)
        except KeyboardInterrupt:
            raise
        except Exception as exc:
            _status(f"连接中断，{reconnect_delay:.0f}s 后重连: {exc}")
            time.sleep(reconnect_delay)
            reconnect_delay = min(30.0, reconnect_delay * 2)
            if on_reconnect:
                refreshed = on_reconnect()
                if refreshed:
                    token, secret, jar, uid = refreshed


format_listen_time = _listen_clock

