#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""多账号 Cookie 发现与读写。

推荐文件：``secrets/{platform}.cookies.json``（仅含 platform + cookies）::

    {"platform":"xhs","cookies":"web_session=...; a1=..."}

多账号：``secrets/{platform}.cookies.{id}.json``。
仍兼容旧纯文本 ``secrets/{platform}.cookies``。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
SECRETS_DIR = ROOT / "secrets"

PLATFORMS = ("xhs", "dy", "dyhot", "ks")


@dataclass(frozen=True)
class CookieAccount:
    platform: str
    account_id: str
    cookies: str  # 传给 --cookies 的整段字符串
    source: str
    cookies_dict: Optional[Dict[str, str]] = None


def _safe_account_id(name: str) -> str:
    name = (name or "default").strip() or "default"
    return re.sub(r"[^\w.-]+", "_", name)[:64]


def cookie_dict_to_str(cookie_dict: Dict[str, str]) -> str:
    return ";".join(f"{k}={v}" for k, v in cookie_dict.items() if k)


def cookie_str_to_dict(cookie_str: str) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for part in (cookie_str or "").split(";"):
        part = part.strip()
        if not part or "=" not in part:
            continue
        k, v = part.split("=", 1)
        k = k.strip()
        if k:
            out[k] = v.strip()
    return out


def _read_plaintext_segments(path: Path) -> List[Tuple[str, str]]:
    """旧格式：返回 [(account_id, cookie_str), ...]。"""
    text = path.read_text(encoding="utf-8")
    if re.search(r"(?m)^---\s*$", text):
        chunks = re.split(r"(?m)^---\s*$", text)
    else:
        chunks = [text]

    base_id = _account_id_from_filename(path)
    segments: List[Tuple[str, str]] = []
    for i, chunk in enumerate(chunks):
        lines: List[str] = []
        for line in chunk.splitlines():
            s = line.strip()
            if not s or s.startswith("#"):
                continue
            lines.append(s)
        if not lines:
            continue
        cookie = "".join(lines) if len(lines) > 1 else lines[0]
        aid = base_id if len(chunks) == 1 or i == 0 else f"{base_id}_{i + 1}"
        segments.append((_safe_account_id(aid), cookie))
    return segments


def _account_id_from_filename(path: Path) -> str:
    name = path.name
    for platform in PLATFORMS:
        if name == f"{platform}.cookies.json":
            return "default"
        if name == f"{platform}.cookies":
            return "default"
        prefix_json = f"{platform}.cookies."
        # xhs.cookies.1.json → handled as stem
        if name.startswith(prefix_json) and name.endswith(".json"):
            mid = name[len(prefix_json) : -len(".json")]
            return _safe_account_id(mid or "default")
        if name.startswith(prefix_json):
            return _safe_account_id(name[len(prefix_json) :])
    if name.endswith(".cookies.json"):
        return _safe_account_id(name[: -len(".cookies.json")])
    if name.endswith(".cookies"):
        return _safe_account_id(name[: -len(".cookies")])
    return _safe_account_id(path.stem)


def _parse_json_payload(data: Any, platform: str, path: Path) -> List[Tuple[str, str, Optional[Dict[str, str]]]]:
    """返回 [(id, cookie_str, cookies_dict|None), ...]。"""
    results: List[Tuple[str, str, Optional[Dict[str, str]]]] = []

    def add(aid: str, cookie: str, cdict: Optional[Dict[str, str]] = None) -> None:
        cookie = (cookie or "").strip()
        if not cookie and cdict:
            cookie = cookie_dict_to_str(cdict)
        if not cookie or "REPLACE_ME" in cookie:
            return
        results.append((_safe_account_id(aid), cookie, cdict))

    # Playwright 导出数组: [{"name","value"}, ...]
    if isinstance(data, list):
        cdict: Dict[str, str] = {}
        for item in data:
            if isinstance(item, dict) and item.get("name"):
                cdict[str(item["name"])] = str(item.get("value") or "")
        if cdict:
            add(_account_id_from_filename(path), cookie_dict_to_str(cdict), cdict)
        return results

    if not isinstance(data, dict):
        return results

    # 合并池 secrets/cookies.json：{"xhs":["..."],"dy":["..."],"ks":[]}
    if platform in data and isinstance(data.get(platform), list):
        for i, item in enumerate(data[platform]):
            if isinstance(item, str):
                aid = "default" if i == 0 else f"acc_{i + 1}"
                add(aid, item)
        if results:
            return results
    if platform in data and isinstance(data.get(platform), str):
        add("default", data[platform])
        if results:
            return results

    # 池格式 accounts
    accounts = data.get("accounts")
    if isinstance(accounts, list) and accounts:
        for i, acc in enumerate(accounts):
            if not isinstance(acc, dict):
                continue
            aid = acc.get("id") or acc.get("account_id") or f"acc_{i + 1}"
            cdict = acc.get("cookies") if isinstance(acc.get("cookies"), dict) else None
            cookie = acc.get("cookie") or acc.get("cookies_str") or ""
            if not cookie and isinstance(acc.get("cookies"), str):
                cookie = acc["cookies"]
            if cdict and not cookie:
                cookie = cookie_dict_to_str(cdict)
            add(str(aid), str(cookie), cdict)
        return results

    # 单账号对象
    cdict = data.get("cookies") if isinstance(data.get("cookies"), dict) else None
    cookie = data.get("cookie") or data.get("cookies_str") or ""
    if not cookie and isinstance(data.get("cookies"), str):
        cookie = data["cookies"]
    if cdict and not cookie:
        cookie = cookie_dict_to_str(cdict)
    aid = data.get("id") or data.get("account_id") or _account_id_from_filename(path)
    add(str(aid), str(cookie), cdict)
    return results


def load_accounts_from_file(platform: str, path: Path) -> List[CookieAccount]:
    """从单个文件加载账号列表。"""
    accounts: List[CookieAccount] = []
    suffix = path.suffix.lower()
    name = path.name.lower()

    if name.endswith(".json") or suffix == ".json":
        data = json.loads(path.read_text(encoding="utf-8"))
        for aid, cookie, cdict in _parse_json_payload(data, platform, path):
            accounts.append(
                CookieAccount(
                    platform=platform,
                    account_id=aid,
                    cookies=cookie,
                    source=str(path),
                    cookies_dict=cdict,
                )
            )
        return accounts

    # 旧纯文本
    for aid, cookie in _read_plaintext_segments(path):
        if "REPLACE_ME" in cookie:
            continue
        accounts.append(
            CookieAccount(
                platform=platform,
                account_id=aid,
                cookies=cookie,
                source=str(path),
                cookies_dict=cookie_str_to_dict(cookie),
            )
        )
    return accounts


def discover_cookie_files(platform: str, secrets_dir: Optional[Path] = None) -> List[Path]:
    """发现某平台 Cookie 文件：优先合并池 cookies.json，其次单平台 JSON，再次纯文本。"""
    base = secrets_dir or SECRETS_DIR
    found: List[Path] = []

    # 合并池
    pool = base / "cookies.json"
    if pool.is_file():
        found.append(pool)

    pool_json = base / f"{platform}.cookies.json"
    if pool_json.is_file():
        found.append(pool_json)

    for p in sorted(base.glob(f"{platform}.cookies.*.json")):
        if p.name.endswith(".example") or not p.is_file():
            continue
        found.append(p)

    alt_json = base / f"{platform}.json"
    if alt_json.is_file():
        found.append(alt_json)

    # 纯文本（无主 JSON 时才用默认 .cookies，避免重复）
    flat_txt = base / f"{platform}.cookies"
    if flat_txt.is_file() and not pool_json.is_file():
        found.append(flat_txt)

    for p in sorted(base.glob(f"{platform}.cookies.*")):
        if not p.is_file() or p.name.endswith(".example"):
            continue
        if p.suffix == ".json" or p.name.endswith(".json"):
            continue
        found.append(p)

    sub = base / platform
    if sub.is_dir():
        for p in sorted(list(sub.glob("*.cookies.json")) + list(sub.glob("*.cookies"))):
            if p.name.endswith(".example"):
                continue
            found.append(p)

    seen = set()
    out: List[Path] = []
    for p in found:
        key = str(p.resolve())
        if key in seen:
            continue
        seen.add(key)
        out.append(p)
    return out


def default_cookie_path(platform: str, secrets_dir: Optional[Path] = None) -> Path:
    return (secrets_dir or SECRETS_DIR) / f"{platform}.cookies.json"


def default_json_path(platform: str, secrets_dir: Optional[Path] = None) -> Path:
    return (secrets_dir or SECRETS_DIR) / f"{platform}.cookies.json"


def load_accounts_for_platform(
    platform: str,
    *,
    secrets_dir: Optional[Path] = None,
    cookies_files: Optional[Iterable[str]] = None,
) -> List[CookieAccount]:
    if platform not in PLATFORMS:
        raise ValueError(f"不支持的平台: {platform}")

    paths: List[Path] = []
    if cookies_files:
        for item in cookies_files:
            path = Path(item).expanduser()
            if not path.is_absolute():
                path = (ROOT / path).resolve()
            if not path.is_file():
                raise FileNotFoundError(f"Cookie 文件不存在: {path}")
            paths.append(path)
    else:
        paths = discover_cookie_files(platform, secrets_dir)

    accounts: List[CookieAccount] = []
    for path in paths:
        for acc in load_accounts_from_file(platform, path):
            account_id = acc.account_id
            while any(a.account_id == account_id for a in accounts):
                account_id = f"{account_id}_x"
            if account_id != acc.account_id:
                acc = CookieAccount(
                    platform=acc.platform,
                    account_id=account_id,
                    cookies=acc.cookies,
                    source=acc.source,
                    cookies_dict=acc.cookies_dict,
                )
            accounts.append(acc)
    return accounts


def read_cookie_string(path: Path, platform: Optional[str] = None) -> str:
    """读取文件中的第一段可用 Cookie 字符串（供 run_with_cookies 单账号）。"""
    if not platform:
        platform = "xhs"
        if path.name == "cookies.json":
            raise ValueError("读取 cookies.json 时必须指定 platform")
        for p in PLATFORMS:
            if path.name.startswith(p):
                platform = p
                break
    accounts = load_accounts_from_file(platform, path)
    if not accounts:
        raise ValueError(f"Cookie 文件无有效 {platform} 账号: {path}")
    return accounts[0].cookies


def write_cookie_json(
    path: Path,
    *,
    platform: str,
    cookie_str: str,
    cookie_dict: Optional[Dict[str, str]] = None,
    account_id: str = "default",
    merge: bool = True,
) -> Path:
    """写入精简 JSON：仅 platform + cookies。"""
    _ = cookie_dict, account_id, merge
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "platform": platform,
        "cookies": cookie_str.strip().replace("\n", "").replace("\r", ""),
    }
    path.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return path

