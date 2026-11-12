# -*- coding: utf-8 -*-
"""登录工具：二维码解析、cookie 序列化。"""

from __future__ import annotations

import base64
import re
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import unquote


def cookies_to_header(cookies: List[Dict[str, Any]]) -> str:
    parts = []
    for c in cookies or []:
        name = (c.get("name") or "").strip()
        value = c.get("value")
        if not name or value is None:
            continue
        parts.append(f"{name}={value}")
    return "; ".join(parts)


def cookie_map(cookies: List[Dict[str, Any]]) -> Dict[str, str]:
    return {
        str(c.get("name") or ""): str(c.get("value") or "")
        for c in (cookies or [])
        if c.get("name")
    }


def parse_cookie_header(cookie: str) -> Dict[str, str]:
    """Cookie 请求头字符串 → dict。"""
    out: Dict[str, str] = {}
    for part in (cookie or "").split(";"):
        part = part.strip()
        if not part or "=" not in part:
            continue
        k, v = part.split("=", 1)
        out[k.strip()] = v.strip()
    return out


def decode_data_url_png(src: str) -> Optional[bytes]:
    """把 img src=data:image/png;base64,... 解成 bytes。"""
    if not src:
        return None
    m = re.match(
        r"data:image/(?:png|jpeg|jpg|webp);base64,(.+)",
        src.strip(),
        re.I | re.S,
    )
    if not m:
        return None
    try:
        return base64.b64decode(m.group(1))
    except Exception:
        return None


async def extract_qr_png(page, selectors: List[str]) -> Optional[bytes]:
    """从页面二维码 img 提取 PNG（支持 data URL / 远程 URL / 元素截图）。"""
    for sel in selectors:
        try:
            loc = page.locator(sel).first
            if await loc.count() == 0:
                continue
            if not await loc.is_visible():
                continue
            src = await loc.get_attribute("src") or ""
            if src.startswith("data:image"):
                raw = decode_data_url_png(src)
                if raw:
                    return raw
            if src.startswith("http"):
                try:
                    resp = await page.context.request.get(src)
                    if resp.ok:
                        body = await resp.body()
                        if body and len(body) > 64:
                            return body
                except Exception:
                    pass
            # 兜底：截元素图
            try:
                shot = await loc.screenshot(type="png")
                if shot:
                    return shot
            except Exception:
                pass
        except Exception:
            continue
    return None


def find_chrome() -> Optional[str]:
    import os
    import shutil

    env = (
        os.environ.get("LOGIN_CHROME_PATH")
        or os.environ.get("XHS_CHROME_PATH")
        or os.environ.get("CHROME_PATH")
        or ""
    ).strip()
    if env and Path(env).is_file():
        return env
    candidates = [
        "/usr/bin/google-chrome",
        "/usr/bin/google-chrome-stable",
        "/usr/bin/chromium",
        "/usr/bin/chromium-browser",
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Chromium.app/Contents/MacOS/Chromium",
        shutil.which("google-chrome") or "",
        shutil.which("chromium") or "",
        shutil.which("chromium-browser") or "",
    ]
    for p in candidates:
        if p and Path(p).is_file():
            return p
    return None
