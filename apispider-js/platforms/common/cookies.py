# -*- coding: utf-8 -*-
"""统一 Cookie JSON 加载。

默认文件: cookies/cookies.json

格式:
{
  "xhs": ["cookie字符串1", "cookie字符串2"],
  "dy": ["cookie字符串1"],
  "dyhot": ["cookie字符串1"],
  "ks": []
}

兼容:
- 环境变量 XHS_COOKIE / DY_COOKIE / DYHOT_COOKIE
- 旧版 cookies/xhs.json、dy.json（accounts 结构）与 *_cookie.txt
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[2]

UNIFIED_COOKIE_FILES = ["cookies.json", "cookie.json"]

PLATFORM_ENV = {
    "xhs": "XHS_COOKIE",
    "dy": "DY_COOKIE",
    "dyhot": "DYHOT_COOKIE",
    "ks": "KS_COOKIE",
}

PLATFORM_ALIASES = {
    "douyin": "dy",
    "抖音": "dy",
    "xiaohongshu": "xhs",
    "red": "xhs",
    "小红书": "xhs",
    "douhot": "dyhot",
    "热点宝": "dyhot",
    "kuaishou": "ks",
    "快手": "ks",
}

PLATFORM_LEGACY_JSON = {
    "xhs": ["xhs.json", "xhs_cookies.json"],
    "dy": ["dy.json", "dy_cookies.json"],
    "dyhot": ["dyhot.json", "dyhot_cookies.json"],
    "ks": ["ks.json"],
}

PLATFORM_LEGACY_TXT = {
    "xhs": ["xhs_cookie.txt"],
    "dy": ["dy_cookie.txt"],
    "dyhot": ["dyhot_cookie.txt"],
    "ks": ["ks_cookie.txt"],
}


@dataclass
class CookieAccount:
    name: str
    cookie: str
    ms_token: str = ""
    enabled: bool = True
    extra: Dict[str, Any] = field(default_factory=dict)

    def as_header(self) -> str:
        return (self.cookie or "").strip()


def _normalize_platform(platform: str) -> str:
    platform = (platform or "").lower().strip()
    return PLATFORM_ALIASES.get(platform, platform)


def _resolve_existing(names: List[str]) -> Optional[Path]:
    roots = [ROOT / "cookies", ROOT, Path.cwd() / "cookies", Path.cwd()]
    for root in roots:
        for name in names:
            path = Path(name) if Path(name).is_absolute() else root / name
            if path.is_file():
                return path
    return None


def _normalize_cookie_text(text: str) -> str:
    parts: List[str] = []
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


def _ms_token_from_cookie(cookie: str) -> str:
    for part in (cookie or "").split(";"):
        part = part.strip()
        if part.lower().startswith("mstoken="):
            return part.split("=", 1)[1].strip()
    return ""


def _account_from_string(cookie: str, *, name: str) -> Optional[CookieAccount]:
    cookie = _normalize_cookie_text(cookie)
    if not cookie:
        return None
    return CookieAccount(
        name=name,
        cookie=cookie,
        ms_token=_ms_token_from_cookie(cookie)
        or os.environ.get("DY_MSTOKEN", "").strip(),
        enabled=True,
    )


def _accounts_from_platform_list(
    items: Any, *, platform: str
) -> List[CookieAccount]:
    if items is None:
        return []
    if isinstance(items, str):
        items = [items]
    if not isinstance(items, list):
        return []
    out: List[CookieAccount] = []
    for i, item in enumerate(items, start=1):
        name = f"{platform}_{i}"
        if isinstance(item, str):
            acc = _account_from_string(item, name=name)
            if acc:
                out.append(acc)
            continue
        if isinstance(item, dict):
            cookie = item.get("cookie") or item.get("cookies") or ""
            if isinstance(cookie, list):
                cookie = cookie[0] if cookie else ""
            acc = _account_from_string(str(cookie), name=str(item.get("name") or name))
            if not acc:
                continue
            ms = str(
                item.get("msToken")
                or item.get("mstoken")
                or item.get("ms_token")
                or ""
            ).strip()
            if ms:
                acc.ms_token = ms
            enabled = item.get("enabled", True)
            if isinstance(enabled, str):
                enabled = enabled.strip().lower() not in ("0", "false", "no", "off")
            acc.enabled = bool(enabled)
            out.append(acc)
    return out


def _accounts_from_legacy_obj(data: Any, *, platform: str) -> List[CookieAccount]:
    """旧版单平台 JSON：{accounts:[...]} / {cookie:...}。"""
    if isinstance(data, list):
        return _accounts_from_platform_list(data, platform=platform)
    if isinstance(data, str):
        return _accounts_from_platform_list([data], platform=platform)
    if not isinstance(data, dict):
        return []
    if platform in data and isinstance(data[platform], (list, str)):
        return _accounts_from_platform_list(data[platform], platform=platform)
    for key in ("accounts", "cookies", "items"):
        if key in data and isinstance(data[key], list):
            return _accounts_from_platform_list(data[key], platform=platform)
    cookie = data.get("cookie") or data.get("Cookie") or ""
    if cookie:
        return _accounts_from_platform_list([cookie], platform=platform)
    return []


def _parse_legacy_txt(path: Path, platform: str) -> List[CookieAccount]:
    text = path.read_text(encoding="utf-8")
    ms_token = ""
    lines: List[str] = []
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        if platform == "dy" and s.lower().startswith("mstoken="):
            ms_token = s.split("=", 1)[1].strip()
            continue
        lines.append(s.rstrip(";"))
    cookie = "; ".join(lines).strip()
    if not cookie and text.strip().startswith("{"):
        return _accounts_from_legacy_obj(json.loads(text), platform=platform)
    if not cookie:
        return []
    acc = CookieAccount(
        name=f"{platform}_1",
        cookie=cookie,
        ms_token=ms_token or os.environ.get("DY_MSTOKEN", "").strip(),
        enabled=True,
    )
    return [acc]


def _load_unified_file() -> Optional[Dict[str, Any]]:
    path = _resolve_existing(UNIFIED_COOKIE_FILES)
    if not path:
        env_path = (os.environ.get("COOKIES_FILE") or "").strip()
        if env_path and Path(env_path).is_file():
            path = Path(env_path)
    if not path:
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise RuntimeError(f"cookies 文件必须是 JSON 对象: {path}")
    return data


def load_accounts(
    platform: str,
    *,
    account_name: str = "",
    include_disabled: bool = False,
) -> List[CookieAccount]:
    """加载某平台全部 cookie；account_name 可为 xhs_1 / 1 / 下标。"""
    platform = _normalize_platform(platform)
    accounts: List[CookieAccount] = []

    env_key = PLATFORM_ENV.get(platform)
    env_cookie = (os.environ.get(env_key or "") or "").strip() if env_key else ""
    if env_cookie:
        accounts = [
            CookieAccount(
                name="env",
                cookie=env_cookie,
                ms_token=os.environ.get("DY_MSTOKEN", "").strip()
                if platform == "dy"
                else "",
                enabled=True,
            )
        ]
    else:
        unified = _load_unified_file()
        if unified is not None:
            raw = unified.get(platform)
            if raw is None and platform == "dyhot":
                # 热点宝可复用 dy cookie
                raw = unified.get("dy")
            accounts = _accounts_from_platform_list(raw, platform=platform)
        else:
            json_path = _resolve_existing(PLATFORM_LEGACY_JSON.get(platform, []))
            if json_path:
                data = json.loads(json_path.read_text(encoding="utf-8"))
                accounts = _accounts_from_legacy_obj(data, platform=platform)
            else:
                txt_path = _resolve_existing(PLATFORM_LEGACY_TXT.get(platform, []))
                if txt_path:
                    accounts = _parse_legacy_txt(txt_path, platform)

    if not include_disabled:
        accounts = [a for a in accounts if a.enabled and a.cookie.strip()]

    if account_name:
        wanted = account_name.strip()
        matched = [a for a in accounts if a.name == wanted]
        if not matched and wanted.isdigit():
            idx = int(wanted)
            # 支持 1-based 与 0-based
            if 1 <= idx <= len(accounts):
                matched = [accounts[idx - 1]]
            elif 0 <= idx < len(accounts):
                matched = [accounts[idx]]
        if not matched:
            raise RuntimeError(
                f"未找到账号 {wanted!r} 的 {platform} cookie（可用 name 或序号）"
            )
        accounts = matched

    if not accounts:
        raise RuntimeError(
            f"未找到 {platform} cookie：在 cookies/cookies.json 写入 "
            f'{{"{platform}": ["cookie字符串"]}}，或设置环境变量 {env_key or ""}。'
            f"示例见 examples/cookies/cookies.json"
        )
    return accounts


def load_primary_account(platform: str, *, account_name: str = "") -> CookieAccount:
    return load_accounts(platform, account_name=account_name)[0]


def cookies_json_path() -> Path:
    path = _resolve_existing(UNIFIED_COOKIE_FILES)
    if path:
        return path
    return ROOT / "cookies" / "cookies.json"


def load_cookies_file() -> Dict[str, Any]:
    path = cookies_json_path()
    if path.is_file():
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    return {"xhs": [], "dy": [], "dyhot": [], "ks": []}


def save_platform_cookie(
    platform: str,
    cookie: str,
    *,
    replace: bool = False,
) -> Path:
    """把 cookie 字符串写入 cookies/cookies.json 对应平台数组。

    replace=True：覆盖该平台全部条目；否则按 web_session/sessionid 去重后追加/更新。
    """
    platform = _normalize_platform(platform)
    cookie = _normalize_cookie_text(cookie)
    if not cookie:
        raise ValueError("空 cookie，无法保存")

    path = cookies_json_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    data = load_cookies_file()
    for key in ("xhs", "dy", "dyhot", "ks"):
        data.setdefault(key, [])
        if not isinstance(data[key], list):
            data[key] = []

    if replace:
        data[platform] = [cookie]
    else:
        jar = {}
        for part in cookie.split(";"):
            part = part.strip()
            if "=" in part:
                k, v = part.split("=", 1)
                jar[k.strip()] = v.strip()
        key_name = "web_session" if platform == "xhs" else "sessionid"
        identity = jar.get(key_name) or jar.get("a1") or ""
        if platform == "ks" and not identity:
            identity = jar.get("userId") or jar.get("ud") or jar.get("userid") or ""
        existing: List[str] = list(data.get(platform) or [])
        updated = False
        if identity:
            new_list: List[str] = []
            for old in existing:
                old_jar = {}
                for part in old.split(";"):
                    part = part.strip()
                    if "=" in part:
                        k, v = part.split("=", 1)
                        old_jar[k.strip()] = v.strip()
                old_id = old_jar.get(key_name) or old_jar.get("a1") or ""
                if old_id and old_id == identity:
                    new_list.append(cookie)
                    updated = True
                else:
                    new_list.append(old)
            if not updated:
                new_list.append(cookie)
            data[platform] = new_list
        else:
            if cookie not in existing:
                existing.append(cookie)
            data[platform] = existing

    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return path


def _cookie_identity(platform: str, cookie: str) -> str:
    platform = _normalize_platform(platform)
    jar: Dict[str, str] = {}
    for part in (cookie or "").split(";"):
        part = part.strip()
        if "=" in part:
            k, v = part.split("=", 1)
            jar[k.strip()] = v.strip()
    key_name = "web_session" if platform == "xhs" else "sessionid"
    identity = jar.get(key_name) or jar.get("a1") or ""
    if platform == "ks" and not identity:
        identity = jar.get("userId") or jar.get("ud") or jar.get("userid") or ""
    return identity


def remove_platform_cookies(
    platform: str,
    cookies: List[str],
) -> Path:
    """从 cookies.json 删除指定 cookie 字符串（精确匹配，或同 web_session/sessionid）。"""
    platform = _normalize_platform(platform)
    targets = [_normalize_cookie_text(c) for c in (cookies or []) if (c or "").strip()]
    if not targets:
        return cookies_json_path()

    target_set = set(targets)
    target_ids = {
        _cookie_identity(platform, c) for c in targets if _cookie_identity(platform, c)
    }

    path = cookies_json_path()
    data = load_cookies_file()
    for key in ("xhs", "dy", "dyhot", "ks"):
        data.setdefault(key, [])
        if not isinstance(data[key], list):
            data[key] = []

    existing: List[str] = list(data.get(platform) or [])
    kept: List[str] = []
    for old in existing:
        old_n = _normalize_cookie_text(old)
        old_id = _cookie_identity(platform, old_n)
        if old_n in target_set or (old_id and old_id in target_ids):
            continue
        kept.append(old)
    data[platform] = kept

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return path


def parse_keywords(*parts: str) -> List[str]:
    """支持空格多参数与中英文逗号分隔。"""
    out: List[str] = []
    for part in parts:
        for piece in re.split(r"[,，]+", part or ""):
            kw = piece.strip()
            if kw and kw not in out:
                out.append(kw)
    return out
