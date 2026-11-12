"""Douyin credentials backed exclusively by the SQLite credential vault."""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Any

from message_adapter.config import AdapterConfig
from message_adapter.storage import CredentialStore

_REQUIRED_IM_CRED_KEYS = ("DY_TICKET", "DY_TS_SIGN", "DY_CLIENT_CERT", "DY_PRIVATE_KEY")


@dataclass(slots=True)
class DouyinCredential:
    cookie: str
    name: str = "default"
    source: str = ""
    sessionid: str = ""
    uid: str = ""
    unique_id: str = ""
    nickname: str = ""
    sec_uid: str = ""
    browser_profile: str = ""

    @property
    def is_valid(self) -> bool:
        return bool(self.cookie.strip()) and "sessionid=" in self.cookie


def sessionid_from_cookie(cookie: str) -> str:
    for part in str(cookie or "").split(";"):
        part = part.strip()
        if part.startswith("sessionid="):
            return part.split("=", 1)[1].strip()
    return ""


def _store_or_default(store: CredentialStore | None) -> tuple[CredentialStore, bool]:
    if store is not None:
        return store, False
    path = AdapterConfig.load(platform="douyin").credential_db
    return CredentialStore(path), True


def _cookie_entry(payload: dict[str, Any]) -> dict[str, Any]:
    item = payload.get("cookie")
    return item if isinstance(item, dict) else {}


def load_douyin_cookie(
    *,
    store: CredentialStore | None = None,
) -> DouyinCredential:
    """Load the one Douyin credential assigned to this device."""
    env = os.environ.get("DY_COOKIE", "").strip()
    if env:
        return DouyinCredential(
            cookie=env,
            name="douyin",
            source="env:DY_COOKIE",
            sessionid=sessionid_from_cookie(env),
        )

    target, owned = _store_or_default(store)
    try:
        payload = target.get("douyin") or {}
    finally:
        if owned:
            target.close()
    item = _cookie_entry(payload)
    cookie = str(item.get("cookie") or "").strip()
    if not cookie:
        raise RuntimeError(
            "抖音凭证不存在。请执行 adapter douyin login，或设置环境变量 DY_COOKIE"
        )
    return DouyinCredential(
        cookie=cookie,
        name=str(item.get("name") or "douyin"),
        source=str(item.get("source") or "sqlite"),
        sessionid=str(item.get("sessionid") or sessionid_from_cookie(cookie)),
        uid=str(item.get("uid") or "").strip(),
        unique_id=str(item.get("unique_id") or "").strip(),
        nickname=str(item.get("nickname") or "").strip(),
        sec_uid=str(item.get("sec_uid") or "").strip(),
        browser_profile=str(item.get("browser_profile") or "").strip(),
    )


def save_douyin_cookie(
    cookie: str,
    *,
    store: CredentialStore | None = None,
    name: str = "douyin",
    source: str = "",
    uid: str = "",
    unique_id: str = "",
    nickname: str = "",
    sec_uid: str = "",
    browser_profile: str = "",
    **_: Any,
) -> str:
    """Upsert the cookie section for this device's Douyin slot."""
    cookie = cookie.strip()
    sid = sessionid_from_cookie(cookie)
    if not sid:
        raise ValueError("cookie 中缺少 sessionid")
    target, owned = _store_or_default(store)
    try:
        old = target.get("douyin") or {}
        previous = _cookie_entry(old)
        entry = {
            "name": str(name or previous.get("name") or "douyin"),
            "sessionid": sid,
            "cookie": cookie,
            "source": str(source or previous.get("source") or "manual"),
            "updated_at": int(time.time()),
        }
        for field, value in (
            ("uid", uid),
            ("unique_id", unique_id),
            ("nickname", nickname),
            ("sec_uid", sec_uid),
            ("browser_profile", browser_profile),
        ):
            resolved = str(value or previous.get(field) or "").strip()
            if resolved:
                entry[field] = resolved
        target.save("douyin", {**old, "cookie": entry}, platform_actor_id=str(uid or ""))
    finally:
        if owned:
            target.close()
    return str(uid or "")

def load_im_cred(
    *,
    store: CredentialStore | None = None,
    sessionid: str = "",
) -> dict[str, str]:
    target, owned = _store_or_default(store)
    try:
        payload = target.get("douyin") or {}
    finally:
        if owned:
            target.close()
    item = payload.get("im")
    if not isinstance(item, dict):
        return {}
    stored_sid = str(item.get("sessionid") or "")
    if sessionid and stored_sid and sessionid != stored_sid:
        return {}
    return {field: str(item[field]) for field in _REQUIRED_IM_CRED_KEYS if item.get(field)}


def save_im_cred(
    cred: dict[str, str],
    *,
    store: CredentialStore | None = None,
    sessionid: str = "",
    **_: Any,
) -> str:
    payload = {field: str(cred.get(field) or "") for field in _REQUIRED_IM_CRED_KEYS if cred.get(field)}
    if not payload:
        raise ValueError("发信凭据为空")
    target, owned = _store_or_default(store)
    try:
        old = target.get("douyin") or {}
        cookie_sid = str(_cookie_entry(old).get("sessionid") or "")
        target.save("douyin", {**old, "im": {"sessionid": str(sessionid or cookie_sid), **payload}})
        actor_id = target.get_bound_actor_id("douyin")
    finally:
        if owned:
            target.close()
    return actor_id
