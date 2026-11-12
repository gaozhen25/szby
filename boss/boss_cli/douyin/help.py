# -*- coding: utf-8 -*-
"""抖音 a_bogus 签名（复用 MediaCrawler/libs/douyin.js）"""

from __future__ import annotations

import os
import random
import re
from pathlib import Path
from typing import Dict, Optional, Tuple

import execjs

_JS_PATH = Path(__file__).resolve().parent / "vendor" / "douyin.js"
_CTX = None


def _ctx():
    global _CTX
    if _CTX is None:
        _CTX = execjs.compile(_JS_PATH.read_text(encoding="utf-8-sig"))
    return _CTX


def get_web_id() -> str:
    def e(t):
        if t is not None:
            return str(t ^ (int(16 * random.random()) >> (t // 4)))
        return "".join(
            [
                str(int(1e7)),
                "-",
                str(int(1e3)),
                "-",
                str(int(4e3)),
                "-",
                str(int(8e3)),
                "-",
                str(int(1e11)),
            ]
        )

    web_id = "".join(e(int(x)) if x in "018" else x for x in e(None))
    return web_id.replace("-", "")[:19]


def get_a_bogus(query_string: str, user_agent: str, *, uri: str = "") -> str:
    """对已拼好的 query（不含 a_bogus）签名。"""
    name = "sign_reply" if "/reply" in uri else "sign_datail"
    return _ctx().call(name, query_string, user_agent)


def parse_cookie_str(cookie: str) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for part in cookie.split(";"):
        part = part.strip()
        if not part or "=" not in part:
            continue
        k, v = part.split("=", 1)
        out[k.strip()] = v.strip()
    return out


def _resolve_cookie_path(cookie_file: str) -> Optional[str]:
    candidates = [cookie_file]
    name = Path(cookie_file).name
    root = Path(__file__).resolve().parents[2]
    candidates.extend(
        [
            str(root / "cookies" / name),
            str(root / name),
            str(Path.cwd() / "cookies" / name),
            str(Path.cwd() / name),
        ]
    )
    for path in candidates:
        if path and os.path.isfile(path):
            return path
    return None


def load_dy_auth(cookie_file: str = "dy_cookie.txt") -> Tuple[str, Dict[str, str]]:
    """Return (cookie string, extra fields). Prefer boss-cli douyin credentials."""
    from .credentials import load_douyin_cookie

    extra: Dict[str, str] = {}
    ms = os.environ.get("DY_MSTOKEN", "").strip()
    if ms:
        extra["msToken"] = ms
    if cookie_file and cookie_file != "dy_cookie.txt":
        path = _resolve_cookie_path(cookie_file)
        if path:
            text = Path(path).read_text(encoding="utf-8").strip()
            if text and not text.startswith("{"):
                lines = []
                for line in text.splitlines():
                    s = line.strip()
                    if not s or s.startswith("#"):
                        continue
                    if s.lower().startswith("mstoken="):
                        extra["msToken"] = s.split("=", 1)[1].strip()
                        continue
                    lines.append(s)
                cookie = "; ".join(lines)
                if cookie:
                    return cookie, extra
    acc = load_douyin_cookie()
    if acc.cookie.split("msToken=")[-1] if "msToken=" in acc.cookie else "":
        pass
    return acc.cookie, extra



def parse_sec_user_id(url_or_id: str) -> str:
    text = (url_or_id or "").strip()
    if not text:
        raise ValueError("空的博主 ID/URL")
    if text.startswith("MS4wLjABAAAA") or (not text.startswith("http") and "douyin.com" not in text):
        return text.split("?")[0]
    m = re.search(r"/user/([^/?]+)", text)
    if m:
        return m.group(1)
    raise ValueError(f"无法解析 sec_user_id: {url_or_id}")


def parse_video_info_from_url(url_or_id: str) -> Dict[str, str]:
    """
    解析作品 URL / 纯 aweme_id（对齐 mediaspider parse_video_info_from_url）。

    支持:
    - 纯数字 ID
    - /video/{id}、/note/{id}
    - ?modal_id=
    - v.douyin.com 短链（url_type=short，需客户端 resolve）
    """
    from urllib.parse import parse_qs, urlparse

    text = (url_or_id or "").strip()
    if not text:
        raise ValueError("空的作品 URL/ID")
    if text.isdigit():
        return {"aweme_id": text, "url_type": "normal"}

    is_short = "v.douyin.com" in text or (
        text.startswith("http")
        and len(text) < 50
        and "/video/" not in text
        and "/note/" not in text
    )
    if is_short:
        return {"aweme_id": "", "url_type": "short"}

    params = parse_qs(urlparse(text).query)
    modal_id = (params.get("modal_id") or [""])[0]
    if modal_id:
        return {"aweme_id": modal_id, "url_type": "modal"}

    match = re.search(r"/(?:video|note)/(\d+)", text)
    if match:
        return {"aweme_id": match.group(1), "url_type": "normal"}

    raise ValueError(f"无法从 URL 解析 aweme_id: {url_or_id}")
