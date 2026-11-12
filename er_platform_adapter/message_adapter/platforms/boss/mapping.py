"""Map raw BOSS chat payloads into platform-neutral text events."""

from __future__ import annotations

import html
import re
from typing import Any


def _integer(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def mqtt_is_mine(
    *,
    from_uid: int = 0,
    to_uid: int = 0,
    flag: int = 0,
    my_uid: int = 0,
    from_name: str = "",
    my_encrypt: str = "",
    my_name: str = "",
) -> bool:
    """Return whether a live MQTT frame was sent by the current actor."""
    from_uid = _integer(from_uid)
    to_uid = _integer(to_uid)
    my_uid = _integer(my_uid)
    flag = _integer(flag)
    from_name = str(from_name or "")
    my_encrypt = str(my_encrypt or "")
    my_name = str(my_name or "")
    if my_uid and from_uid == my_uid:
        return True
    if my_encrypt and from_name == my_encrypt:
        return True
    if flag & 0x10000:
        if my_uid and to_uid == my_uid and from_uid != my_uid:
            return False
        return True
    return bool(my_name and from_name == my_name and my_uid and to_uid and to_uid != my_uid)


def _history_is_mine(message: dict[str, Any], *, my_uid: int, peer_uid: int) -> bool:
    sender = message.get("from") if isinstance(message.get("from"), dict) else {}
    recipient = message.get("to") if isinstance(message.get("to"), dict) else {}
    from_uid = _integer(sender.get("uid") or message.get("fromUid"))
    to_uid = _integer(recipient.get("uid") or message.get("toUid"))
    my_uid = _integer(my_uid)
    peer_uid = _integer(peer_uid)
    if my_uid and from_uid == my_uid:
        return True
    if peer_uid and from_uid == peer_uid:
        return False
    if _integer(message.get("flag")) & 0x10000:
        return True
    if peer_uid and from_uid and from_uid != peer_uid:
        return True
    if my_uid and to_uid == my_uid and from_uid and from_uid != my_uid:
        return False
    if "received" in message:
        return not bool(message.get("received"))
    return False


def _text(message: dict[str, Any]) -> str:
    body = message.get("body")
    candidates: list[Any] = []
    if isinstance(body, dict):
        candidates.extend((body.get("text"), body.get("showText"), body.get("headTitle")))
    elif isinstance(body, str):
        candidates.append(body)
    candidates.extend((message.get("text"), message.get("showText")))
    value = next((item for item in candidates if isinstance(item, str) and item), "")
    value = html.unescape(value)
    return re.sub(r"</?(?:copy|phone|job|company|encrypt|tel|span)\b[^>]*>", "", value)


def _timestamp_ms(message: dict[str, Any]) -> int:
    value = _integer(message.get("time") or message.get("addTime"))
    if value <= 0:
        return 0
    return value if value > 10_000_000_000 else value * 1000


def history_message(message: dict[str, Any], *, my_uid: int = 0, peer_uid: int = 0) -> dict[str, Any]:
    """Return the text-only history fields consumed by the BOSS adapter."""
    body = message.get("body")
    body_type = body.get("type") if isinstance(body, dict) else None
    message_type = message.get("type") if message.get("type") is not None else body_type
    text = _text(message)
    kind = "text" if text or body_type in (None, 0, 1) else "unsupported"
    return {
        "mid": message.get("mid") or message.get("msgId") or message.get("cmid"),
        "text": text,
        "ts": _timestamp_ms(message),
        "mine": _history_is_mine(message, my_uid=my_uid, peer_uid=peer_uid),
        "type": message_type,
        "kind": kind,
    }
