# -*- coding: utf-8 -*-
"""抖音 Web IM：按会话 HTTP 轮询 / 发送私信（不依赖 DouYin_Spider）。

接口:
  POST https://imapi.douyin.com/v1/conversation/get_list       (protobuf cmd=200)
  POST https://imapi.douyin.com/v1/message/get_by_conversation  (protobuf cmd=301)
  POST https://imapi.douyin.com/v2/conversation/create         (protobuf cmd=609)
  POST https://imapi.douyin.com/v1/message/send                (protobuf cmd=100)

鉴权: cookies.json 的 sessionid。
收信只需 cookie；发信协议还要 web_protect ticket，缺省时用同一份 cookie
自动打开抖音网页从 localStorage 抓取（写入 im_cred.json）。
"""
from __future__ import annotations

from collections import Counter
import base64
import hashlib
import json
import logging
import random
import re
import sys
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple
from urllib.parse import quote

import requests
import urllib3

from .im_client import DEFAULT_UA, DouyinClient
from .help import get_a_bogus, parse_cookie_str

urllib3.disable_warnings()

logger = logging.getLogger(__name__)

from boss_cli.constants import DOUYIN_IM_CRED_FILE

CRED_PATH = DOUYIN_IM_CRED_FILE
GET_BY_CONVERSATION = "https://imapi.douyin.com/v1/message/get_by_conversation"
CREATE_CONVERSATION = "https://imapi.douyin.com/v2/conversation/create"
SEND_MESSAGE = "https://imapi.douyin.com/v1/message/send"
GET_CONVERSATION_LIST = "https://imapi.douyin.com/v1/conversation/get_list"

DEFAULT_CONVERSATION_ID = "0:1:75604715923:468829025871684"
DEFAULT_CONVERSATION_SHORT_ID = 7303822822667764275

_nick_cache: Dict[str, str] = {}
_user_cache: Dict[str, Dict[str, Any]] = {}
_conv_title_cache: Dict[str, str] = {}


@dataclass
class ImAuth:
    cookie: Dict[str, str]
    cookie_str: str = ""
    ticket: str = ""
    ts_sign: str = ""
    client_cert: str = ""
    private_key: str = ""
    # 扫码/本地缓存的真实 uid（profile 风控时必须靠它，不能从单会话瞎猜）
    uid: str = ""
    account_name: str = ""
    _client: Optional[DouyinClient] = field(default=None, repr=False)

    @property
    def token(self) -> str:
        return self.ticket or self.cookie.get("sessionid", "")

    @property
    def client(self) -> DouyinClient:
        if self._client is None:
            self._client = DouyinClient(cookie=self.cookie_str)
        return self._client


def load_auth(*, cookie: str = "", account_name: str = "", uid: str = "") -> ImAuth:
    """从 cookie 字符串或 cookies.json 账号构建 ImAuth。"""
    acc_name = account_name
    stored_uid = str(uid or "").strip()
    if not cookie or (account_name and not stored_uid):
        from .credentials import load_douyin_cookie

        try:
            acc = load_douyin_cookie(account_name=account_name)
            if not cookie:
                cookie = acc.cookie
                acc_name = acc.name
            if not stored_uid:
                stored_uid = str(acc.uid or "").strip()
            if not acc_name:
                acc_name = acc.name
        except Exception:
            if not cookie:
                raise
    jar = parse_cookie_str(cookie)
    auth = ImAuth(cookie=jar, cookie_str=cookie, uid=stored_uid, account_name=str(acc_name or ""))
    # cookie 未显式传 account_name 时，按 sessionid 回填本地缓存的 uid
    if not auth.uid:
        try:
            from .credentials import load_douyin_cookie

            sid = str(jar.get("sessionid") or "")
            acc = load_douyin_cookie(account_name=acc_name) if acc_name else None
            if acc is None and sid:
                # 按 sessionid 精确匹配，避免 active 串号
                from .credentials import _find_account, _load_cookie_store

                hit = _find_account(list(_load_cookie_store().get("accounts") or []), sessionid=sid)
                if hit is not None:
                    auth.uid = str(hit.get("uid") or "").strip()
                    if not auth.account_name:
                        auth.account_name = str(hit.get("name") or "")
            elif acc is not None:
                auth.uid = str(acc.uid or "").strip()
                if not auth.account_name:
                    auth.account_name = acc.name
        except Exception:
            pass
    try:
        from .credentials import load_im_cred

        cred = load_im_cred(
            account_name=auth.account_name or acc_name,
            sessionid=str(jar.get("sessionid") or ""),
        )
        if cred:
            _apply_cred(auth, cred)
    except Exception:
        pass
    if not auth.token:
        raise RuntimeError("missing sessionid in cookie (and no ticket in im_cred.json)")
    return auth


def _send_cred_missing(auth: ImAuth) -> List[str]:
    missing = []
    if not auth.ticket:
        missing.append("DY_TICKET")
    if not auth.ts_sign:
        missing.append("DY_TS_SIGN")
    if not auth.client_cert:
        missing.append("DY_CLIENT_CERT")
    if not auth.private_key:
        missing.append("DY_PRIVATE_KEY")
    return missing


def _apply_cred(auth: ImAuth, cred: Dict[str, Any]) -> None:
    auth.ticket = str(cred.get("DY_TICKET") or "") or auth.ticket
    auth.ts_sign = str(cred.get("DY_TS_SIGN") or "") or auth.ts_sign
    auth.client_cert = str(cred.get("DY_CLIENT_CERT") or "") or auth.client_cert
    auth.private_key = str(cred.get("DY_PRIVATE_KEY") or "") or auth.private_key


def require_send_cred(auth: ImAuth) -> None:
    """发信需要 web_protect ticket + ECDSA 私钥。"""
    missing = _send_cred_missing(auth)
    if missing:
        raise RuntimeError(
            f"发信缺少 {', '.join(missing)}。"
            f"先运行: boss douyin grab-ticket [--headed]"
            f" → 写入 {CRED_PATH}"
        )


def ensure_send_cred(auth: ImAuth, *, headed: bool = False) -> None:
    """发信凭据：始终优先 <project>/douyin/im_cred.json。"""
    # 1) 每次发信前重新加载 im_cred.json（避免进程内过期 ticket）
    try:
        from .credentials import load_im_cred

        local = load_im_cred(sessionid=str(auth.cookie.get("sessionid") or ""))
        if local:
            _apply_cred(auth, local)
    except Exception:
        pass
    if not _send_cred_missing(auth):
        return

    # 2) 旧版 spider/js 凭据（导入到 im_cred.json 后复用）
    try:
        from .credentials import import_im_cred_from_spider, load_im_cred

        import_im_cred_from_spider()
        local = load_im_cred(sessionid=str(auth.cookie.get("sessionid") or ""))
        if local:
            _apply_cred(auth, local)
            if not _send_cred_missing(auth):
                print(f"[im] 已导入发信凭据 → {CRED_PATH}", file=sys.stderr)
                return
    except Exception:
        pass

    print("[im] 发信凭据缺失，用 cookie 打开抖音网页抓 ticket…", file=sys.stderr)
    import asyncio

    from .grab_ticket import grab
    from .credentials import load_douyin_cookie, save_im_cred

    try:
        cred = asyncio.run(grab(auth.cookie_str, headless=not headed))
    except Exception as exc:
        raise RuntimeError(
            f"用 cookie 自动抓 ticket 失败: {exc}。"
            "可手动: boss douyin grab-ticket --headed"
            "（需 uv sync --extra browser && uv run playwright install chromium）"
            f" → 写入 {CRED_PATH}"
        ) from exc
    _apply_cred(auth, cred)
    missing = _send_cred_missing(auth)
    if missing:
        raise RuntimeError(f"抓到的凭据不完整: {', '.join(missing)}（应写入 {CRED_PATH}）")
    try:
        active = load_douyin_cookie()
        if str(auth.cookie.get("sessionid") or "") == active.sessionid:
            account_name = active.name
        else:
            account_name = ""
    except Exception:
        account_name = ""
    save_im_cred(
        {
            "DY_TICKET": auth.ticket,
            "DY_TS_SIGN": auth.ts_sign,
            "DY_CLIENT_CERT": auth.client_cert,
            "DY_PRIVATE_KEY": auth.private_key,
        },
        account_name=account_name,
        sessionid=str(auth.cookie.get("sessionid") or ""),
        append=True,
    )
    print(f"[im] ticket 已写入 {CRED_PATH}", file=sys.stderr)


def _profile_summary(cookie: str) -> Dict[str, str]:
    client = DouyinClient(cookie=cookie)
    p = client.get_self_profile()
    u = p.get("user") if isinstance(p, dict) and p.get("user") else p
    if isinstance(u, dict) and "user" in u and isinstance(u.get("user"), dict):
        u = u["user"]
    if isinstance(u, dict) and not u.get("nickname") and u.get("user_info"):
        u = u["user_info"]
    if not isinstance(u, dict) or not any(u.get(k) for k in ("uid", "nickname", "unique_id")):
        return {}
    from boss_cli.douyin_web.payload import avatar_from_user

    return {
        "nickname": str(u.get("nickname") or ""),
        "unique_id": str(u.get("unique_id") or ""),
        "short_id": str(u.get("short_id") or ""),
        "uid": str(u.get("uid") or ""),
        "sec_uid": str(u.get("sec_uid") or u.get("sec_user_id") or ""),
        "avatar": avatar_from_user(u),
    }


def _uid_from_cookie_jar(jar: Dict[str, str]) -> str:
    for key in ("uid_tt", "login_uid", "passport_uid", "user_id"):
        val = str(jar.get(key) or "").strip().strip('"')
        if val.isdigit() and len(val) >= 5:
            return val
    return ""


def infer_self_uid(
    auth: ImAuth,
    *,
    convs: Optional[List[Dict[str, Any]]] = None,
) -> str:
    """Resolve current user uid when profile/self is blocked."""
    # 1) 扫码写入 / load_auth 注入的本地 uid（最可靠）
    cached = str(getattr(auth, "uid", "") or "").strip()
    if cached.isdigit() and len(cached) >= 5:
        return cached
    uid = _uid_from_cookie_jar(auth.cookie)
    if uid:
        return uid
    summary = {}
    try:
        summary = _profile_summary(auth.cookie_str)
    except Exception:
        summary = {}
    uid = str(summary.get("uid") or "").strip()
    if uid:
        return uid
    if convs is None:
        try:
            convs = list_conversations(auth, page_size=40, max_pages=1)
        except Exception:
            convs = []
    counts: Counter[str] = Counter()
    for conv in convs or []:
        parts = str(conv.get("conversation_id") or "").split(":")
        if len(parts) >= 4:
            counts[str(parts[2])] += 1
            counts[str(parts[3])] += 1
    if not counts:
        return ""
    ranked = counts.most_common(2)
    best_uid, best_n = ranked[0]
    # 单会话时两边各计 1，猜错会把「我」和对方互换 → 头像错乱 + 实时消息被当 foreign 丢掉
    if len(ranked) >= 2 and ranked[0][1] == ranked[1][1]:
        return ""
    if len(convs or []) >= 2 and best_n < len(convs or []):
        return ""
    return best_uid if best_uid.isdigit() else ""


def account_summary(auth: ImAuth) -> Dict[str, str]:
    """当前 cookie 账号资料摘要（profile 被风控时从 IM 会话推断 uid）。"""
    summary: Dict[str, str] = {}
    try:
        summary = _profile_summary(auth.cookie_str)
    except Exception:
        summary = {}
    cached = str(getattr(auth, "uid", "") or "").strip()
    if cached.isdigit() and len(cached) >= 5:
        summary["uid"] = cached
    if not summary.get("uid"):
        uid = infer_self_uid(auth)
        if uid:
            summary["uid"] = uid
    uid = str(summary.get("uid") or "").strip()
    if uid and not summary.get("nickname"):
        try:
            prof = resolve_user_profile(auth, uid)
            if prof.get("nickname"):
                summary["nickname"] = str(prof["nickname"])
            if prof.get("unique_id"):
                summary["unique_id"] = str(prof["unique_id"])
        except Exception:
            pass
    return summary


def resolve_auth_by_nick(nick: str) -> tuple[ImAuth, Dict[str, str]]:
    """按昵称 / 抖音号 / uid 在配置账号中匹配。"""
    from .credentials import load_douyin_cookie

    needle = (nick or "").strip().lower()
    if not needle:
        raise ValueError("empty nick")
    try:
        acc = load_douyin_cookie(account_name=nick)
        summary = _profile_summary(acc.cookie)
        keys = {
            summary.get("nickname", "").lower(),
            summary.get("unique_id", "").lower(),
            summary.get("short_id", "").lower(),
            summary.get("uid", "").lower(),
            acc.name.lower(),
        }
        if needle in keys or not nick:
            return load_auth(cookie=acc.cookie), summary
    except Exception as exc:
        raise RuntimeError(f"no dy cookie matched nick={nick!r}: {exc}") from exc
    raise RuntimeError(f"no dy cookie matched nick={nick!r}")


def _protobuf_headers(ua: str = DEFAULT_UA) -> Dict[str, str]:
    return {
        "user-agent": ua,
        "accept": "application/x-protobuf",
        "content-type": "application/x-protobuf",
        "cache-control": "no-cache",
        "pragma": "no-cache",
        "sec-ch-ua": '"Chromium";v="125", "Not.A/Brand";v="24", "Google Chrome";v="125"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"macOS"',
        "sec-fetch-dest": "empty",
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "same-site",
        "priority": "u=1, i",
        "accept-language": "zh-CN,zh;q=0.9,en;q=0.8",
        "referer": "https://www.douyin.com/",
        "origin": "https://www.douyin.com",
    }


# --- minimal protobuf encode/decode ---


def _enc_varint(n: int) -> bytes:
    n = int(n) & ((1 << 64) - 1)
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        out.append(b | (0x80 if n else 0))
        if not n:
            return bytes(out)


def _enc_key(field: int, wire: int) -> bytes:
    return _enc_varint((field << 3) | wire)


def _enc_bytes(field: int, data: bytes | str) -> bytes:
    if isinstance(data, str):
        data = data.encode("utf-8")
    return _enc_key(field, 2) + _enc_varint(len(data)) + data


def _enc_varint_field(field: int, n: int) -> bytes:
    return _enc_key(field, 0) + _enc_varint(n)


def _dec_varint(buf: bytes, i: int) -> tuple[int, int]:
    shift = 0
    n = 0
    while i < len(buf):
        b = buf[i]
        i += 1
        n |= (b & 0x7F) << shift
        if not (b & 0x80):
            return n, i
        shift += 7
    raise ValueError("truncated varint")


def _decode_fields(buf: bytes) -> Dict[int, List[Any]]:
    out: Dict[int, List[Any]] = {}
    i = 0
    while i < len(buf):
        key, i = _dec_varint(buf, i)
        field, wire = key >> 3, key & 7
        if wire == 0:
            val, i = _dec_varint(buf, i)
        elif wire == 2:
            ln, i = _dec_varint(buf, i)
            val = buf[i : i + ln]
            i += ln
        elif wire == 1:
            val = buf[i : i + 8]
            i += 8
        elif wire == 5:
            val = buf[i : i + 4]
            i += 4
        else:
            break
        out.setdefault(field, []).append(val)
    return out


def _avatar_url_from_user(user: Dict[str, Any]) -> str:
    from boss_cli.douyin_web.payload import avatar_from_user

    return avatar_from_user(user)


def _apply_user_dict(profile: Dict[str, Any], user: Dict[str, Any]) -> None:
    if not isinstance(user, dict):
        return
    nick = str(user.get("nickname") or user.get("display_name") or "").strip()
    if nick:
        profile["nickname"] = nick
    uid_val = str(user.get("unique_id") or user.get("short_id") or "").strip()
    if uid_val:
        profile["unique_id"] = uid_val
    sec = str(user.get("sec_uid") or user.get("sec_user_id") or "").strip()
    if sec:
        profile["sec_uid"] = sec
    avatar = _avatar_url_from_user(user)
    if avatar:
        profile["avatar"] = avatar


def resolve_user_profile(
    auth: ImAuth, uid: str, sec_sender: str = ""
) -> Dict[str, Any]:
    """uid / sec_uid → {uid, nickname, unique_id, sec_uid, avatar}。"""
    uid = str(uid or "").strip()
    if not uid:
        return {"uid": "", "nickname": "?", "unique_id": "", "sec_uid": "", "avatar": ""}
    cached = _user_cache.get(uid)
    sec_in = str(sec_sender or "").strip()
    # Reuse only complete profiles (nickname + avatar). Incomplete cache blocked avatar refresh.
    if (
        cached
        and cached.get("avatar")
        and cached.get("nickname")
        and cached.get("nickname") != uid
    ):
        if sec_in and not cached.get("sec_uid"):
            cached = {**cached, "sec_uid": sec_in}
            _user_cache[uid] = cached
        return cached
    profile: Dict[str, Any] = {
        "uid": uid,
        "nickname": (cached or {}).get("nickname") or uid,
        "unique_id": (cached or {}).get("unique_id") or "",
        "sec_uid": sec_in or str((cached or {}).get("sec_uid") or ""),
        "avatar": (cached or {}).get("avatar") or "",
    }
    sec = profile["sec_uid"]
    if sec:
        try:
            info = auth.client.get_user_info(sec)
            user = info.get("user") or info
            if isinstance(user, dict):
                _apply_user_dict(profile, user)
        except Exception:
            pass
    if not profile.get("unique_id") or profile.get("nickname") == uid or not profile.get("avatar"):
        try:
            found = resolve_peer_uid(auth, uid)
            if found.get("nickname"):
                profile["nickname"] = str(found["nickname"])
            if found.get("unique_id"):
                profile["unique_id"] = str(found["unique_id"])
            if found.get("avatar") and not profile.get("avatar"):
                profile["avatar"] = str(found["avatar"])
            if found.get("sec_uid") and not profile.get("sec_uid"):
                profile["sec_uid"] = str(found["sec_uid"])
            sec2 = str(found.get("sec_uid") or profile.get("sec_uid") or "")
            if sec2 and (not profile.get("avatar") or profile.get("nickname") == uid):
                try:
                    info = auth.client.get_user_info(sec2)
                    user = info.get("user") or info
                    if isinstance(user, dict):
                        _apply_user_dict(profile, user)
                except Exception:
                    pass
        except Exception:
            pass
    _user_cache[uid] = profile
    _nick_cache[uid] = profile["nickname"] or uid
    return profile


def resolve_sender_nickname(auth: ImAuth, sender: str, sec_sender: str = "") -> str:
    uid = str(sender or "").strip()
    if not uid:
        return "?"
    return resolve_user_profile(auth, uid, sec_sender).get("nickname") or uid


def peer_profile_for_conversation(
    auth: ImAuth,
    conversation_id: str,
    messages: Optional[List[Dict[str, Any]]] = None,
    *,
    sec_uid: str = "",
) -> Dict[str, str]:
    my_uid = ""
    try:
        my_uid = _self_uid(auth)
    except Exception:
        my_uid = str((account_summary(auth) or {}).get("uid") or "")
    try:
        peer_uid = peer_uid_from_conversation(conversation_id, my_uid)
    except Exception:
        peer_uid = ""
    sec = str(sec_uid or "").strip()
    # Prefer peer's own sec_sender from history (required for avatar/nickname).
    if not sec:
        for m in messages or []:
            if peer_uid and str(m.get("sender") or "") == peer_uid:
                sec = str(m.get("sec_sender") or "").strip()
                if sec:
                    break
    if not peer_uid:
        return {"uid": "", "nickname": "未知", "unique_id": "", "sec_uid": "", "avatar": ""}
    return resolve_user_profile(auth, peer_uid, sec)


def conversation_title(
    auth: ImAuth,
    conversation_id: str,
    messages: Optional[List[Dict[str, Any]]] = None,
) -> str:
    cid = str(conversation_id or "").strip()
    if not cid:
        return "未知会话"
    if cid in _conv_title_cache and not messages:
        return _conv_title_cache[cid]
    peer = peer_profile_for_conversation(auth, cid, messages)
    nick = peer.get("nickname") or peer.get("uid") or "未知"
    dyid = peer.get("unique_id") or peer.get("uid") or ""
    title = f"{nick}({dyid})" if dyid else str(nick)
    _conv_title_cache[cid] = title
    return title


def conversation_filename(peer: Dict[str, Any]) -> str:
    nick = str(peer.get("nickname") or "unknown")
    dyid = str(peer.get("unique_id") or peer.get("uid") or "uid")
    safe = re.sub(r'[\\/:*?"<>|\s]+', "_", f"{nick}_{dyid}").strip("._") or "unknown"
    return safe + ".json"


def sender_label(auth: ImAuth, m: Dict[str, Any]) -> str:
    uid = str(m.get("sender") or "")
    profile = resolve_user_profile(auth, uid, str(m.get("sec_sender") or ""))
    nick = profile.get("nickname") or uid
    dyid = profile.get("unique_id") or uid
    if nick and dyid and nick != dyid:
        return f"{nick}({dyid})"
    return nick or dyid or "?"


def _build_request_envelope(
    auth: ImAuth,
    cmd: int,
    body_field: int,
    body_inner: bytes,
    *,
    request_sign: str = "",
) -> bytes:
    """通用 imapi Request（与 DouYin_Spider ProtoBuilder 字段对齐）。"""
    body = _enc_bytes(body_field, body_inner)
    parts = [
        _enc_varint_field(1, int(cmd)),
        _enc_varint_field(2, random.randint(10000, 20000)),
        _enc_bytes(3, "1.1.3"),
        _enc_bytes(4, auth.token),
        _enc_varint_field(5, 3),
        _enc_varint_field(6, 0),
        _enc_bytes(7, "5fa6ff1:Detached"),
        _enc_bytes(8, body),
        _enc_bytes(9, "0"),
        _enc_bytes(11, "douyin_pc"),
        _enc_varint_field(18, 4),
        _enc_bytes(21, "douyin_web"),
        _enc_bytes(22, "web_sdk"),
    ]
    if auth.ts_sign:
        parts.append(_enc_bytes(23, auth.ts_sign))
    if auth.client_cert:
        parts.append(
            _enc_bytes(24, base64.b64encode(auth.client_cert.encode("utf-8")).decode())
        )
    if request_sign:
        parts.append(_enc_bytes(25, request_sign))
    return b"".join(parts)


def _build_get_by_conversation_bytes(
    auth: ImAuth,
    conversation_id: str,
    conversation_short_id: int,
    *,
    limit: int = 30,
    direction: int = 1,
    anchor_index: int = 0,
) -> bytes:
    body301 = b"".join(
        [
            _enc_bytes(1, conversation_id),
            _enc_varint_field(2, 1),
            _enc_varint_field(3, int(conversation_short_id)),
            _enc_varint_field(4, int(direction)),
            _enc_varint_field(5, int(anchor_index)),
            _enc_varint_field(6, int(limit)),
        ]
    )
    return _build_request_envelope(auth, 301, 301, body301)


def _build_get_conversation_list_bytes(
    auth: ImAuth,
    *,
    cursor: int = 0,
    limit: int = 50,
) -> bytes:
    body200 = b"".join(
        [
            _enc_varint_field(1, int(cursor)),
            _enc_varint_field(2, int(limit)),
        ]
    )
    return _build_request_envelope(auth, 200, 200, body200)


def _as_int(v: Any, default: int = 0) -> int:
    try:
        if v is None or v == "":
            return default
        if isinstance(v, (bytes, bytearray)):
            text = bytes(v).decode("utf-8", "replace").strip()
            return int(text) if text else default
        return int(v)
    except (TypeError, ValueError):
        return default


def _guess_unix_ms(n: int) -> int:
    """把秒/毫秒/微秒猜成 unix 毫秒；对不上则 0。"""
    try:
        n = int(n)
    except (TypeError, ValueError):
        return 0
    if n <= 0:
        return 0
    if n >= 10**16:  # ns
        n //= 10**6
    elif n >= 10**14:  # us
        n //= 10**3
    elif n < 10**11:  # seconds
        n *= 1000
    # 2001-01-01 .. 2035-01-01
    if 978307200000 <= n <= 2051222400000:
        return n
    return 0


def _format_chat_time(ms: int) -> str:
    if not ms:
        return ""
    try:
        return datetime.fromtimestamp(ms / 1000.0).strftime("%Y-%m-%d %H:%M:%S")
    except (OSError, OverflowError, ValueError):
        return ""


def _message_create_time_ms(fields: Dict[int, List[Any]]) -> int:
    skip = {1, 2, 3, 4, 5, 6, 7, 8, 14}
    for f, vals in fields.items():
        if f in skip:
            continue
        for v in vals:
            ms = _guess_unix_ms(_as_int(v, 0))
            if ms:
                return ms
    return 0


def _generate_req_sign(payload: Any, private_key: str) -> str:
    """bd-ticket-guard ECDSA req_sign（DER + base64）。"""
    from ecdsa import NIST256p, SigningKey
    from ecdsa.util import sigencode_der

    if isinstance(payload, (dict, list)):
        payload = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    if "-----BEGIN" in private_key:
        sk = SigningKey.from_pem(private_key)
    else:
        sk = SigningKey.from_string(bytes.fromhex(private_key), curve=NIST256p)
    sig = sk.sign(payload.encode("utf-8"), hashfunc=hashlib.sha256, sigencode=sigencode_der)
    return base64.b64encode(sig).decode()


def _ms_token(auth: ImAuth, length: int = 107) -> str:
    existing = auth.cookie.get("msToken") or ""
    if existing:
        return existing
    alphabet = "ABCDEFGHIGKLMNOPQRSTUVWXYZabcdefghigklmnopqrstuvwxyz0123456789="
    return "".join(random.choice(alphabet) for _ in range(length))


def _self_uid(auth: ImAuth) -> str:
    uid = infer_self_uid(auth)
    if uid:
        return uid
    summary = account_summary(auth)
    uid = str(summary.get("uid") or "").strip()
    if not uid:
        raise RuntimeError("无法解析当前账号 uid（cookie 可能失效）")
    return uid


def peer_uid_from_conversation(conversation_id: str, my_uid: str) -> str:
    """从 `0:1:{a}:{b}` 里取出对方 uid。"""
    parts = (conversation_id or "").split(":")
    if len(parts) < 4:
        raise ValueError(f"bad conversation_id={conversation_id!r}")
    a, b = parts[2], parts[3]
    my = str(my_uid)
    if a == my:
        return b
    if b == my:
        return a
    # 默认会话可能与 cookie 账号不一致时：取第二个（对方）
    return b


def resolve_peer_uid(auth: ImAuth, target: str) -> Dict[str, str]:
    """uid / 主页 URL / sec_uid / 抖音号 → 对方 uid（统一按抖音号搜索，不按昵称）。

    返回 {"uid", "nickname", "unique_id", "sec_uid"}。
    """
    text = (target or "").strip()
    if not text:
        raise ValueError("empty peer target")

    def _from_user(user: Dict[str, Any], sec: str = "") -> Dict[str, str]:
        uid = str(user.get("uid") or "").strip()
        if not uid:
            raise RuntimeError(f"用户无 uid: {text}")
        return {
            "uid": uid,
            "nickname": str(user.get("nickname") or user.get("display_name") or ""),
            "unique_id": str(user.get("unique_id") or user.get("short_id") or ""),
            "sec_uid": str(sec or user.get("sec_uid") or user.get("sec_user_id") or ""),
            "avatar": _avatar_url_from_user(user),
        }

    # 纯数字 = 直接视为 uid 直发，避免触发用户搜索（搜索频控 2484）
    if text.isdigit():
        return {"uid": text, "nickname": "", "unique_id": "", "sec_uid": ""}

    # 主页链接 / sec_uid
    if (
        text.startswith("http")
        or "douyin.com" in text
        or text.startswith("MS4wLjABAAAA")
    ):
        sec = auth.client.resolve_creator_sec_uid(text)
        info = auth.client.get_user_info(sec)
        user = info.get("user") or info
        if not isinstance(user, dict):
            raise RuntimeError(f"无法拉取用户资料: {text}")
        return _from_user(user, sec)

    # 抖音号（统一按抖音号 unique_id 搜索补头像/昵称，不再按昵称模糊匹配）
    try:
        bundle = auth.client.get_profile_bundle(text)
        creators = bundle.get("creators") or []
        if creators:
            chosen = creators[0][0]
            uid = str(chosen.get("uid") or "").strip()
            if uid:
                return {
                    "uid": uid,
                    "nickname": str(chosen.get("display_name") or chosen.get("nickname") or ""),
                    "unique_id": str(chosen.get("unique_id") or ""),
                    "sec_uid": str(chosen.get("sec_uid") or chosen.get("sec_user_id") or ""),
                    "avatar": _avatar_url_from_user(chosen),
                }
    except Exception as exc:
        if text.isdigit():
            return {"uid": text, "nickname": "", "unique_id": "", "sec_uid": ""}
        raise RuntimeError(
            f"无法解析对方「{text}」（抖音号/昵称搜索失败）。"
            "可改用主页 URL，或直接传 uid。"
            f" 原始错误: {exc}"
        ) from exc

    if text.isdigit():
        return {"uid": text, "nickname": "", "unique_id": "", "sec_uid": ""}
    raise RuntimeError(f"未找到用户: {text}")


def create_conversation(auth: ImAuth, to_user_id: int | str) -> Tuple[str, int, str]:
    """建/取单聊会话 → (conversation_id, conversation_short_id, ticket)。"""
    ensure_send_cred(auth)
    to_id = int(to_user_id)
    my_id = int(_self_uid(auth))
    body609 = b"".join(
        [
            _enc_varint_field(1, 1),
            _enc_varint_field(2, to_id),
            _enc_varint_field(2, my_id),
        ]
    )
    sign = _generate_req_sign(
        {
            "sign_data": f"avatar_url=&idempotent_id=&name=&participants={to_id},{my_id}",
            "certType": "cookie",
            "scene": "web_protect",
        },
        auth.private_key,
    )
    payload = _build_request_envelope(auth, 609, 609, body609, request_sign=sign)
    headers = _protobuf_headers(auth.client.user_agent)
    resp = requests.post(
        CREATE_CONVERSATION,
        headers=headers,
        cookies=auth.cookie,
        data=payload,
        verify=False,
        timeout=30,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"create HTTP {resp.status_code}: {resp.content[:200]!r}")

    top = _decode_fields(resp.content)
    msg = (top.get(4) or [b""])[0]
    if isinstance(msg, bytes):
        msg = msg.decode("utf-8", "replace")
    body_raw = (top.get(6) or [b""])[0]
    if not isinstance(body_raw, (bytes, bytearray)):
        raise RuntimeError(f"create: empty body message={msg!r}")
    body = _decode_fields(bytes(body_raw))
    list_raw = (body.get(609) or [b""])[0]
    if not isinstance(list_raw, (bytes, bytearray)) or not list_raw:
        err = (top.get(3) or [b""])[0]
        if isinstance(err, bytes):
            err = err.decode("utf-8", "replace")
        raise RuntimeError(f"create failed message={msg!r} err={err!r}")

    info_list = _decode_fields(bytes(list_raw))
    infos = info_list.get(1) or []
    if not infos:
        raise RuntimeError(f"create: no conversation_info_list message={msg!r}")
    info = _decode_fields(bytes(infos[0])) if isinstance(infos[0], (bytes, bytearray)) else {}

    def g(f: int, default: Any = ""):
        vals = info.get(f) or []
        if not vals:
            return default
        v = vals[0]
        if isinstance(v, bytes):
            return v.decode("utf-8", "replace")
        return v

    cid = str(g(1, ""))
    cshort = int(g(2, 0) or 0)
    ticket = str(g(4, ""))
    if not cid or not cshort or not ticket:
        raise RuntimeError(f"create incomplete: id={cid} short={cshort} ticket={bool(ticket)}")
    return cid, cshort, ticket


def send_text(
    auth: ImAuth,
    text: str,
    *,
    conversation_id: str = "",
    conversation_short_id: int = 0,
    conversation_ticket: str = "",
    to_user_id: str = "",
    headed: bool = False,
) -> Dict[str, Any]:
    """发送文本私信（message_type=7）。

    to_user_id 可为 uid / 抖音号 / 昵称 / 主页 URL / sec_uid。
    优先用已有会话；无 ticket 时会 create_conversation 取票。
    缺 web_protect 凭据时用 cookie 自动抓。
    """
    ensure_send_cred(auth, headed=headed)
    content_text = (text or "").strip()
    if not content_text:
        raise ValueError("empty text")

    cid = (conversation_id or "").strip()
    cshort = int(conversation_short_id or 0)
    ticket = (conversation_ticket or "").strip()
    to_raw = str(to_user_id or "").strip()
    peer: Dict[str, str] = {}

    if not ticket or not cid or not cshort:
        if to_raw:
            peer = resolve_peer_uid(auth, to_raw)
            to_uid = peer["uid"]
        else:
            if not cid:
                cid = DEFAULT_CONVERSATION_ID
                cshort = cshort or DEFAULT_CONVERSATION_SHORT_ID
            to_uid = peer_uid_from_conversation(cid, _self_uid(auth))
            peer = {"uid": to_uid, "nickname": "", "unique_id": "", "sec_uid": ""}
        new_cid, new_short, ticket = create_conversation(auth, to_uid)
        cid, cshort = new_cid, new_short
    elif to_raw:
        peer = resolve_peer_uid(auth, to_raw)

    client_message_id = str(uuid.uuid4())
    msg_content = {
        "mention_users": [],
        "aweType": 700,
        "richTextInfos": [],
        "text": content_text,
    }
    content_json = json.dumps(msg_content, ensure_ascii=False, separators=(",", ":"))
    stime = str(int(round(time.time() * 1000)))

    def _ext(key: str, value: str) -> bytes:
        return _enc_bytes(5, _enc_bytes(1, key) + _enc_bytes(2, value))

    body100 = b"".join(
        [
            _enc_bytes(1, cid),
            _enc_varint_field(2, 1),
            _enc_varint_field(3, int(cshort)),
            _enc_bytes(4, content_json),
            _ext("s:client_message_id", client_message_id),
            _ext("s:stime", stime),
            _ext("s:mentioned_users", ""),
            _enc_varint_field(6, 7),
            _enc_bytes(7, ticket),
            _enc_bytes(8, client_message_id),
        ]
    )
    sign = _generate_req_sign(
        {
            "sign_data": (
                f"content={content_json}"
                f"&conversation_id={cid}"
                f"&conversation_short_id={cshort}"
            ),
            "certType": "cookie",
            "scene": "web_protect",
        },
        auth.private_key,
    )
    payload = _build_request_envelope(auth, 100, 100, body100, request_sign=sign)

    fp = auth.cookie.get("s_v_web_id") or ""
    params: Dict[str, str] = {
        "verifyFp": fp,
        "fp": fp,
        "msToken": _ms_token(auth),
    }
    query = "&".join(f"{k}={quote(str(v), safe='')}" for k, v in params.items())
    params["a_bogus"] = get_a_bogus(query, auth.client.user_agent)

    headers = _protobuf_headers(auth.client.user_agent)
    resp = requests.post(
        SEND_MESSAGE,
        params=params,
        headers=headers,
        cookies=auth.cookie,
        data=payload,
        verify=False,
        timeout=30,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"send HTTP {resp.status_code}: {resp.content[:200]!r}")

    parsed = _parse_send_response(resp.content)
    # 顶层常返回 "OK"，真正成败在 body100；7911 等风控会假成功。
    ok = bool(parsed.get("ok"))
    out: Dict[str, Any] = {
        "ok": ok,
        "message": str(parsed.get("message") or ""),
        "error_desc": str(parsed.get("error_desc") or ""),
        "status_code": parsed.get("status_code"),
        "conversation_id": cid,
        "conversation_short_id": int(cshort),
        "client_message_id": client_message_id,
        "server_message_id": str(parsed.get("server_message_id") or ""),
        "text": content_text,
    }
    if peer:
        out["to"] = peer

    # 网关 OK 后尽量拉历史核对是否落库。历史接口偶发延迟/正文是 JSON，
    # 对不上时只记警告，不再把 ok 打成 False（否则会出现「对方已收到但仍刷
    # ticket 不同源」的误报，自动回复也会被当成发送失败）。
    if ok:
        delivered = False
        me_uid = _self_uid(auth)
        needle = str(content_text or "").strip()
        try:
            for attempt in range(3):
                time.sleep(0.35 + attempt * 0.35)
                recent = get_messages_by_conversation(auth, cid, int(cshort), limit=20)
                now_ms = time.time() * 1000
                for m in recent:
                    if me_uid and str(m.get("sender") or "") != me_uid:
                        continue
                    body = message_body(auth, m).strip()
                    raw_content = str(m.get("content") or "")
                    matched = False
                    if needle and (needle == body or needle in body or needle in raw_content):
                        matched = True
                    elif client_message_id and client_message_id in raw_content:
                        matched = True
                    if not matched:
                        continue
                    cts = int(m.get("create_time_ms") or 0)
                    if cts and abs(now_ms - cts) > 180_000:
                        continue
                    delivered = True
                    if not out.get("server_message_id"):
                        out["server_message_id"] = str(m.get("server_message_id") or "")
                    break
                if delivered:
                    break
            out["delivered"] = delivered
            if not delivered:
                out["verify"] = (
                    "网关 OK，但短时间内未在会话历史核对到正文"
                    "（多为历史接口延迟，不一定是 ticket 不同源）"
                )
                logger.info(
                    "send verify soft-miss cid=%s text=%r",
                    cid,
                    needle[:40],
                )
        except Exception as exc:
            out["delivered"] = None
            out["verify"] = f"发送后未能核对历史: {exc}"
    return out


def _as_text(v: Any) -> str:
    if isinstance(v, (bytes, bytearray)):
        return bytes(v).decode("utf-8", "replace")
    if v is None:
        return ""
    return str(v)


def _tips_from_status_payload(data: Dict[str, Any]) -> str:
    """从 send body 里的 status_msg JSON 抽出可读提示。"""
    tips = str(data.get("tips") or "").strip()
    if tips:
        return tips
    status_msg = data.get("status_msg")
    if isinstance(status_msg, dict):
        content = status_msg.get("msg_content")
        if isinstance(content, dict):
            tips = str(content.get("tips") or "").strip()
            if tips:
                return tips
        tips = str(status_msg.get("tips") or "").strip()
        if tips:
            return tips
    return ""


def _parse_send_response(resp_content: bytes) -> Dict[str, Any]:
    """解析 message/send 响应。

    信封 field4=='OK' 不够：body(cmd100) 里可能带 status_code=7911
    （「重新登录后可以正常使用私信」），消息实际未投递。
    """
    top = _decode_fields(resp_content)
    msg = _as_text((top.get(4) or [b""])[0])
    err_top = (top.get(3) or [None])[0]
    err_desc = _as_text(err_top) if not isinstance(err_top, int) else ""
    ok = msg == "OK"
    status_code: Any = None
    server_message_id = ""

    body_raw = (top.get(6) or [b""])[0]
    if isinstance(body_raw, (bytes, bytearray)) and body_raw:
        body = _decode_fields(bytes(body_raw))
        inner_raw = (body.get(100) or [b""])[0]
        if isinstance(inner_raw, (bytes, bytearray)) and inner_raw:
            inner = _decode_fields(bytes(inner_raw))
            check = (inner.get(5) or [None])[0]
            payload = (inner.get(6) or [b""])[0]
            if isinstance(payload, (bytes, bytearray)) and payload:
                text = ""
                try:
                    text = bytes(payload).decode("utf-8")
                except Exception:
                    text = ""
                if text.startswith("{"):
                    try:
                        data = json.loads(text)
                    except json.JSONDecodeError:
                        data = None
                    if isinstance(data, dict) and "status_code" in data:
                        status_code = data.get("status_code")
                        try:
                            code_i = int(status_code)
                        except (TypeError, ValueError):
                            code_i = -1
                        if code_i != 0:
                            ok = False
                            tip = _tips_from_status_payload(data)
                            if tip:
                                err_desc = tip
                            else:
                                err_desc = f"发送被拒绝 status_code={status_code}"
                            if code_i == 7911 or "重新登录" in err_desc:
                                err_desc = (
                                    f"{err_desc}。"
                                    "请更新 cookie 后执行: boss douyin grab-ticket --headed"
                                )
                else:
                    # 成功时 field6 常为 MessageBody（含 server_message_id=field3）
                    try:
                        mb = _decode_fields(bytes(payload))
                        sid = _as_text((mb.get(3) or [b""])[0])
                        if sid and sid.isdigit():
                            server_message_id = sid
                    except Exception:
                        pass
            # check!=0 且没有 server id / 已判失败时，避免假成功
            if ok and not server_message_id and check not in (None, 0, 1):
                ok = False
                if not err_desc:
                    err_desc = f"发送未确认(check={check})"

    if not ok and not err_desc:
        err_desc = msg if msg and msg != "OK" else "发送失败"
    return {
        "ok": ok,
        "message": msg,
        "error_desc": err_desc,
        "status_code": status_code,
        "server_message_id": server_message_id,
    }


def clone_auth(auth: ImAuth) -> ImAuth:
    """线程内独立 ImAuth（不共享 DouyinClient session）。"""
    return ImAuth(
        cookie=dict(auth.cookie),
        cookie_str=auth.cookie_str,
        ticket=auth.ticket,
        ts_sign=auth.ts_sign,
        client_cert=auth.client_cert,
        private_key=auth.private_key,
    )


def send_many(
    auth: ImAuth,
    text: str,
    targets: List[str],
    *,
    workers: int = 0,
    headed: bool = False,
) -> List[Dict[str, Any]]:
    """并发给多个抖音号发同一段文本。workers<=0 时按目标数（上限 8）。"""
    from concurrent.futures import ThreadPoolExecutor, as_completed

    ensure_send_cred(auth, headed=headed)
    content = (text or "").strip()
    if not content:
        raise ValueError("empty text")
    uniq: List[str] = []
    for t in targets:
        s = str(t or "").strip()
        if s and s not in uniq:
            uniq.append(s)
    if not uniq:
        raise ValueError("empty targets")

    n = len(uniq)
    pool = workers if workers and workers > 0 else min(8, n)
    pool = max(1, min(pool, n))

    def _one(target: str) -> Dict[str, Any]:
        local = clone_auth(auth)
        try:
            result = send_text(
                local,
                content,
                conversation_id="",
                conversation_short_id=0,
                to_user_id=target,
                headed=False,
            )
            result["target"] = target
            return result
        except Exception as exc:
            return {
                "ok": False,
                "target": target,
                "error": str(exc),
                "text": content,
            }

    print(f"[im] send {n} targets workers={pool}", file=sys.stderr)
    out: List[Dict[str, Any]] = [None] * n  # type: ignore
    with ThreadPoolExecutor(max_workers=pool) as ex:
        futs = {ex.submit(_one, t): i for i, t in enumerate(uniq)}
        for fut in as_completed(futs):
            i = futs[fut]
            row = fut.result()
            out[i] = row
            tag = "ok" if row.get("ok") else "fail"
            peer = (row.get("to") or {}).get("unique_id") or row.get("target")
            print(
                f"[im] [{tag}] {peer}: {row.get('message') or row.get('error')}",
                file=sys.stderr,
            )
    return out


def get_messages_by_conversation(
    auth: ImAuth,
    conversation_id: str,
    conversation_short_id: int,
    *,
    limit: int = 30,
    anchor_index: int = 0,
) -> List[Dict[str, Any]]:
    if not auth.token:
        raise RuntimeError("missing sessionid/ticket")

    payload = _build_get_by_conversation_bytes(
        auth,
        conversation_id,
        int(conversation_short_id),
        limit=limit,
        anchor_index=anchor_index,
    )
    headers = _protobuf_headers(auth.client.user_agent)
    resp = requests.post(
        GET_BY_CONVERSATION,
        headers=headers,
        cookies=auth.cookie,
        data=payload,
        verify=False,
        timeout=30,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"HTTP {resp.status_code}: {resp.content[:200]!r}")

    top = _decode_fields(resp.content)
    body_raw = (top.get(6) or [b""])[0]
    if not isinstance(body_raw, (bytes, bytearray)):
        return []
    body = _decode_fields(bytes(body_raw))
    conv_raw = (body.get(301) or [b""])[0]
    if not isinstance(conv_raw, (bytes, bytearray)) or not conv_raw:
        err = (top.get(3) or top.get(4) or [b""])[0]
        if isinstance(err, bytes):
            err = err.decode("utf-8", "replace")
        raise RuntimeError(f"no messages body; err={err!r} fields={list(top)}")

    conv = _decode_fields(bytes(conv_raw))
    msgs_raw = conv.get(1) or []
    out: List[Dict[str, Any]] = []
    for raw in msgs_raw:
        if not isinstance(raw, (bytes, bytearray)):
            continue
        m = _decode_fields(bytes(raw))

        def g(f: int, default: Any = ""):
            vals = m.get(f) or []
            if not vals:
                return default
            v = vals[0]
            if isinstance(v, bytes):
                return v.decode("utf-8", "replace")
            return v

        content = g(8, "")
        create_ms = _message_create_time_ms(m)
        if not create_ms and isinstance(content, str) and content.startswith("{"):
            try:
                obj = json.loads(content)
                if isinstance(obj, dict):
                    create_ms = _guess_unix_ms(
                        obj.get("create_time") or obj.get("createTime") or 0
                    )
            except Exception:
                create_ms = create_ms
        out.append(
            {
                "conversation_id": str(g(1, "")),
                "conversation_type": int(g(2, 0) or 0),
                "server_message_id": str(g(3, "")),
                "index_in_conversation": str(g(4, "")),
                "conversation_short_id": str(g(5, "")),
                "message_type": int(g(6, 0) or 0),
                "sender": str(g(7, "")),
                "content": content if isinstance(content, str) else str(content),
                "sec_sender": str(g(14, "")),
                "create_time_ms": create_ms,
            }
        )
    return out


def list_conversations(
    auth: ImAuth,
    *,
    page_size: int = 50,
    max_pages: int = 10,
) -> List[Dict[str, Any]]:
    """收件箱会话列表（cmd=200）。按 conversation_id 去重。"""
    if not auth.token:
        raise RuntimeError("missing sessionid/ticket")

    headers = _protobuf_headers(auth.client.user_agent)
    ordered: List[Dict[str, Any]] = []
    seen_cids: Set[str] = set()
    cursor = 0

    for _ in range(max(1, int(max_pages))):
        payload = _build_get_conversation_list_bytes(
            auth, cursor=cursor, limit=max(1, int(page_size))
        )
        resp = requests.post(
            GET_CONVERSATION_LIST,
            headers=headers,
            cookies=auth.cookie,
            data=payload,
            verify=False,
            timeout=30,
        )
        if resp.status_code != 200:
            raise RuntimeError(f"HTTP {resp.status_code}: {resp.content[:200]!r}")

        top = _decode_fields(resp.content)
        body_raw = (top.get(6) or [b""])[0]
        if not isinstance(body_raw, (bytes, bytearray)):
            break
        body = _decode_fields(bytes(body_raw))
        inner_raw = (body.get(200) or [b""])[0]
        if not isinstance(inner_raw, (bytes, bytearray)) or not inner_raw:
            err = (top.get(3) or top.get(4) or [b""])[0]
            if isinstance(err, bytes):
                err = err.decode("utf-8", "replace")
            raise RuntimeError(f"no conversation list body; err={err!r} fields={list(top)}")

        inner = _decode_fields(bytes(inner_raw))
        for raw in inner.get(1) or []:
            if not isinstance(raw, (bytes, bytearray)):
                continue
            m = _decode_fields(bytes(raw))

            def g(f: int, default: Any = ""):
                vals = m.get(f) or []
                if not vals:
                    return default
                v = vals[0]
                if isinstance(v, bytes):
                    return v.decode("utf-8", "replace")
                return v

            cid = str(g(1, "")).strip()
            if not cid or cid in seen_cids:
                continue
            seen_cids.add(cid)
            ordered.append(
                {
                    "conversation_id": cid,
                    "conversation_type": _as_int(g(2, 0)),
                    "conversation_short_id": _as_int(g(5, 0)),
                    "last_message_type": _as_int(g(6, 0)),
                    "last_sender": str(g(7, "")),
                }
            )

        has_more = _as_int((inner.get(3) or [0])[0]) == 1
        next_cursor = _as_int((inner.get(2) or inner.get(5) or [0])[0])
        if not has_more or not next_cursor or next_cursor == cursor:
            break
        cursor = next_cursor

    return ordered


def parse_media_urls(content: str) -> Dict[str, Any]:
    if not content:
        return {"raw": "", "urls": []}
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        return {"raw": content, "urls": []}
    urls: List[str] = []
    # 图片/语音/表情：优先 origin → large → medium → thumb
    for key in (
        "resource_url",
        "url",
        "cover_url",
        "play_url",
        "audio_url",
        "emoji_url",
        "gif_url",
        "display_url",
    ):
        obj = data.get(key)
        if isinstance(obj, dict):
            for k in (
                "origin_url_list",
                "large_url_list",
                "url_list",
                "medium_url_list",
                "thumb_url_list",
            ):
                for u in obj.get(k) or []:
                    if isinstance(u, str) and u.startswith("http") and u not in urls:
                        urls.append(u)
        elif isinstance(obj, str) and obj.startswith("http"):
            urls.append(obj)
    if not urls:
        stack: List[Any] = [data]
        while stack and len(urls) < 8:
            obj = stack.pop()
            if isinstance(obj, str):
                if obj.startswith("http") and obj not in urls:
                    urls.append(obj)
            elif isinstance(obj, dict):
                stack.extend(obj.values())
            elif isinstance(obj, list):
                stack.extend(obj)
    return {"raw": data, "urls": urls, "aweType": data.get("aweType")}


def _extract_share_item_id(raw: Any) -> str:
    if not isinstance(raw, dict):
        return ""
    for k in ("itemId", "item_id", "aweme_id", "awemeId", "video_id"):
        v = raw.get(k)
        if v not in (None, "", 0, "0"):
            return str(v)
    share_id = str(raw.get("share_id") or "")
    if "_" in share_id:
        tail = share_id.rsplit("_", 1)[-1]
        if tail.isdigit() and len(tail) >= 10:
            return tail
    return ""


def _format_share_line(base: str, raw: Any) -> Optional[str]:
    """视频/图文分享：输出可点开的 douyin 链接。"""
    if not isinstance(raw, dict):
        return None
    item = _extract_share_item_id(raw)
    if not item:
        return None
    name = str(raw.get("content_title") or raw.get("content_name") or "").strip()
    url = f"https://www.douyin.com/video/{item}"
    aweme_type = raw.get("awemeType")
    kind = "分享图文" if aweme_type in (68, "68") else "分享视频"
    if name:
        return f"{base}{kind}:{name} {url}"
    return f"{base}{kind}:{url}"


def message_body(auth: ImAuth, m: Dict[str, Any]) -> str:
    """微信气泡正文（不含会话/发送者前缀）。"""
    mt = int(m.get("message_type") or 0)
    content = m.get("content") or ""
    media = parse_media_urls(content)
    raw = media.get("raw") if isinstance(media.get("raw"), dict) else {}

    if mt == 7:
        try:
            return str(json.loads(content).get("text") or "")
        except Exception:
            return str(content)[:120]
    if mt == 5:
        url = (media.get("urls") or [""])[0]
        return f"[表情] {url}" if url else "[表情]"
    if mt in (8, 77) or raw.get("aweType") == 800 or _extract_share_item_id(raw):
        share = _format_share_line("", raw)
        if share:
            return share.lstrip()
        if mt in (8, 77):
            return "[分享]"
    if mt == 17:
        url = (media.get("urls") or [""])[0]
        return f"[语音] {url}" if url else "[语音]"
    if mt == 27:
        urls = media.get("urls") or []
        if urls:
            return f"[图片] {urls[0]}"
        return "[图片]"
    if mt == 50001:
        try:
            return f"[已读] {json.loads(content).get('read_index')}"
        except Exception:
            return "[已读]"
    if mt == 105:
        share = _format_share_line("", raw)
        return share.lstrip() if share else "[分享视频]"
    if mt == 110:
        share = _format_share_line("", raw)
        return share.lstrip() if share else "[分享]"
    return str(content)[:160]


def format_im_message(auth: ImAuth, m: Dict[str, Any]) -> str:
    mt = int(m.get("message_type") or 0)
    title = conversation_title(auth, str(m.get("conversation_id") or ""), [m])
    when = _format_chat_time(_as_int(m.get("create_time_ms")))
    prefix = f"[{when}] " if when else ""
    return (
        f"{prefix}【会话:{title}】【来自:{sender_label(auth, m)}】【type={mt}】"
        f"{message_body(auth, m)}"
    )


def format_chat_line(item: Dict[str, Any]) -> str:
    """终端版微信气泡：日期分割后按时间从上到下。"""
    when = str(item.get("time") or "")
    clock = when[11:16] if len(when) >= 16 else when
    name = str(item.get("from") or "")
    text = str(item.get("text") or "")
    stamp = f"{clock}  " if clock else ""
    return f"{stamp}{name}: {text}"


def sort_messages(msgs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return sorted(
        msgs,
        key=lambda m: (
            _as_int(m.get("create_time_ms")),
            _as_int(m.get("index_in_conversation")),
        ),
    )


def build_chat_dump(
    auth: ImAuth,
    conversation_id: str,
    conversation_short_id: int,
    msgs: List[Dict[str, Any]],
    *,
    account: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """单会话：微信时间线 JSON。"""
    me = dict(account or {})
    if not me:
        me = account_summary(auth) or {}
    my_uid = str(me.get("uid") or "")
    if my_uid:
        _user_cache[my_uid] = {
            "uid": my_uid,
            "nickname": str(me.get("nickname") or ""),
            "unique_id": str(me.get("unique_id") or ""),
            "sec_uid": "",
        }
    peer = peer_profile_for_conversation(auth, conversation_id, msgs)
    title = conversation_title(auth, conversation_id, msgs)
    chat: List[Dict[str, Any]] = []
    for m in sort_messages(msgs):
        mt = int(m.get("message_type") or 0)
        if mt == 50001:
            continue
        sender = str(m.get("sender") or "")
        is_me = bool(my_uid) and sender == my_uid
        sender_prof = resolve_user_profile(auth, sender, str(m.get("sec_sender") or ""))
        chat.append(
            {
                "time": _format_chat_time(_as_int(m.get("create_time_ms"))),
                "from": "我" if is_me else (sender_prof.get("nickname") or sender or "?"),
                "side": "right" if is_me else "left",
                "text": message_body(auth, m),
                "type": mt,
            }
        )
    return {
        "title": title,
        "peer": {
            "nickname": peer.get("nickname") or "",
            "unique_id": peer.get("unique_id") or "",
            "uid": peer.get("uid") or "",
        },
        "me": {
            "nickname": me.get("nickname") or "",
            "unique_id": me.get("unique_id") or "",
            "uid": my_uid,
        },
        "conversation_id": conversation_id,
        "conversation_short_id": int(conversation_short_id or 0),
        "message_count": len(chat),
        "messages": chat,
    }


def poll_new_messages(
    auth: ImAuth,
    conversation_id: str,
    conversation_short_id: int,
    seen: Set[str],
    *,
    limit: int = 30,
    seed_only: bool = False,
) -> List[Dict[str, Any]]:
    msgs = get_messages_by_conversation(
        auth, conversation_id, int(conversation_short_id), limit=limit
    )
    fresh: List[Dict[str, Any]] = []
    for m in msgs:
        sid = str(m.get("server_message_id") or "")
        if not sid:
            continue
        if sid in seen:
            continue
        seen.add(sid)
        if not seed_only:
            fresh.append(m)
    return fresh


def dump_conversation(
    auth: ImAuth,
    conversation_id: str,
    conversation_short_id: int,
    *,
    limit: int = 40,
) -> Dict[str, Any]:
    msgs = get_messages_by_conversation(
        auth, conversation_id, int(conversation_short_id), limit=limit
    )
    account: Dict[str, Any] = {}
    try:
        user = auth.client.get_self_profile()
        u = user.get("user") or user.get("user_info") or user
        if isinstance(u, dict) and "user" in u:
            u = u["user"]
        if isinstance(u, dict):
            account = {
                "nickname": u.get("nickname"),
                "uid": str(u.get("uid") or ""),
                "unique_id": u.get("unique_id") or u.get("short_id") or "",
            }
    except Exception:
        pass
    return build_chat_dump(
        auth,
        conversation_id,
        int(conversation_short_id),
        msgs,
        account=account,
    )


def dump_all_conversations(auth: ImAuth, *, limit: int = 40) -> Dict[str, Any]:
    """全部会话各拉最近 limit 条，微信时间线。"""
    convs = list_conversations(auth)
    conversations: List[Dict[str, Any]] = []
    account: Dict[str, Any] = {}
    try:
        account = account_summary(auth) or {}
    except Exception:
        account = {}
    for conv in convs:
        cid = conv["conversation_id"]
        short = int(conv["conversation_short_id"] or 0)
        try:
            data = dump_conversation(auth, cid, short, limit=limit)
        except Exception as exc:
            peer = peer_profile_for_conversation(auth, cid, [])
            conversations.append(
                {
                    "title": conversation_title(auth, cid, []),
                    "peer": peer,
                    "me": account,
                    "conversation_id": cid,
                    "conversation_short_id": short,
                    "error": str(exc),
                    "message_count": 0,
                    "messages": [],
                }
            )
            continue
        if not account:
            account = data.get("me") or {}
        conversations.append(data)
    return {
        "platform": "dy",
        "crawl_type": "im",
        "account": account,
        "conversation_count": len(conversations),
        "conversations": conversations,
    }


# 自动回复话术（网页版：每会话两步，与对方内容无关）
AUTO_REPLY_GREETING = "你好，是要了解私信聚合吗"
AUTO_REPLY_CONTACT = "+🌍180******"
# 兼容旧名 / 轮询兜底
AUTO_REPLY_INTRO = AUTO_REPLY_GREETING
DEFAULT_AUTO_REPLIES = [AUTO_REPLY_GREETING]


def auto_reply_for_conversation_state(state: str) -> str | None:
    """按会话进度返回下一条自动回复；done 或未知终态返回 None。"""
    s = str(state or "").strip()
    if s == "done":
        return None
    if s == "greeted":
        return AUTO_REPLY_CONTACT
    return AUTO_REPLY_GREETING




def _is_peer_chat_message(auth: ImAuth, m: Dict[str, Any]) -> bool:
    """对方发来的聊天消息（排除自己、已读回执）。"""
    mt = int(m.get("message_type") or 0)
    if mt == 50001:
        return False
    my = ""
    try:
        my = _self_uid(auth)
    except Exception:
        my = ""
    sender = str(m.get("sender") or "")
    if my and sender == my:
        return False
    return True


def run_poll_loop(
    auth: ImAuth,
    *,
    conversation_id: str = DEFAULT_CONVERSATION_ID,
    conversation_short_id: int = DEFAULT_CONVERSATION_SHORT_ID,
    interval: float = 2.0,
    seconds: int = 0,
    on_message: Optional[Callable[[Dict[str, Any]], None]] = None,
    auto_replies: Optional[List[str]] = None,
    headed: bool = False,
    all_conversations: bool = False,
    list_refresh: float = 30.0,
) -> None:
    """持续轮询新私信。seconds<=0 表示一直听。

    all_conversations=True 时扫收件箱全部会话，并定期刷新新会话。
    auto_replies 非空时，对方每来一条消息就依次发送这些文本。
    """
    replies = [str(t).strip() for t in (auto_replies or []) if str(t).strip()]
    if replies:
        try:
            ensure_send_cred(auth, headed=headed)
            print(f"[im] auto-reply {len(replies)} 条: {replies[0][:40]}…", flush=True)
        except Exception as e:
            print(f"[im] auto-reply 凭据准备失败: {e}", flush=True)
            replies = []

    seen: Set[str] = set()
    convs: Dict[str, int] = {}
    seeded: Set[str] = set()

    def refresh_convs() -> None:
        if all_conversations:
            listed = list_conversations(auth)
            for conv in listed:
                cid = str(conv.get("conversation_id") or "").strip()
                short = _as_int(conv.get("conversation_short_id"))
                if not cid or not short:
                    continue
                if cid not in convs:
                    print(f"[im] +conversation {cid} short={short}", flush=True)
                convs[cid] = short
            return
        cid = (conversation_id or "").strip() or DEFAULT_CONVERSATION_ID
        convs[cid] = _as_int(conversation_short_id, DEFAULT_CONVERSATION_SHORT_ID)

    def seed_missing(*, limit: int = 20) -> None:
        for cid, short in list(convs.items()):
            if cid in seeded:
                continue
            print(f"[im] seed conversation={cid} short={short}", flush=True)
            try:
                poll_new_messages(
                    auth, cid, short, seen, limit=limit, seed_only=True
                )
            except Exception as exc:
                print(f"[im] seed err {cid}: {exc}", flush=True)
            seeded.add(cid)

    refresh_convs()
    seed_missing(limit=40)
    print(
        f"[im] seeded {len(seen)} msgs across {len(convs)} conversations, watching…",
        flush=True,
    )
    start = time.time()
    last_list = start
    while True:
        if seconds > 0 and (time.time() - start) >= seconds:
            break
        if all_conversations and (time.time() - last_list) >= max(5.0, float(list_refresh)):
            try:
                refresh_convs()
                seed_missing(limit=20)
            except Exception as exc:
                print(f"[im] list refresh err: {exc}", flush=True)
            last_list = time.time()
        try:
            fresh: List[Dict[str, Any]] = []
            for cid, short in list(convs.items()):
                try:
                    fresh.extend(
                        poll_new_messages(
                            auth,
                            cid,
                            short,
                            seen,
                            limit=20,
                            seed_only=False,
                        )
                    )
                except Exception as exc:
                    print(f"[im] err {cid}: {exc}", flush=True)
            for m in fresh:
                line = format_im_message(auth, m)
                if on_message:
                    on_message(m)
                else:
                    print("[im]", line, flush=True)
                if replies and _is_peer_chat_message(auth, m):
                    msg_cid = str(m.get("conversation_id") or conversation_id or "")
                    msg_short = _as_int(
                        m.get("conversation_short_id"),
                        _as_int(conversation_short_id),
                    )
                    for i, text in enumerate(replies):
                        try:
                            result = send_text(
                                auth,
                                text,
                                conversation_id=msg_cid,
                                conversation_short_id=msg_short,
                            )
                            tag = "ok" if result.get("ok") else "fail"
                            print(
                                f"[im] auto-reply[{i+1}/{len(replies)}] {tag} {text[:60]}",
                                flush=True,
                            )
                        except Exception as exc:
                            print(f"[im] auto-reply err: {exc}", flush=True)
                        if i + 1 < len(replies):
                            time.sleep(0.6)
        except Exception as e:
            print(f"[im] err: {e}", flush=True)
        time.sleep(max(0.5, float(interval)))
