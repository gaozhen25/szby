#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""导出小红书 + 抖音 Cookie（单文件）。

同步本机 Chrome 登录态 → 开一次浏览器 → 连续采集 → 写入 secrets/。

用法::

    uv run python scripts/export_cookies.py
    uv run python scripts/export_cookies.py --platforms xhs
    uv run python scripts/export_cookies.py --platforms dy
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

ROOT = Path(__file__).resolve().parents[1]
SECRETS = ROOT / "secrets"
POOL = SECRETS / "cookies.json"

URLS = {
    "xhs": ["https://www.xiaohongshu.com"],
    "dy": [
        "https://www.douyin.com",
        "https://douyin.com",
        "https://creator.douyin.com",
    ],
}
NEED = {
    "xhs": ("web_session",),
    "dy": ("sessionid", "LOGIN_STATUS"),
}


def _setup() -> None:
    os.chdir(ROOT)
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))


def _cfg() -> None:
    import config

    config.PLATFORM = "xhs"
    config.LOGIN_TYPE = "qrcode"
    config.COOKIES = ""
    config.HEADLESS = False
    config.CDP_HEADLESS = False
    config.ENABLE_CDP_MODE = True
    config.CDP_USE_SYSTEM_PROFILE = True
    config.CDP_CONNECT_EXISTING = False
    config.SAVE_LOGIN_STATE = False
    config.AUTO_CLOSE_BROWSER = True
    config.ENABLE_IP_PROXY = False


def _merge(cookies: Sequence[dict]) -> Tuple[str, Dict[str, str]]:
    m: Dict[str, str] = {}
    for c in cookies:
        n, v = c.get("name"), c.get("value")
        if n and v is not None:
            m[str(n)] = str(v)
    return ";".join(f"{k}={v}" for k, v in m.items()), m


def _write_one(platform: str, cookie: str) -> Path:
    SECRETS.mkdir(parents=True, exist_ok=True)
    path = SECRETS / f"{platform}.cookies.json"
    path.write_text(
        json.dumps({"platform": platform, "cookies": cookie}, ensure_ascii=False)
        + "\n",
        encoding="utf-8",
    )
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return path


def _load_pool(path: Path) -> Dict[str, List[str]]:
    pool: Dict[str, List[str]] = {"xhs": [], "dy": [], "ks": []}
    if not path.is_file():
        return pool
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return pool
    if not isinstance(data, dict):
        return pool
    for k in ("xhs", "dy", "ks"):
        v = data.get(k)
        if isinstance(v, list):
            pool[k] = [str(x).strip() for x in v if isinstance(x, str) and x.strip()]
        elif isinstance(v, str) and v.strip():
            pool[k] = [v.strip()]
    return pool


def _save_pool(path: Path, pool: Dict[str, List[str]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload: Dict[str, Any] = {
        "xhs": pool.get("xhs") or [],
        "dy": pool.get("dy") or [],
        "ks": pool.get("ks") or [],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return path


def _upsert(pool: Dict[str, List[str]], platform: str, cookie: str) -> None:
    cookie = cookie.strip()
    if not cookie:
        return
    items = pool.setdefault(platform, [])
    if cookie in items:
        return
    if items:
        items[0] = cookie
    else:
        items.append(cookie)


async def _logged_in(platform: str, ctx, page) -> bool:
    from tools import utils

    _, d = _merge(await ctx.cookies(urls=URLS[platform]))
    if platform == "dy":
        ok = d.get("LOGIN_STATUS") == "1" or bool(d.get("sessionid"))
        if ok:
            utils.logger.info("[export_cookies] 抖音已登录")
        return ok
    try:
        if await page.is_visible(
            "xpath=//a[contains(@href, '/user/profile/')]//span[text()='我']",
            timeout=500,
        ):
            utils.logger.info("[export_cookies] 小红书已登录")
            return True
    except Exception:
        pass
    if d.get("web_session"):
        utils.logger.info("[export_cookies] 小红书已有 web_session")
        return True
    return False


async def _login_xhs(ctx, page) -> None:
    from media_platform.xhs.login import XiaoHongShuLogin
    from tools import utils

    await page.goto("https://www.xiaohongshu.com", wait_until="domcontentloaded", timeout=60000)
    await asyncio.sleep(0.8)
    if await _logged_in("xhs", ctx, page):
        return
    if await page.locator("xpath=//img[@class='qrcode-img']").count() == 0:
        for sel in (
            "xpath=//*[@id='app']/div[1]/div[2]/div[1]/ul/div[1]/button",
            "xpath=//button[contains(., '登录')]",
            "text=登录",
        ):
            try:
                loc = page.locator(sel).first
                if await loc.count():
                    await loc.click(timeout=3000)
                    break
            except Exception:
                continue
    utils.logger.info("[export_cookies] 请扫码登录小红书")
    await XiaoHongShuLogin(
        login_type="qrcode",
        login_phone="",
        browser_context=ctx,
        context_page=page,
        cookie_str="",
    ).begin()


async def _login_dy(ctx, page) -> None:
    from media_platform.douyin.login import DouYinLogin
    from tools import utils

    await page.goto("https://www.douyin.com", wait_until="domcontentloaded", timeout=60000)
    await asyncio.sleep(0.5)
    if await _logged_in("dy", ctx, page):
        return
    utils.logger.info("[export_cookies] 请扫码登录抖音")
    await DouYinLogin(
        login_type="qrcode",
        login_phone="",
        browser_context=ctx,
        context_page=page,
        cookie_str="",
    ).begin()


async def _export_platform(platform: str, ctx, page) -> str:
    from tools import utils

    if platform == "xhs":
        await _login_xhs(ctx, page)
    else:
        await _login_dy(ctx, page)

    raw = await ctx.cookies(urls=URLS[platform])
    cookie, d = _merge(raw)
    if not cookie:
        raise RuntimeError(f"{platform} 未采到 Cookie")
    if not any(d.get(k) for k in NEED[platform]):
        utils.logger.warning(f"[export_cookies] {platform} 缺少常见字段，仍写入")
    path = _write_one(platform, cookie)
    utils.logger.info(f"[export_cookies] → {path} ({len(d)} 键)")
    return cookie


async def run(platforms: Sequence[str], pool_path: Path) -> Path:
    from playwright.async_api import async_playwright

    from tools import utils
    from tools.browser_launcher import BrowserLauncher
    from tools.cdp_browser import CDPBrowserManager

    _cfg()
    utils.logger.info(
        f"[export_cookies] 一次打开浏览器，连续导出: {', '.join(platforms)}"
    )
    utils.logger.info(
        f"[export_cookies] 同步日常 Chrome → clone "
        f"({BrowserLauncher.get_system_chrome_user_data_dir()})"
    )

    pool = _load_pool(pool_path)
    mgr = CDPBrowserManager()
    async with async_playwright() as pw:
        try:
            ctx = await mgr.launch_and_connect(pw, None, None, headless=False)
            try:
                await mgr.add_stealth_script()
            except Exception:
                pass
            utils.logger.info(f"[export_cookies] CDP: {await mgr.get_browser_info()}")
            page = await ctx.new_page()
            for p in platforms:
                print(f"\n===== {p} =====\n")
                cookie = await _export_platform(p, ctx, page)
                _upsert(pool, p, cookie)
                print(f"[export_cookies] {p} ok ({len(cookie)} chars)")
        finally:
            await mgr.cleanup()

    pool.setdefault("xhs", pool.get("xhs") or [])
    pool.setdefault("dy", pool.get("dy") or [])
    pool.setdefault("ks", pool.get("ks") or [])
    out = _save_pool(pool_path, pool)
    print(f"\n[export_cookies] done → {out}")
    print(f"  xhs={len(pool['xhs'])} dy={len(pool['dy'])} ks={len(pool['ks'])}")
    return out


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="导出小红书/抖音 Cookie")
    parser.add_argument("--platforms", default="xhs,dy", help="默认 xhs,dy")
    parser.add_argument("-o", "--output", default=str(POOL.relative_to(ROOT)))
    args = parser.parse_args(list(argv) if argv is not None else None)

    _setup()
    platforms = [p.strip() for p in args.platforms.split(",") if p.strip()]
    for p in platforms:
        if p not in ("xhs", "dy"):
            print(f"仅支持 xhs/dy: {p}", file=sys.stderr)
            return 2

    out = Path(args.output).expanduser()
    if not out.is_absolute():
        out = (ROOT / out).resolve()

    try:
        asyncio.run(run(platforms, out))
    except KeyboardInterrupt:
        print("\n已取消", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"导出失败: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
