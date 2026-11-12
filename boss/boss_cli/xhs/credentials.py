"""Xiaohongshu cookie storage under <project>/xhs/cookies.json."""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from boss_cli.constants import XHS_COOKIE_FILE, XHS_DIR

logger = logging.getLogger(__name__)


@dataclass
class XhsCredential:
    cookie: str
    name: str = "default"
    source: str = ""
    web_session: str = ""
    user_id: str = ""
    red_id: str = ""
    nickname: str = ""

    @property
    def is_valid(self) -> bool:
        text = (self.cookie or "").strip()
        return bool(text) and ("web_session=" in text or "a1=" in text)


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    path.chmod(0o600)


def web_session_from_cookie(cookie: str) -> str:
    for part in str(cookie or "").split(";"):
        part = part.strip()
        if part.startswith("web_session="):
            return part.split("=", 1)[1].strip()
    return ""


def _normalize_cookie_text(text: str) -> str:
    parts: list[str] = []
    for line in (text or "").splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        parts.append(s.rstrip(";"))
    if not parts:
        return (text or "").strip()
    if len(parts) == 1:
        return parts[0]
    return "; ".join(parts)


def _load_store() -> dict[str, Any]:
    XHS_DIR.mkdir(parents=True, exist_ok=True)
    data = _read_json(XHS_COOKIE_FILE)
    if not isinstance(data, dict):
        return {"active": "", "accounts": []}
    accounts = data.get("accounts")
    if not isinstance(accounts, list):
        # Compat: spider/js cookies.json {"xhs": ["cookie...", ...]}
        raw = data.get("xhs")
        if isinstance(raw, list):
            accounts = []
            for i, item in enumerate(raw):
                if isinstance(item, str) and item.strip():
                    accounts.append(
                        {
                            "name": f"account{i + 1}",
                            "cookie": _normalize_cookie_text(item),
                            "web_session": web_session_from_cookie(item),
                            "source": "import:spider",
                            "updated_at": int(time.time()),
                        }
                    )
            return {"active": accounts[0]["name"] if accounts else "", "accounts": accounts}
        accounts = []
    return {
        "active": str(data.get("active") or ""),
        "accounts": [a for a in accounts if isinstance(a, dict)],
    }


def _save_store(store: dict[str, Any]) -> Path:
    _write_json(XHS_COOKIE_FILE, store)
    return XHS_COOKIE_FILE


def _find_account(
    accounts: list[dict[str, Any]],
    *,
    name: str = "",
    web_session: str = "",
) -> dict[str, Any] | None:
    name = (name or "").strip()
    web_session = (web_session or "").strip()
    if name:
        for acc in accounts:
            if str(acc.get("name") or "").strip() == name:
                return acc
    if web_session:
        for acc in accounts:
            if str(acc.get("web_session") or "").strip() == web_session:
                return acc
            if web_session_from_cookie(str(acc.get("cookie") or "")) == web_session:
                return acc
    return None


def _to_credential(acc: dict[str, Any]) -> XhsCredential:
    cookie = _normalize_cookie_text(str(acc.get("cookie") or ""))
    return XhsCredential(
        cookie=cookie,
        name=str(acc.get("name") or "default"),
        source=str(acc.get("source") or ""),
        web_session=str(acc.get("web_session") or web_session_from_cookie(cookie)),
        user_id=str(acc.get("user_id") or ""),
        red_id=str(acc.get("red_id") or ""),
        nickname=str(acc.get("nickname") or ""),
    )


def list_xhs_accounts() -> list[dict[str, Any]]:
    store = _load_store()
    active = str(store.get("active") or "")
    rows: list[dict[str, Any]] = []
    for acc in store.get("accounts") or []:
        cred = _to_credential(acc)
        rows.append(
            {
                "active": cred.name == active,
                "name": cred.name,
                "web_session": (cred.web_session[:16] + "…") if cred.web_session else "",
                "nickname": cred.nickname,
                "user_id": cred.user_id,
                "valid": cred.is_valid,
            }
        )
    return rows


def set_active_xhs_account(name: str) -> None:
    store = _load_store()
    hit = _find_account(list(store.get("accounts") or []), name=name)
    if hit is None:
        raise KeyError(f"未找到小红书账号: {name}")
    store["active"] = str(hit.get("name") or name)
    _save_store(store)


def load_xhs_cookie(*, account_name: str = "") -> XhsCredential:
    store = _load_store()
    accounts = list(store.get("accounts") or [])
    picked = None
    if account_name:
        picked = _find_account(accounts, name=account_name)
        if picked is None:
            raise KeyError(f"未找到小红书账号: {account_name}")
    else:
        active = str(store.get("active") or "")
        picked = _find_account(accounts, name=active) if active else None
        if picked is None and accounts:
            picked = accounts[0]
    if picked is None:
        raise RuntimeError(
            "未找到小红书 cookie。请先执行: boss xhs login（浏览器扫码）"
        )
    cred = _to_credential(picked)
    if not cred.is_valid:
        raise RuntimeError(f"账号 {cred.name} 的 cookie 无效，请重新扫码登录")
    return cred


def save_xhs_cookie(
    cookie: str,
    *,
    account_name: str = "",
    source: str = "browser:qr",
    user_id: str = "",
    red_id: str = "",
    nickname: str = "",
    set_active: bool = True,
) -> XhsCredential:
    cookie = _normalize_cookie_text(cookie)
    if not cookie:
        raise ValueError("空 cookie，无法保存")
    web_session = web_session_from_cookie(cookie)
    store = _load_store()
    accounts = list(store.get("accounts") or [])
    name = (account_name or nickname or red_id or web_session[:12] or "default").strip()
    existing = _find_account(accounts, name=name, web_session=web_session)
    entry = {
        "name": name,
        "cookie": cookie,
        "web_session": web_session,
        "user_id": str(user_id or ""),
        "red_id": str(red_id or ""),
        "nickname": str(nickname or ""),
        "source": source,
        "updated_at": int(time.time()),
    }
    if existing is not None:
        idx = accounts.index(existing)
        entry["name"] = str(existing.get("name") or name)
        accounts[idx] = {**existing, **entry}
    else:
        accounts.append(entry)
    store["accounts"] = accounts
    if set_active:
        store["active"] = entry["name"]
    _save_store(store)
    logger.info("saved xhs cookie account=%s", entry["name"])
    return _to_credential(entry)
