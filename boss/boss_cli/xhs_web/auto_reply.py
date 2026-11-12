# -*- coding: utf-8 -*-
"""小红书私信自动回复（了解私信聚合平台）。

流程（每个会话只走一遍）：
  1. 对方发来任意类型消息（文本/图片/语音等）→ 「你好，是要了解私信聚合吗」
  2. 对方再发任意回复 → 「+🌍180******」
  3. 之后该会话不再自动回复
"""

from __future__ import annotations

import logging
import random
import threading
import time
from typing import Any, Callable, Dict, Optional, Set

logger = logging.getLogger("xhs_web.auto_reply")

GREETING = "你好，是要了解私信聚合吗"
CONTACT = "+🌍180******"

# chat_user_id -> "idle" | "awaiting" | "done"
_states: Dict[str, str] = {}
_seen_msg_ids: Set[str] = set()
_lock = threading.Lock()
_enabled = True

# 同一会话短时间多条消息只触发一次（防刷）
_last_action_at: Dict[str, float] = {}
_ACTION_COOLDOWN_S = 2.0
# 收到对方消息后，随机等待再回复
_REPLY_DELAY_MIN_S = 5.0
_REPLY_DELAY_MAX_S = 8.0


def set_enabled(on: bool) -> None:
    global _enabled
    _enabled = bool(on)
    logger.info("auto_reply enabled=%s", _enabled)


def is_enabled() -> bool:
    return _enabled


def _remember_msg(key: str) -> bool:
    """返回 True 表示首次见到，应处理；False 表示重复。"""
    if not key or key.endswith(":"):
        return True
    with _lock:
        if key in _seen_msg_ids:
            return False
        _seen_msg_ids.add(key)
        if len(_seen_msg_ids) > 5000:
            drop = list(_seen_msg_ids)[:2500]
            for x in drop:
                _seen_msg_ids.discard(x)
        return True


def handle_incoming(
    ev: Dict[str, Any],
    *,
    send_fn: Callable[[str, str], Any],
    on_sent: Optional[Callable[[str, str], None]] = None,
) -> None:
    """处理一条对方发来的消息，按需自动回复。"""
    if not _enabled:
        return
    if ev.get("outgoing") or ev.get("revoked"):
        return
    cid = str(ev.get("chat_user_id") or "").strip()
    if not cid:
        return
    mid = str(ev.get("message_id") or "")
    sid = str(ev.get("store_id") or "")
    dedupe_key = f"{cid}:{mid or sid}"
    if not _remember_msg(dedupe_key):
        return

    with _lock:
        state = _states.get(cid, "idle")

    if state == "done":
        return

    try:
        now = time.time()
        with _lock:
            last = _last_action_at.get(cid, 0)
            if now - last < _ACTION_COOLDOWN_S:
                return

        delay = random.uniform(_REPLY_DELAY_MIN_S, _REPLY_DELAY_MAX_S)
        logger.info("auto_reply wait %.1fs cid=%s state=%s", delay, cid, state)
        time.sleep(delay)

        if state == "awaiting":
            _send(cid, CONTACT, send_fn, on_sent)
            with _lock:
                _last_action_at[cid] = time.time()
                _states[cid] = "done"
            return

        # idle：对方首条消息（任意类型）→ 发问候
        _send(cid, GREETING, send_fn, on_sent)
        with _lock:
            _last_action_at[cid] = time.time()
            _states[cid] = "awaiting"
    except Exception as exc:  # noqa: BLE001
        logger.exception("auto_reply failed cid=%s: %s", cid, exc)
        with _lock:
            if _states.get(cid) == "awaiting" and state != "awaiting":
                _states[cid] = state or "idle"


def _send(
    cid: str,
    text: str,
    send_fn: Callable[[str, str], Any],
    on_sent: Optional[Callable[[str, str], None]],
) -> None:
    logger.info("auto_reply → %s text=%r", cid, text[:80].replace("\n", "\\n"))
    send_fn(cid, text)
    if on_sent:
        try:
            on_sent(cid, text)
        except Exception as exc:  # noqa: BLE001
            logger.warning("on_sent failed: %s", exc)
