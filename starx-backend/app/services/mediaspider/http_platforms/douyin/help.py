# -*- coding: utf-8 -*-
"""抖音 a_bogus 签名（复用 MediaCrawler/libs/douyin.js）"""

from __future__ import annotations

import os
import random
import re
import threading
from pathlib import Path
from typing import Dict, Optional, Tuple

import quickjs

_JS_PATH = Path(__file__).resolve().parents[1] / "vendor" / "douyin.js"
_JS_SOURCE = _JS_PATH.read_text(encoding="utf-8-sig")
_THREAD_LOCAL = threading.local()


def _ctx():
    context = getattr(_THREAD_LOCAL, "context", None)
    if context is None:
        # QuickJS Context 具有线程亲和性，必须由使用它的 worker 线程自行创建。
        # 进程内执行避免了 PyExecJS 在 PM2 长驻进程里反复 fork Node 后触发
        # SIGABRT，同时每线程隔离也避免共享 Context 导致段错误。
        context = quickjs.Context()
        context.eval(_JS_SOURCE)
        _THREAD_LOCAL.context = context
    return context


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


def webid_from_cookie(cookie: str | Dict[str, str]) -> str:
    """优先用 Cookie 里的 s_v_web_id，避免每次随机 webid 与登录态指纹漂移。"""

    jar = cookie if isinstance(cookie, dict) else parse_cookie_str(cookie)
    for key in ("s_v_web_id", "s_v_webid", "webid"):
        value = str(jar.get(key) or "").strip()
        if value:
            return value
    return get_web_id()


def generate_ms_token(length: int = 107) -> str:
    """生成占位 msToken（浏览器 xmst 缺失时的兜底，降低空参触发风控概率）。"""

    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
    return "".join(random.choice(alphabet) for _ in range(max(32, int(length))))


def device_fingerprint_from_cookie(cookie: str | Dict[str, str]) -> Dict[str, str]:
    """从登录 Cookie 对齐屏幕/CPU 等公共参数。"""

    jar = cookie if isinstance(cookie, dict) else parse_cookie_str(cookie)
    out: Dict[str, str] = {}
    width = str(jar.get("dy_swidth") or "").strip()
    height = str(jar.get("dy_sheight") or "").strip()
    cpu = str(jar.get("device_web_cpu_core") or "").strip()
    memory = str(jar.get("device_web_memory_size") or "").strip()
    if width.isdigit():
        out["screen_width"] = width
    if height.isdigit():
        out["screen_height"] = height
    if cpu.isdigit():
        out["cpu_core_num"] = cpu
    if memory.isdigit():
        out["device_memory"] = memory
    return out


def get_a_bogus(query_string: str, user_agent: str, *, uri: str = "") -> str:
    """对已拼好的 query（不含 a_bogus）签名。"""
    name = "sign_reply" if "/reply" in uri else "sign_datail"
    return _ctx().get(name)(query_string, user_agent)


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
    """
    返回 (cookie字符串, 额外字段)
    优先 cookies/dy.json 多账号；兼容环境变量与旧版 txt。
    """
    from ..common.cookies import load_primary_account

    if cookie_file and cookie_file != "dy_cookie.txt":
        path = _resolve_cookie_path(cookie_file)
        if path:
            extra: Dict[str, str] = {}
            ms = os.environ.get("DY_MSTOKEN", "").strip()
            if ms:
                extra["msToken"] = ms
            text = Path(path).read_text(encoding="utf-8").strip()
            if text.startswith("{"):
                from ..common.cookies import _accounts_from_json_obj
                import json as _json

                accounts = _accounts_from_json_obj(_json.loads(text))
                if accounts:
                    acc = accounts[0]
                    if acc.ms_token:
                        extra["msToken"] = acc.ms_token
                    return acc.cookie, extra
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

    acc = load_primary_account("dy")
    extra = {}
    if acc.ms_token:
        extra["msToken"] = acc.ms_token
    elif os.environ.get("DY_MSTOKEN", "").strip():
        extra["msToken"] = os.environ.get("DY_MSTOKEN", "").strip()
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
