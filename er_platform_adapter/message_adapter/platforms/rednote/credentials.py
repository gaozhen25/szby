"""Rednote credentials stored in the SQLite vault, same as Douyin."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from message_adapter.config import AdapterConfig
from message_adapter.storage import CredentialStore


@dataclass(slots=True)
class RednoteCredential:
    cookie: str
    name: str = "rednote"
    source: str = ""
    web_session: str = ""
    user_id: str = ""
    red_id: str = ""
    nickname: str = ""
    device_id: str = ""
    browser_profile: str = ""

    @property
    def is_valid(self) -> bool:
        text = self.cookie.strip()
        return bool(text) and ("web_session=" in text or "a1=" in text)


def web_session_from_cookie(cookie: str) -> str:
    for part in str(cookie or "").split(";"):
        part = part.strip()
        if part.startswith("web_session="):
            return part.split("=", 1)[1].strip()
    return ""


def _store_or_default(store: CredentialStore | None) -> tuple[CredentialStore, bool]:
    if store is not None:
        return store, False
    path = AdapterConfig.load(platform="rednote").credential_db
    return CredentialStore(path), True


def _cookie_entry(payload: dict[str, Any]) -> dict[str, Any]:
    item = payload.get("cookie")
    return item if isinstance(item, dict) else {}


def load_rednote_cookie(*, store: CredentialStore | None = None) -> RednoteCredential:
    env = os.environ.get("REDNOTE_COOKIE", "").strip()
    if env:
        return RednoteCredential(cookie=env, source="env:REDNOTE_COOKIE", web_session=web_session_from_cookie(env))
    target, owned = _store_or_default(store)
    try:
        payload = target.get("rednote") or {}
    finally:
        if owned:
            target.close()
    item = _cookie_entry(payload)
    cookie = str(item.get("cookie") or "").strip()
    if not cookie:
        raise RuntimeError("小红书凭证不存在。请在桌面连接器扫码登录，或设置环境变量 REDNOTE_COOKIE")
    return RednoteCredential(
        cookie=cookie,
        name=str(item.get("name") or "rednote"),
        source=str(item.get("source") or "sqlite"),
        web_session=str(item.get("web_session") or web_session_from_cookie(cookie)),
        user_id=str(item.get("user_id") or ""),
        red_id=str(item.get("red_id") or ""),
        nickname=str(item.get("nickname") or ""),
        device_id=str(item.get("device_id") or ""),
        browser_profile=str(item.get("browser_profile") or ""),
    )


def save_rednote_cookie(
    cookie: str,
    *,
    store: CredentialStore,
    user_id: str,
    nickname: str = "",
    red_id: str = "",
    device_id: str = "",
    browser_profile: str = "",
    source: str = "browser:qr",
) -> None:
    store.save(
        "rednote",
        {
            "cookie": {
                "cookie": cookie,
                "name": nickname or "rednote",
                "source": source,
                "web_session": web_session_from_cookie(cookie),
                "user_id": user_id,
                "red_id": red_id,
                "nickname": nickname,
                "device_id": device_id,
                "browser_profile": browser_profile,
            }
        },
        platform_actor_id=user_id,
    )
