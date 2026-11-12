# -*- coding: utf-8 -*-
"""小红书扫码登录（Playwright），Cookie 写入项目根 xhs/cookies.json。"""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from typing import Any

from boss_cli.constants import XHS_DIR

from .credentials import save_xhs_cookie
from .login_util import cookie_map, cookies_to_header, extract_qr_png, find_chrome

logger = logging.getLogger(__name__)

XHS_HOME = "https://www.xiaohongshu.com"
QR_SELECTORS = [
    "img.qrcode-img",
    "img[class*='qrcode']",
    ".qrcode-img",
    "img[src*='qrcode']",
]
LOGIN_BTNS = [
    "button:has-text('登录')",
    "text=登录",
]


async def _open_login_qr(page) -> None:
    await page.goto(XHS_HOME, wait_until="domcontentloaded", timeout=60000)
    await page.wait_for_timeout(800)
    for sel in LOGIN_BTNS:
        try:
            btn = page.locator(sel).first
            if await btn.count() and await btn.is_visible():
                await btn.click(timeout=3000)
                await page.wait_for_timeout(800)
                break
        except Exception:
            continue


async def run_xhs_qr_login(
    *,
    account_name: str = "",
    timeout: float = 180,
    headed: bool = True,
) -> dict[str, Any]:
    """打开浏览器扫码；成功后写入 xhs/cookies.json。"""
    try:
        from playwright.async_api import async_playwright
    except ImportError as exc:
        raise RuntimeError(
            "未安装 playwright。请执行: uv sync && uv run playwright install chromium"
        ) from exc

    if not headed:
        raise RuntimeError("扫码登录需要有界面浏览器，请去掉 --headless")

    profile_dir = XHS_DIR / "login_profiles" / (account_name or "default")
    profile_dir.mkdir(parents=True, exist_ok=True)

    async with async_playwright() as p:
        chrome = find_chrome()
        launch_kwargs: dict[str, Any] = {
            "headless": False,
            "args": [
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
            ],
        }
        if chrome:
            launch_kwargs["executable_path"] = chrome

        context = await p.chromium.launch_persistent_context(
            str(profile_dir),
            **launch_kwargs,
            viewport={"width": 1280, "height": 860},
            locale="zh-CN",
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0.0.0 Safari/537.36"
            ),
        )
        try:
            try:
                await context.clear_cookies()
            except Exception:
                pass
            page = context.pages[0] if context.pages else await context.new_page()
            print("[xhs] 正在打开小红书网页，请用 App 扫码登录…", flush=True)
            await _open_login_qr(page)

            # 有界面浏览器里已展示二维码，不再截图落盘
            qr = await extract_qr_png(page, QR_SELECTORS)
            if not qr:
                await _open_login_qr(page)
                qr = await extract_qr_png(page, QR_SELECTORS)
            if not qr:
                # 截不到也不阻断：用户仍可直接扫浏览器窗口内的码
                print("[xhs] 未截到二维码节点，请直接扫浏览器窗口内的码", flush=True)
            else:
                print("[xhs] 请扫浏览器窗口内的二维码", flush=True)

            deadline = time.time() + timeout
            while time.time() < deadline:
                cookies = await context.cookies()
                jar = cookie_map(cookies)
                if jar.get("web_session"):
                    await page.wait_for_timeout(1500)
                    header = cookies_to_header(await context.cookies())
                    profile: dict[str, str] = {}
                    try:
                        from .client import XhsClient

                        me = XhsClient(cookie=header).user_me() or {}
                        if me.get("guest"):
                            print("[xhs] 已扫码，请在浏览器/手机完成验证…", flush=True)
                            await asyncio.sleep(2)
                            continue
                        profile = {
                            "nickname": str(me.get("nickname") or ""),
                            "red_id": str(me.get("red_id") or me.get("redId") or ""),
                            "user_id": str(me.get("user_id") or me.get("userId") or ""),
                        }
                    except Exception as exc:
                        logger.debug("user_me after scan failed: %s", exc)
                        profile = {}

                    if not profile.get("user_id") and not profile.get("nickname"):
                        print("[xhs] 已扫码，请完成短信/安全验证…", flush=True)
                        await asyncio.sleep(2)
                        continue

                    name = account_name or profile.get("nickname") or profile.get("red_id") or ""
                    cred = save_xhs_cookie(
                        header,
                        account_name=name,
                        source="browser:qr",
                        user_id=profile.get("user_id") or "",
                        red_id=profile.get("red_id") or "",
                        nickname=profile.get("nickname") or "",
                    )
                    print(
                        f"[xhs] 登录成功 account={cred.name} "
                        f"nickname={cred.nickname!r} user_id={cred.user_id}",
                        flush=True,
                    )
                    return {
                        "ok": True,
                        "name": cred.name,
                        "nickname": cred.nickname,
                        "user_id": cred.user_id,
                        "red_id": cred.red_id,
                    }

                try:
                    text = await page.inner_text("body")
                except Exception:
                    text = ""
                if any(x in text for x in ("二次验证", "安全验证", "短信验证", "请完成验证")):
                    print("[xhs] 需要二次验证，请在打开的浏览器完成", flush=True)

                await asyncio.sleep(2)

            raise RuntimeError(f"扫码超时（{int(timeout)}s）")
        finally:
            # persistent context 在部分机器上 close 会挂起，限时强制退出，避免登录成功后仍占终端
            try:
                await asyncio.wait_for(context.close(), timeout=3)
            except Exception:
                try:
                    browser = getattr(context, "browser", None)
                    if browser is not None:
                        await asyncio.wait_for(browser.close(), timeout=2)
                except Exception:
                    pass


def login_qr(*, account_name: str = "", timeout: float = 180) -> dict[str, Any]:
    return asyncio.run(
        run_xhs_qr_login(account_name=account_name, timeout=timeout, headed=True)
    )
