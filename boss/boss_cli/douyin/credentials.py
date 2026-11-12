"""Douyin cookie + send-credential storage under <project>/douyin/."""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from boss_cli.constants import DOUYIN_COOKIE_FILE, DOUYIN_DIR, DOUYIN_IM_CRED_FILE

logger = logging.getLogger(__name__)

_BROWSER_ORDER = ("chrome", "edge", "brave", "firefox", "chromium", "safari")
_REQUIRED_IM_CRED_KEYS = ("DY_TICKET", "DY_TS_SIGN", "DY_CLIENT_CERT", "DY_PRIVATE_KEY")
SPIDER_IM_CRED_FILE = Path.home() / "spider" / "js" / "cookies" / "dy_im_cred.json"


@dataclass
class DouyinCredential:
    cookie: str
    name: str = "default"
    source: str = ""
    sessionid: str = ""
    uid: str = ""
    unique_id: str = ""
    nickname: str = ""
    sec_uid: str = ""

    @property
    def is_valid(self) -> bool:
        return bool((self.cookie or "").strip()) and "sessionid=" in self.cookie


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    path.chmod(0o600)


def sessionid_from_cookie(cookie: str) -> str:
    for part in str(cookie or "").split(";"):
        part = part.strip()
        if part.startswith("sessionid="):
            val = part.split("=", 1)[1].strip()
            if val:
                return val
    return ""


def _cookie_dict_to_str(cookies: dict[str, str]) -> str:
    return "; ".join(f"{k}={v}" for k, v in cookies.items() if k and v)


def _normalize_account_key(name: str) -> str:
    """Loose key for near-homophone typos (州/洲 etc.)."""
    text = str(name or "").strip().lower()
    if not text:
        return ""
    # 常见形近/音近字，避免 --account 寒州顾 找不到 寒洲顾
    for src, dst in (
        ("州", "洲"),
        ("洲", "洲"),
        ("清", "清"),
        ("顾", "顾"),
    ):
        text = text.replace(src, dst)
    return text


def _find_account(accounts: list[dict[str, Any]], *, name: str = "", sessionid: str = "") -> dict[str, Any] | None:
    if sessionid:
        for item in accounts:
            if str(item.get("sessionid") or "") == sessionid:
                return item
    if name:
        target = name.strip()
        for item in accounts:
            if str(item.get("name") or "") == target:
                return item
        # 模糊：归一化后全等，或编辑距离很近
        norm = _normalize_account_key(target)
        if norm:
            for item in accounts:
                item_name = str(item.get("name") or "")
                if _normalize_account_key(item_name) == norm:
                    return item
            try:
                import difflib

                names = [str(a.get("name") or "") for a in accounts if a.get("name")]
                hits = difflib.get_close_matches(target, names, n=1, cutoff=0.7)
                if hits:
                    for item in accounts:
                        if str(item.get("name") or "") == hits[0]:
                            return item
            except Exception:
                pass
    return None


def _normalize_cookie_accounts(data: Any) -> dict[str, Any]:
    if isinstance(data, dict) and isinstance(data.get("accounts"), list):
        accounts: list[dict[str, Any]] = []
        for item in data["accounts"]:
            if isinstance(item, str) and item.strip():
                sid = sessionid_from_cookie(item)
                accounts.append({"name": sid[:8] or "default", "sessionid": sid, "cookie": item.strip()})
            elif isinstance(item, dict) and item.get("cookie"):
                cookie = str(item["cookie"]).strip()
                sid = str(item.get("sessionid") or sessionid_from_cookie(cookie))
                entry = {
                    "name": str(item.get("name") or sid[:8] or "default"),
                    "sessionid": sid,
                    "cookie": cookie,
                    "source": str(item.get("source") or ""),
                    "updated_at": int(item.get("updated_at") or 0),
                }
                for key in ("uid", "unique_id", "nickname", "sec_uid"):
                    val = str(item.get(key) or "").strip()
                    if val:
                        entry[key] = val
                accounts.append(entry)
        active = str(data.get("active") or "")
        if not active and accounts:
            active = str(accounts[0].get("name") or "")
        return {"active": active, "accounts": accounts}

    if isinstance(data, dict):
        raw = data.get("cookie") or data.get("cookies") or ""
        if isinstance(raw, str) and raw.strip():
            name = str(data.get("name") or "default")
            sid = sessionid_from_cookie(raw)
            return {
                "active": name,
                "accounts": [
                    {
                        "name": name,
                        "sessionid": sid,
                        "cookie": raw.strip(),
                        "source": f"file:{DOUYIN_COOKIE_FILE}",
                        "updated_at": 0,
                    }
                ],
            }
        items = data.get("dy") or data.get("accounts")
        if isinstance(items, list) and items:
            accounts = []
            for i, picked in enumerate(items):
                if isinstance(picked, str) and picked.strip():
                    sid = sessionid_from_cookie(picked)
                    accounts.append({"name": f"dy_{i + 1}", "sessionid": sid, "cookie": picked.strip()})
                elif isinstance(picked, dict) and picked.get("cookie"):
                    cookie = str(picked["cookie"]).strip()
                    sid = str(picked.get("sessionid") or sessionid_from_cookie(cookie))
                    accounts.append(
                        {
                            "name": str(picked.get("name") or f"dy_{i + 1}"),
                            "sessionid": sid,
                            "cookie": cookie,
                        }
                    )
            if accounts:
                return {"active": str(accounts[0].get("name") or ""), "accounts": accounts}

    if isinstance(data, list):
        accounts = []
        for i, item in enumerate(data):
            if isinstance(item, str) and item.strip():
                sid = sessionid_from_cookie(item)
                accounts.append({"name": f"dy_{i + 1}", "sessionid": sid, "cookie": item.strip()})
        if accounts:
            return {"active": str(accounts[0].get("name") or ""), "accounts": accounts}

    if isinstance(data, str) and data.strip():
        sid = sessionid_from_cookie(data)
        return {
            "active": sid[:8] or "default",
            "accounts": [{"name": sid[:8] or "default", "sessionid": sid, "cookie": data.strip()}],
        }

    return {"active": "", "accounts": []}


def _load_cookie_store() -> dict[str, Any]:
    data = _read_json(DOUYIN_COOKIE_FILE)
    if data is None:
        txt = DOUYIN_DIR / "cookie.txt"
        if txt.is_file():
            text = txt.read_text(encoding="utf-8").strip()
            if text:
                return _normalize_cookie_accounts(text)
        return {"active": "", "accounts": []}
    return _normalize_cookie_accounts(data)


def _save_cookie_store(store: dict[str, Any]) -> Path:
    _write_json(DOUYIN_COOKIE_FILE, store)
    return DOUYIN_COOKIE_FILE


def _normalize_im_cred_accounts(data: Any) -> dict[str, Any]:
    if isinstance(data, dict) and isinstance(data.get("accounts"), list):
        accounts: list[dict[str, Any]] = []
        for item in data["accounts"]:
            if not isinstance(item, dict):
                continue
            payload = {k: str(v) for k, v in item.items() if k in _REQUIRED_IM_CRED_KEYS and v}
            if not payload:
                continue
            accounts.append(
                {
                    "name": str(item.get("name") or item.get("sessionid") or "default"),
                    "sessionid": str(item.get("sessionid") or ""),
                    **payload,
                }
            )
        active = str(data.get("active") or "")
        if not active and accounts:
            active = str(accounts[0].get("name") or "")
        return {"active": active, "accounts": accounts}

    if isinstance(data, dict) and any(data.get(k) for k in _REQUIRED_IM_CRED_KEYS):
        payload = {k: str(data[k]) for k in _REQUIRED_IM_CRED_KEYS if data.get(k)}
        # 兼容旧单账号文件：尽量挂上当前 cookie 的 sessionid，便于后续按账号 upsert。
        sid = ""
        name = "default"
        try:
            cookie_store = _normalize_cookie_accounts(_read_json(DOUYIN_COOKIE_FILE))
            active = str(cookie_store.get("active") or "")
            accounts = list(cookie_store.get("accounts") or [])
            picked = _find_account(accounts, name=active) if active else None
            if picked is None and accounts:
                picked = accounts[0]
            if picked:
                sid = str(picked.get("sessionid") or sessionid_from_cookie(str(picked.get("cookie") or "")))
                name = str(picked.get("name") or name)
        except Exception:
            pass
        return {"active": name, "accounts": [{"name": name, "sessionid": sid, **payload}]}

    return {"active": "", "accounts": []}


def _load_im_cred_store() -> dict[str, Any]:
    data = _read_json(DOUYIN_IM_CRED_FILE)
    if data is None:
        return {"active": "", "accounts": []}
    return _normalize_im_cred_accounts(data)


def _save_im_cred_store(store: dict[str, Any]) -> Path:
    _write_json(DOUYIN_IM_CRED_FILE, store)
    return DOUYIN_IM_CRED_FILE


def list_douyin_accounts() -> list[dict[str, Any]]:
    cookie_store = _load_cookie_store()
    cred_store = _load_im_cred_store()
    active = str(cookie_store.get("active") or "")
    rows: list[dict[str, Any]] = []
    for item in cookie_store.get("accounts") or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "")
        sid = str(item.get("sessionid") or sessionid_from_cookie(str(item.get("cookie") or "")))
        cred = _find_account(list(cred_store.get("accounts") or []), name=name, sessionid=sid) or {}
        cred_ok = all(cred.get(k) for k in _REQUIRED_IM_CRED_KEYS)
        rows.append(
            {
                "name": name,
                "sessionid": sid,
                "active": name == active,
                "source": str(item.get("source") or ""),
                "send_ready": cred_ok,
            }
        )
    return rows


def _is_sessionid_fallback_name(name: str, sessionid: str) -> bool:
    """True when name is just sessionid[:8] placeholder (not a real nickname)."""
    n = str(name or "").strip()
    sid = str(sessionid or "").strip()
    return bool(n) and bool(sid) and n == sid[:8]


def _prefer_account_name(*, new_name: str, old_name: str = "", sessionid: str = "") -> str:
    """Prefer a real nickname over sessionid-prefix fallback names."""
    sid = str(sessionid or "").strip()
    new = str(new_name or "").strip()
    old = str(old_name or "").strip()
    if new and not _is_sessionid_fallback_name(new, sid):
        return new
    if old and not _is_sessionid_fallback_name(old, sid):
        return old
    return new or old or (sid[:8] if sid else "douyin")


def set_active_douyin_account(name: str) -> None:
    target = str(name or "").strip()
    if not target:
        raise ValueError("账号名称不能为空")
    cookie_store = _load_cookie_store()
    account = _find_account(list(cookie_store.get("accounts") or []), name=target)
    if account is None:
        raise KeyError(f"未找到账号: {target}")
    cookie_store["active"] = target
    _save_cookie_store(cookie_store)

    cred_store = _load_im_cred_store()
    sid = str(account.get("sessionid") or sessionid_from_cookie(str(account.get("cookie") or "")))
    cred = _find_account(list(cred_store.get("accounts") or []), name=target, sessionid=sid)
    if cred is not None:
        cred_store["active"] = str(cred.get("name") or target)
    else:
        cred_store["active"] = target
    _save_im_cred_store(cred_store)


def load_douyin_cookie(*, account_name: str = "") -> DouyinCredential:
    """Load Douyin cookie from env or <project>/douyin/ only."""
    env = (os.environ.get("DY_COOKIE") or "").strip()
    if env:
        sid = sessionid_from_cookie(env)
        return DouyinCredential(cookie=env, name="env", source="env:DY_COOKIE", sessionid=sid)

    DOUYIN_DIR.mkdir(parents=True, exist_ok=True)
    store = _load_cookie_store()
    accounts = [a for a in (store.get("accounts") or []) if isinstance(a, dict) and a.get("cookie")]
    if not accounts:
        raise RuntimeError(
            f"未找到抖音 cookie。请执行: boss douyin login\n"
            f"（有界面浏览器扫码，自动保存 cookie + ticket）\n"
            f"或写入 {DOUYIN_COOKIE_FILE} "
            '（{"accounts":[{"name":"账号1","cookie":"sessionid=..."}]}），或设置环境变量 DY_COOKIE'
        )

    picked = _find_account(accounts, name=account_name) if account_name else None
    if account_name and picked is not None and str(picked.get("name") or "") != account_name.strip():
        logger.warning(
            "账号名 %r 未精确匹配，已选用近似账号 %r",
            account_name,
            picked.get("name"),
        )
    if picked is None and account_name:
        active = str(store.get("active") or "")
        picked = _find_account(accounts, name=active) if active else None
        if picked is not None:
            logger.warning(
                "未找到账号 %r，回退到当前 active=%r（请确认昵称：寒洲顾 不是 寒州顾）",
                account_name,
                picked.get("name"),
            )
    elif picked is None:
        active = str(store.get("active") or "")
        picked = _find_account(accounts, name=active) if active else None
    if picked is None:
        picked = accounts[0]

    cookie = str(picked.get("cookie") or "").strip()
    name = str(picked.get("name") or "default")
    sid = str(picked.get("sessionid") or sessionid_from_cookie(cookie))
    source = str(picked.get("source") or f"file:{DOUYIN_COOKIE_FILE}")
    return DouyinCredential(
        cookie=cookie,
        name=name,
        source=source,
        sessionid=sid,
        uid=str(picked.get("uid") or "").strip(),
        unique_id=str(picked.get("unique_id") or "").strip(),
        nickname=str(picked.get("nickname") or "").strip(),
        sec_uid=str(picked.get("sec_uid") or "").strip(),
    )


def save_douyin_cookie(
    cookie: str,
    *,
    name: str = "default",
    source: str = "",
    append: bool = True,
    set_active: bool = True,
    uid: str = "",
    unique_id: str = "",
    nickname: str = "",
    sec_uid: str = "",
) -> Path:
    """Save cookie; default upserts by sessionid and keeps other accounts."""
    cookie = cookie.strip()
    sid = sessionid_from_cookie(cookie)
    if not sid:
        raise ValueError("cookie 中缺少 sessionid，无法保存多账号配置")

    store = _load_cookie_store()
    accounts = list(store.get("accounts") or [])
    existing = _find_account(accounts, name=name, sessionid=sid)
    entry = {
        "name": name,
        "sessionid": sid,
        "cookie": cookie,
        "source": source,
        "updated_at": int(time.time()),
    }
    for key, val in (
        ("uid", uid),
        ("unique_id", unique_id),
        ("nickname", nickname),
        ("sec_uid", sec_uid),
    ):
        text = str(val or "").strip()
        if text:
            entry[key] = text
        elif existing is not None and existing.get(key):
            entry[key] = str(existing.get(key) or "")
    if existing is not None:
        entry["name"] = _prefer_account_name(
            new_name=name,
            old_name=str(existing.get("name") or ""),
            sessionid=sid,
        )
        accounts[accounts.index(existing)] = {**existing, **entry}
    elif append or not accounts:
        accounts.append(entry)
    else:
        active_name = str(store.get("active") or "")
        active = _find_account(accounts, name=active_name) if active_name else None
        if active is not None:
            entry["name"] = _prefer_account_name(
                new_name=name,
                old_name=str(active.get("name") or ""),
                sessionid=sid,
            )
            accounts[accounts.index(active)] = {**active, **entry}
        else:
            accounts[0] = {**accounts[0], **entry}

    if set_active:
        store["active"] = entry["name"]
    store["accounts"] = accounts
    return _save_cookie_store(store)


def extract_browser_douyin_cookie(cookie_source: str | None = None) -> tuple[str | None, list[str]]:
    """Extract douyin.com cookies from a local browser via browser-cookie3."""
    try:
        import browser_cookie3 as bc3
    except ImportError:
        return None, ["browser-cookie3 未安装"]

    browser_fns = {
        "chrome": bc3.chrome,
        "edge": bc3.edge,
        "brave": bc3.brave,
        "firefox": bc3.firefox,
        "chromium": bc3.chromium,
        "safari": bc3.safari,
    }
    order = [cookie_source.strip().lower()] if cookie_source else list(_BROWSER_ORDER)
    for name in order:
        fn = browser_fns.get(name)
        if fn is None:
            continue
        try:
            jar = fn(domain_name=".douyin.com")
        except Exception as exc:
            logger.debug("%s douyin extraction failed: %s", name, exc)
            continue
        cookies: dict[str, str] = {}
        for item in jar:
            domain = item.domain or ""
            if "douyin.com" not in domain:
                continue
            if item.name and item.value:
                cookies[item.name] = item.value
        if cookies.get("sessionid"):
            logger.info("Found douyin cookies in %s", name)
            return _cookie_dict_to_str(cookies), []
    return None, ["未在浏览器中找到 douyin.com 的 sessionid，请先登录 douyin.com"]


def load_im_cred(*, account_name: str = "", sessionid: str = "") -> dict[str, str]:
    store = _load_im_cred_store()
    accounts = [a for a in (store.get("accounts") or []) if isinstance(a, dict)]
    picked = _find_account(accounts, name=account_name, sessionid=sessionid) if (account_name or sessionid) else None
    if picked is None:
        active = str(store.get("active") or "")
        picked = _find_account(accounts, name=active) if active else None
    if picked is None and not (account_name or sessionid):
        cookie = load_douyin_cookie()
        picked = _find_account(accounts, name=cookie.name, sessionid=cookie.sessionid)
    if picked is None and accounts:
        picked = accounts[0]
    if not picked:
        return {}
    return {k: str(picked[k]) for k in _REQUIRED_IM_CRED_KEYS if picked.get(k)}


def save_im_cred(
    cred: dict[str, str],
    *,
    account_name: str = "",
    sessionid: str = "",
    append: bool = True,
    set_active: bool = True,
) -> Path:
    payload = {k: str(cred.get(k) or "") for k in _REQUIRED_IM_CRED_KEYS if cred.get(k)}
    if not payload:
        raise ValueError("发信凭据为空")

    if not sessionid or not account_name:
        try:
            active_cookie = load_douyin_cookie(account_name=account_name)
            sessionid = sessionid or active_cookie.sessionid
            account_name = account_name or active_cookie.name
        except Exception:
            account_name = account_name or "default"

    store = _load_im_cred_store()
    accounts = list(store.get("accounts") or [])
    existing = _find_account(accounts, name=account_name, sessionid=sessionid)
    entry = {
        "name": account_name or sessionid[:8] or "default",
        "sessionid": sessionid,
        **payload,
    }
    if existing is not None:
        entry["name"] = _prefer_account_name(
            new_name=entry["name"],
            old_name=str(existing.get("name") or ""),
            sessionid=sessionid,
        )
        accounts[accounts.index(existing)] = {**existing, **entry}
    elif append or not accounts:
        accounts.append(entry)
    else:
        active_name = str(store.get("active") or "")
        active = _find_account(accounts, name=active_name) if active_name else None
        if active is not None:
            entry["name"] = _prefer_account_name(
                new_name=entry["name"],
                old_name=str(active.get("name") or ""),
                sessionid=sessionid,
            )
            accounts[accounts.index(active)] = {**active, **entry}
        else:
            accounts[0] = {**accounts[0], **entry}

    if set_active:
        store["active"] = entry["name"]
    store["accounts"] = accounts
    return _save_im_cred_store(store)


def import_im_cred_from_spider(*, source: Path | None = None, account_name: str = "") -> Path:
    """Copy send credentials from legacy spider/js cookies/dy_im_cred.json."""
    src = Path(source) if source else SPIDER_IM_CRED_FILE
    if not src.is_file():
        raise FileNotFoundError(f"未找到发信凭据: {src}")
    data = _read_json(src)
    if not isinstance(data, dict):
        raise RuntimeError(f"凭据文件格式无效: {src}")
    missing = [k for k in _REQUIRED_IM_CRED_KEYS if not data.get(k)]
    if missing:
        raise RuntimeError(f"凭据不完整，缺少: {', '.join(missing)}")
    payload = {k: str(data[k]) for k in _REQUIRED_IM_CRED_KEYS}
    return save_im_cred(payload, account_name=account_name, append=True)


def im_cred_status(*, account_name: str = "") -> dict[str, bool]:
    data = load_im_cred(account_name=account_name)
    return {k: bool(data.get(k)) for k in _REQUIRED_IM_CRED_KEYS}
