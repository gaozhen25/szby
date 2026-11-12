# -*- coding: utf-8 -*-
"""热点宝 cookie 加载。"""

from __future__ import annotations

from typing import Tuple

from platforms.common.cookies import load_primary_account


def load_dyhot_cookie() -> str:
    """优先 cookies/dyhot.json；兼容环境变量与旧版 txt。"""
    return load_primary_account("dyhot").cookie


def cookie_header_pair(cookie: str) -> Tuple[str, dict]:
    cookie = (cookie or "").strip()
    jar = {}
    for part in cookie.split(";"):
        part = part.strip()
        if not part or "=" not in part:
            continue
        k, v = part.split("=", 1)
        jar[k.strip()] = v.strip()
    return cookie, jar
