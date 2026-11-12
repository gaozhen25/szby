# -*- coding: utf-8 -*-
"""抖音 Web IM：会话解析与私信发送（不依赖 DouYin_Spider）。

接口:
  POST https://imapi.douyin.com/v1/conversation/get_list       (protobuf cmd=200)
  POST https://imapi.douyin.com/v1/message/get_by_conversation  (protobuf cmd=301)
  POST https://imapi.douyin.com/v2/conversation/create         (protobuf cmd=609)
  POST https://imapi.douyin.com/v1/message/send                (protobuf cmd=100)

鉴权使用 SQLite 凭证库中的 sessionid。发信还需要扫码登录取得的
web_protect ticket 与签名密钥。
"""

from __future__ import annotations

from collections import Counter
import base64
import hashlib
import json
import logging
import random
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple
from urllib.parse import quote

import requests
import urllib3

from message_adapter.browser_identity import current_browser_identity, sec_ch_ua_for_user_agent

from .api import DEFAULT_UA, DouyinClient
from .images import openable_image_url
from .signing import get_a_bogus, parse_cookie_str

urllib3.disable_warnings()

logger = logging.getLogger(__name__)

GET_BY_CONVERSATION = "https://imapi.douyin.com/v1/message/get_by_conversation"
CREATE_CONVERSATION = "https://imapi.douyin.com/v2/conversation/create"
SEND_MESSAGE = "https://imapi.douyin.com/v1/message/send"
GET_CONVERSATION_LIST = "https://imapi.douyin.com/v1/conversation/get_list"

DEFAULT_CONVERSATION_ID = "0:1:75604715923:468829025871684"
DEFAULT_CONVERSATION_SHORT_ID = 7303822822667764275

_nick_cache: Dict[str, str] = {}
_user_cache: Dict[str, Dict[str, Any]] = {}


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


def load_auth(
    *,
    cookie: str = "",
    account_name: str = "",
    uid: str = "",
    send_credential: dict[str, Any] | None = None,
) -> ImAuth:
    """Build protocol authentication from explicitly supplied credentials."""
    if not cookie.strip():
        raise ValueError("Douyin cookie is required")
    jar = parse_cookie_str(cookie)
    auth = ImAuth(
        cookie=jar,
        cookie_str=cookie,
        uid=str(uid or "").strip(),
        account_name=str(account_name or ""),
    )
    if send_credential:
        _apply_cred(auth, send_credential)
    if not auth.token:
        raise RuntimeError("missing sessionid in Douyin credential")
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
        raise RuntimeError(f"发信缺少 {', '.join(missing)}。请重新运行 adapter douyin login")


def ensure_send_cred(auth: ImAuth, *, headed: bool = False) -> None:
    """Require send credentials captured by the interactive login command."""
    del headed
    require_send_cred(auth)


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
    from .profile import avatar_from_user

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


def _protobuf_headers(ua: str = DEFAULT_UA) -> Dict[str, str]:
    browser = current_browser_identity()
    return {
        "user-agent": ua,
        "accept": "application/x-protobuf",
        "content-type": "application/x-protobuf",
        "cache-control": "no-cache",
        "pragma": "no-cache",
        "sec-ch-ua": sec_ch_ua_for_user_agent(ua),
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": browser.sec_ch_ua_platform,
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
    from .profile import avatar_from_user

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


def resolve_user_profile(auth: ImAuth, uid: str, sec_sender: str = "") -> Dict[str, Any]:
    """uid / sec_uid → {uid, nickname, unique_id, sec_uid, avatar}。"""
    uid = str(uid or "").strip()
    if not uid:
        return {"uid": "", "nickname": "?", "unique_id": "", "sec_uid": "", "avatar": ""}
    cached = _user_cache.get(uid)
    sec_in = str(sec_sender or "").strip()
    # Reuse only complete profiles (nickname + avatar). Incomplete cache blocked avatar refresh.
    if cached and cached.get("avatar") and cached.get("nickname") and cached.get("nickname") != uid:
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
        parts.append(_enc_bytes(24, base64.b64encode(auth.client_cert.encode("utf-8")).decode()))
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
    if text.startswith("http") or "douyin.com" in text or text.startswith("MS4wLjABAAAA"):
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
        raise RuntimeError(f"无法解析对方「{text}」（抖音号/昵称搜索失败）。可改用主页 URL，或直接传 uid。 原始错误: {exc}") from exc

    if text.isdigit():
        return {"uid": text, "nickname": "", "unique_id": "", "sec_uid": ""}
    raise RuntimeError(f"未找到用户: {text}")


def create_conversation(auth: ImAuth, to_user_id: int | str) -> Tuple[str, int, str]:
    """建/取单聊会话 → (conversation_id, conversation_short_id, ticket)。"""
    ensure_send_cred(auth)
    raw = str(to_user_id or "").strip()
    if not raw.isdigit():
        raise ValueError(f"create conversation needs numeric uid, got {to_user_id!r}")
    to_id = int(raw)
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
    web_protect 凭据必须由扫码登录命令准备。
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

    content_json = json.dumps(
        {
            "mention_users": [],
            "aweType": 700,
            "richTextInfos": [],
            "text": content_text,
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )

    def _deliver(target_cid: str, target_short: int, target_ticket: str) -> Dict[str, Any]:
        client_message_id = str(uuid.uuid4())
        stime = str(int(round(time.time() * 1000)))

        def _ext(key: str, value: str) -> bytes:
            return _enc_bytes(5, _enc_bytes(1, key) + _enc_bytes(2, value))

        body100 = b"".join(
            [
                _enc_bytes(1, target_cid),
                _enc_varint_field(2, 1),
                _enc_varint_field(3, int(target_short)),
                _enc_bytes(4, content_json),
                _ext("s:client_message_id", client_message_id),
                _ext("s:stime", stime),
                _ext("s:mentioned_users", ""),
                _enc_varint_field(6, 7),
                _enc_bytes(7, target_ticket),
                _enc_bytes(8, client_message_id),
            ]
        )
        sign = _generate_req_sign(
            {
                "sign_data": (
                    f"content={content_json}&conversation_id={target_cid}"
                    f"&conversation_short_id={target_short}"
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
        resp = requests.post(
            SEND_MESSAGE,
            params=params,
            headers=_protobuf_headers(auth.client.user_agent),
            cookies=auth.cookie,
            data=payload,
            verify=False,
            timeout=30,
        )
        if resp.status_code != 200:
            raise RuntimeError(f"send HTTP {resp.status_code}: {resp.content[:200]!r}")
        parsed = _parse_send_response(resp.content)
        parsed["client_message_id"] = client_message_id
        return parsed

    parsed = _deliver(cid, cshort, ticket)
    try:
        rejected_code = int(parsed.get("status_code")) if parsed.get("status_code") is not None else 0
    except (TypeError, ValueError):
        rejected_code = -1
    # A cached ticket/short id can be rejected while the account is still online.
    # Refresh once. Do not retry login/risk-control failures, and do not send
    # again when the first response simply lacked a server id.
    if (
        not parsed.get("ok")
        and rejected_code not in (0, 7911)
        and "重新登录" not in str(parsed.get("error_desc") or "")
        and to_raw.isdigit()
    ):
        logger.info(
            "Douyin send rejected status_code=%s; refreshing conversation before retry",
            rejected_code,
        )
        cid, cshort, ticket = create_conversation(auth, to_raw)
        parsed = _deliver(cid, cshort, ticket)

    out: Dict[str, Any] = {
        "ok": bool(parsed.get("ok")),
        "message": str(parsed.get("message") or ""),
        "error_desc": str(parsed.get("error_desc") or ""),
        "status_code": parsed.get("status_code"),
        "conversation_id": cid,
        "conversation_short_id": int(cshort),
        "client_message_id": str(parsed.get("client_message_id") or ""),
        "server_message_id": str(parsed.get("server_message_id") or ""),
        "text": content_text,
    }
    if peer:
        out["to"] = peer
    out["conversation_ticket"] = ticket
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


def _plausible_server_message_id(value: Any) -> str:
    """Snowflake / server ids are long digit strings. Small status ints are not."""
    if isinstance(value, bool):
        return ""
    if isinstance(value, int):
        text = str(value)
    elif isinstance(value, (bytes, bytearray)):
        text = bytes(value).decode("utf-8", "replace").strip()
    else:
        text = str(value or "").strip()
    if text.isdigit() and len(text) >= 6:
        return text
    return ""


def _parse_send_response(resp_content: bytes) -> Dict[str, Any]:
    """解析 message/send 响应。

    成功不一定写在信封 field4=='OK'。当前响应经常是 status_code=0，
    server_message_id 在 body100.field1。只认 field4 会把已投递的消息
    记成「发送失败」。body 里的 7911 仍表示未真正投递。
    """
    if not resp_content:
        return {
            "ok": False,
            "message": "",
            "error_desc": "发送响应为空",
            "status_code": None,
            "server_message_id": "",
        }
    stripped = resp_content.lstrip()
    if stripped[:1] in (b"{", b"[", b"<"):
        preview = stripped[:240].decode("utf-8", "replace")
        return {
            "ok": False,
            "message": preview,
            "error_desc": f"发送响应不是私信结果: {preview[:160]}",
            "status_code": None,
            "server_message_id": "",
        }

    top = _decode_fields(resp_content)
    msg = _as_text((top.get(4) or [b""])[0])
    err_top = (top.get(3) or [None])[0]
    status_code: Any = err_top if isinstance(err_top, int) else None
    err_desc = "" if isinstance(err_top, int) else _as_text(err_top)
    server_message_id = ""
    check: Any = None
    inner_status: Any = None

    body_raw = (top.get(6) or [b""])[0]
    if isinstance(body_raw, (bytes, bytearray)) and body_raw:
        body = _decode_fields(bytes(body_raw))
        inner_raw = (body.get(100) or [b""])[0]
        if isinstance(inner_raw, (bytes, bytearray)) and inner_raw:
            inner = _decode_fields(bytes(inner_raw))
            server_message_id = _plausible_server_message_id((inner.get(1) or [None])[0])
            inner_status_raw = (inner.get(3) or [None])[0]
            nested_id = _plausible_server_message_id(inner_status_raw)
            if nested_id:
                if not server_message_id:
                    server_message_id = nested_id
            elif isinstance(inner_status_raw, int):
                inner_status = inner_status_raw
            check = (inner.get(5) or [None])[0]
            payload = (inner.get(6) or [b""])[0]
            if isinstance(payload, (bytes, bytearray)) and payload:
                text = bytes(payload).decode("utf-8", "replace")
                if text.startswith("{"):
                    try:
                        data = json.loads(text)
                    except json.JSONDecodeError:
                        data = None
                    if isinstance(data, dict):
                        if "status_code" in data:
                            status_code = data.get("status_code")
                        tip = _tips_from_status_payload(data)
                        if tip:
                            err_desc = tip
                        if not server_message_id:
                            server_message_id = _plausible_server_message_id(
                                data.get("server_message_id") or data.get("server_msg_id")
                            )
                elif not server_message_id:
                    try:
                        mb = _decode_fields(bytes(payload))
                        server_message_id = _plausible_server_message_id((mb.get(3) or [b""])[0])
                    except Exception:
                        pass

    try:
        envelope_code = int(status_code) if status_code is not None else 0
    except (TypeError, ValueError):
        envelope_code = -1
    try:
        inner_code = int(inner_status) if inner_status is not None else 0
    except (TypeError, ValueError):
        inner_code = -1
    check_bad = check not in (None, 0, 1)
    message_bad = bool(msg) and msg not in {"OK", "0"}
    rejected = envelope_code != 0 or inner_code != 0 or check_bad or message_bad
    if envelope_code == 7911 or inner_code == 7911 or "重新登录" in err_desc:
        if "重新登录" not in err_desc:
            err_desc = err_desc or "重新登录后可以正常使用私信"
        err_desc = f"{err_desc}。请重新执行 adapter douyin login"
        rejected = True
    ok = not rejected and bool(server_message_id)
    if not ok and not err_desc:
        if message_bad:
            err_desc = msg
        elif envelope_code not in (0, None) or (status_code not in (None, 0) and envelope_code != 0):
            err_desc = f"发送被拒绝 status_code={status_code}"
        elif inner_code not in (0, None):
            err_desc = f"发送被拒绝 status_code={inner_status}"
        elif check_bad:
            err_desc = f"发送未确认(check={check})"
        elif not server_message_id:
            err_desc = "发送未拿到 server_message_id（疑似未真正投递）"
        else:
            err_desc = "发送失败"
    return {
        "ok": ok,
        "message": msg,
        "error_desc": "" if ok else err_desc,
        "status_code": status_code if status_code is not None else inner_status,
        "server_message_id": server_message_id,
    }


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
                    create_ms = _guess_unix_ms(obj.get("create_time") or obj.get("createTime") or 0)
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
        payload = _build_get_conversation_list_bytes(auth, cursor=cursor, limit=max(1, int(page_size)))
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


def _first_url(media: Dict[str, Any]) -> str:
    urls = media.get("urls") or []
    return str(urls[0]) if urls else ""


def _positive_int(value: Any, default: int = 0) -> int:
    try:
        number = int(float(value))
    except (TypeError, ValueError):
        return default
    return number if number > 0 else default


def _duration_ms(raw: Dict[str, Any]) -> int:
    if raw.get("duration_ms") not in (None, ""):
        return _positive_int(raw.get("duration_ms"))
    number = raw.get("duration", raw.get("voice_duration"))
    if number in (None, ""):
        return 0
    try:
        value = float(number)
    except (TypeError, ValueError):
        return 0
    if value <= 0:
        return 0
    # 抖音语音 duration 有时是秒（3.8），文档要求 MQ 用毫秒。
    return int(value if value > 1000 else value * 1000)


def _nested_meta(raw: Dict[str, Any], *keys: str, default: int = 0) -> int:
    sources: List[Any] = [raw]
    for name in ("resource_url", "url", "cover_url"):
        nested = raw.get(name)
        if isinstance(nested, dict):
            sources.append(nested)
    for source in sources:
        for key in keys:
            found = _positive_int(source.get(key))
            if found:
                return found
    return default


def _cover_url(raw: Dict[str, Any]) -> str:
    cover = raw.get("cover_url")
    if isinstance(cover, dict):
        for key in ("origin_url_list", "url_list", "large_url_list", "thumb_url_list"):
            values = cover.get(key) or []
            if values and isinstance(values[0], str) and values[0].startswith("http"):
                return values[0]
    if isinstance(cover, str) and cover.startswith("http"):
        return cover
    return ""


def _picture_content(raw: Dict[str, Any], url: str, *, kind: str) -> Dict[str, Any]:
    if kind == "emoji":
        size = width = height = 100
    else:
        size = _nested_meta(raw, "size", "data_size", default=100)
        width = _nested_meta(raw, "width", default=100)
        height = _nested_meta(raw, "height", default=100)
        url, decoded_size = openable_image_url(raw, url)
        if decoded_size:
            size = decoded_size
    return {
        "picture": {
            "sourcePath": "./",
            "sourcePicture": {
                "uuid": str(uuid.uuid4()),
                "type": kind,
                "size": size,
                "width": width,
                "height": height,
                "url": url,
            },
        }
    }


def _video_content(raw: Dict[str, Any], video_url: str, cover: str) -> Dict[str, Any]:
    return {
        "video": {
            "videoPath": "",
            "videoUUID": str(uuid.uuid4()),
            "videoUrl": video_url,
            "videoType": "mp4",
            "videoSize": _nested_meta(raw, "size", "data_size"),
            "duration": _duration_ms(raw),
            "snapshotPath": "",
            "snapshotUUID": str(uuid.uuid4()),
            "snapshotSize": _nested_meta(raw, "preview_img_size"),
            "snapshotUrl": cover,
            "snapshotWidth": _nested_meta(raw, "width"),
            "snapshotHeight": _nested_meta(raw, "height"),
        }
    }


def _plain_quote(value: str) -> str:
    text = value.strip()
    if "「" in text and "」" in text:
        inner = text.split("「", 1)[1].split("」", 1)[0].strip()
        if inner:
            return inner
    return text.strip("「」")


def _quote_text(raw: Dict[str, Any]) -> str:
    for key in ("quote_content", "ref_msg_text", "reply_text"):
        value = raw.get(key)
        if isinstance(value, str) and value.strip():
            return _plain_quote(value)
        if isinstance(value, dict):
            nested = str(value.get("text") or value.get("content") or "").strip()
            if nested:
                return _plain_quote(nested)
    for key in ("refmsg", "ref_msg", "quote", "reply"):
        nested = raw.get(key)
        if isinstance(nested, dict):
            value = str(nested.get("text") or nested.get("content") or "").strip()
            if value:
                return value
        elif isinstance(nested, str) and nested.strip():
            return nested.strip()
    return ""


def im_uplink_content(m: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """把抖音 IM 消息映射成 qkserver 上行 content。

    类型与 spider/js 的 render_dy_message 一致：
    7 文本、5 表情、27 图片、17 语音、8/105 分享视频、77/110 分享卡片。
    50001 已读回执不进入 MQ。
    """
    mt = int(m.get("message_type") or 0)
    if mt == 50001:
        return None
    content = m.get("content") or ""
    media = parse_media_urls(content)
    raw = media.get("raw") if isinstance(media.get("raw"), dict) else {}
    url = _first_url(media)
    summary = message_body(None, m).strip()  # type: ignore[arg-type]

    if mt == 7:
        text = summary
        quoted = _quote_text(raw)
        if quoted:
            return {
                "content_type": 114,
                "text": text or quoted,
                "content": {
                    "quote": {
                        "text": text,
                        "quoteMessage": {"text": quoted},
                        "quoteMessageType": 101,
                    }
                },
            }
        if not text:
            return None
        return {"content_type": 101, "text": text, "content": {"text": text}}

    if mt == 5:
        return {
            "content_type": 102,
            "text": summary or "[表情]",
            "content": _picture_content(raw, url, kind="emoji"),
        }
    if mt == 27:
        return {
            "content_type": 102,
            "text": summary or "[图片]",
            "content": _picture_content(raw, url, kind="image"),
        }
    if mt == 17:
        return {
            "content_type": 103,
            "text": summary or "[语音]",
            "content": {
                "voice": {
                    "uuid": str(uuid.uuid4()),
                    "soundPath": "",
                    "sourceUrl": url,
                    "dataSize": _nested_meta(raw, "size", "data_size"),
                    "duration": _duration_ms(raw),
                }
            },
        }
    if mt in (8, 77, 105, 110) or raw.get("aweType") == 800 or _extract_share_item_id(raw):
        item = _extract_share_item_id(raw)
        # 8/105 是分享视频；77/110 是分享卡片，带作品 ID 时同样是可打开的视频。
        if item or mt in (8, 105):
            video_url = f"https://www.douyin.com/video/{item}" if item else url
            if video_url or summary:
                return {
                    "content_type": 104,
                    "text": summary or "[视频]",
                    "content": _video_content(raw, video_url, _cover_url(raw)),
                }
        if not summary:
            return None
        return {"content_type": 101, "text": summary, "content": {"text": summary}}

    if not summary:
        return None
    if summary.startswith("{") or summary.startswith("["):
        summary = "[消息]"
    return {"content_type": 101, "text": summary, "content": {"text": summary}}


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


def sort_messages(msgs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return sorted(
        msgs,
        key=lambda m: (
            _as_int(m.get("create_time_ms")),
            _as_int(m.get("index_in_conversation")),
        ),
    )
