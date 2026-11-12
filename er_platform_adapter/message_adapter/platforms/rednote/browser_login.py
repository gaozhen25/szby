"""Rednote web login via headed Chrome, same flow as Douyin.

Clear the managed profile, open the QR page, then export cookie and account
info from that same browser session. device_id is a fixed value derived from
the account UID, matching Douyin's stable device identity.
"""

from __future__ import annotations

import asyncio
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from message_adapter.browser_profiles import BrowserProfile
from message_adapter.storage import CredentialStore

from .credentials import save_rednote_cookie, web_session_from_cookie
from .im_ws import stable_device_id

REDNOTE_HOME = "https://www.xiaohongshu.com"
REDNOTE_EXPLORE = "https://www.xiaohongshu.com/explore"
REDNOTE_LOGIN = "https://www.xiaohongshu.com/login"
USER_ME_URL = "https://edith.xiaohongshu.com/api/sns/web/v2/user/me"


@dataclass
class RednoteBrowserLoginResult:
    cookie: str
    web_session: str
    user_id: str
    device_id: str
    nickname: str = ""
    red_id: str = ""


async def export_rednote_cookie_str(context: Any) -> str:
    """Convert the Playwright cookie jar to a Rednote cookie header."""
    jar = await context.cookies()
    parts: list[str] = []
    seen: set[str] = set()
    for item in jar or []:
        domain = str(item.get("domain") or "")
        if "xiaohongshu.com" not in domain:
            continue
        name = str(item.get("name") or "").strip()
        if not name or name in seen:
            continue
        seen.add(name)
        parts.append(f"{name}={item.get('value') or ''}")
    cookie_str = "; ".join(parts)
    if "web_session=" not in cookie_str:
        return ""
    return cookie_str


async def extract_self_profile_from_page(page: Any) -> dict[str, str]:
    """Only trust /user/me. Prefer the edith API host used by the real web app."""
    empty = {"nickname": "", "red_id": "", "user_id": "", "guest": ""}
    script = """
    async (userMeUrl) => {
      const pick = (j) => {
        const data = (j && (j.data || j)) || {};
        const nickname = String(data.nickname || data.nick_name || data.userName || '').trim();
        const red_id = String(data.red_id || data.redId || '').trim();
        const user_id = String(data.user_id || data.userId || data.id || '').trim();
        const guest = data.guest === true || data.guest === 'true' || data.guest === 1
          || data.code === -100 || j.code === -100
          || ((j.success === false) && !user_id);
        return {nickname, red_id, user_id, guest: guest ? '1' : ''};
      };
      const urls = [userMeUrl, '/api/sns/web/v2/user/me'];
      for (const url of urls) {
        try {
          const r = await fetch(url, {
            credentials: 'include',
            headers: { accept: 'application/json, text/plain, */*' },
          });
          const j = await r.json();
          const hit = pick(j);
          if (hit.user_id || hit.guest) return hit;
        } catch (e) {}
      }
      return {nickname: '', red_id: '', user_id: '', guest: ''};
    }
    """
    try:
        data = await page.evaluate(script, USER_ME_URL)
    except Exception:
        return empty
    if not isinstance(data, dict):
        return empty
    return {
        "nickname": str(data.get("nickname") or "").strip(),
        "red_id": str(data.get("red_id") or "").strip(),
        "user_id": str(data.get("user_id") or "").strip(),
        "guest": str(data.get("guest") or "").strip(),
    }


async def profile_from_cookie(cookie_str: str) -> dict[str, str]:
    """Signed HTTP fallback when the page fetch is still settling after scan."""
    empty = {"nickname": "", "red_id": "", "user_id": "", "guest": ""}
    if "web_session=" not in cookie_str:
        return empty
    try:
        from .client import RednoteClient

        me = await asyncio.to_thread(RednoteClient(cookie=cookie_str).user_me)
    except Exception:
        return empty
    if not isinstance(me, dict):
        return empty
    user_id = str(me.get("user_id") or me.get("userId") or "").strip()
    guest = me.get("guest") is True or me.get("guest") in {"true", 1} or not user_id
    return {
        "nickname": str(me.get("nickname") or "").strip(),
        "red_id": str(me.get("red_id") or me.get("redId") or "").strip(),
        "user_id": user_id,
        "guest": "1" if guest else "",
    }


async def login_qr_still_visible(page: Any) -> bool:
    """Return True while the QR login panel is still on screen."""
    script = """
    () => {
      const imgs = Array.from(document.querySelectorAll('img, canvas'));
      const hasQrImage = imgs.some((node) => {
        const cls = String(node.className || '').toLowerCase();
        const src = String(node.getAttribute && node.getAttribute('src') || '').toLowerCase();
        return cls.includes('qrcode') || src.includes('qrcode');
      });
      if (hasQrImage) return true;
      const body = String(document.body && document.body.innerText || '');
      return body.includes('扫码登录') || body.includes('打开小红书App') || body.includes('打开小红书 APP');
    }
    """
    try:
        return bool(await page.evaluate(script))
    except Exception:
        return False


async def try_open_login_qr(page: Any) -> None:
    try:
        await page.goto(REDNOTE_LOGIN, wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_timeout(1200)
        if await login_qr_still_visible(page):
            return
    except Exception:
        pass
    try:
        await page.goto(REDNOTE_HOME, wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_timeout(1000)
    except Exception:
        pass
    try:
        await page.evaluate(
            """() => {
                const nodes = Array.from(document.querySelectorAll('button, span, div, a'));
                const hit = nodes.find(n =>
                    ['登录','登 录','Log in'].includes((n.textContent||'').trim())
                );
                if (hit) hit.click();
            }"""
        )
        await page.wait_for_timeout(1000)
        return
    except Exception:
        pass
    for selector in ('text="登录"', "text=登录", "button:has-text('登录')"):
        try:
            locator = page.locator(selector).first
            if await locator.is_visible(timeout=1500):
                await locator.click(timeout=3000)
                await page.wait_for_timeout(1000)
                return
        except Exception:
            continue


def _progress(message: str, on_status: Callable[[str], None] | None = None) -> None:
    print(f"[rednote] {message}", file=sys.stderr, flush=True)
    if on_status:
        on_status(message)


def _logged_in(profile_data: dict[str, str]) -> bool:
    return bool(profile_data.get("user_id")) and not profile_data.get("guest")


async def _settle_after_scan(page: Any) -> None:
    for url in (REDNOTE_EXPLORE, REDNOTE_HOME):
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(1500)
            return
        except Exception:
            continue


async def grab_with_qr(
    *,
    profile: BrowserProfile,
    timeout_s: int = 300,
    on_status: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Keep the QR window open until a real non-guest account is confirmed.

    Guest pages also mint a ``web_session`` cookie — that alone is not login.
    Never leave the login page until ``/user/me`` returns a non-guest UID.
    """
    async with profile.launch() as context:
        page = context.pages[0] if context.pages else await context.new_page()
        await try_open_login_qr(page)
        _progress("请在弹出的 Google Chrome 窗口里用小红书 App 扫码登录…", on_status)
        deadline = time.time() + timeout_s
        last_status = ""
        while time.time() < deadline:
            await asyncio.sleep(2)
            cookie_str = await export_rednote_cookie_str(context)
            profile_data = await extract_self_profile_from_page(page)
            if not _logged_in(profile_data) and cookie_str:
                profile_data = await profile_from_cookie(cookie_str)

            if not _logged_in(profile_data):
                # Guest web_session is normal before scan. Stay on / reopen QR.
                if not await login_qr_still_visible(page):
                    status = "登录页未显示二维码，正在重新打开…"
                    if status != last_status:
                        _progress(status, on_status)
                        last_status = status
                    await try_open_login_qr(page)
                continue

            # Real account confirmed — only then settle cookies on the main site.
            _progress("扫码成功，正在进入主站稳定会话…", on_status)
            await _settle_after_scan(page)
            cookie_str = await export_rednote_cookie_str(context) or cookie_str
            settled = await extract_self_profile_from_page(page)
            if not _logged_in(settled):
                settled = await profile_from_cookie(cookie_str)
            if _logged_in(settled):
                profile_data = settled
            if not cookie_str or not _logged_in(profile_data):
                _progress("账号已识别，会话还在写入，请稍候…", on_status)
                continue

            user_id = str(profile_data.get("user_id") or "").strip()
            device_id = stable_device_id(user_id)
            try:
                from .im_ws import fetch_login_token

                token = await asyncio.to_thread(fetch_login_token, cookie_str, device_id)
                if not str(token.get("a_lt") or "").strip():
                    raise RuntimeError("missing a_lt")
            except Exception as exc:
                _progress(f"账号已识别，消息通道凭据未就绪，继续等待… ({exc})", on_status)
                continue
            return {
                "_cookie_str": cookie_str,
                "_user_id": user_id,
                "_nickname": profile_data.get("nickname") or "",
                "_red_id": profile_data.get("red_id") or "",
                "_device_id": device_id,
            }
        raise TimeoutError("扫码超时：仍未拿到小红书真实登录账号")


async def login_interactive(
    *,
    profile: BrowserProfile,
    headless: bool = False,
    login_timeout_s: int = 300,
    on_status: Callable[[str], None] | None = None,
) -> RednoteBrowserLoginResult:
    """扫码登录并在同一次会话抓取 cookie + 固定 device_id + 账号 UID。"""
    if headless:
        raise RuntimeError("扫码登录需要有界面浏览器，请去掉 --headless")

    _progress("正在打开小红书网页，请扫码登录…", on_status)
    timeout_s = max(int(login_timeout_s or 0), 180)
    try:
        raw = await grab_with_qr(profile=profile, timeout_s=timeout_s, on_status=on_status)
    except TimeoutError:
        raise
    except Exception as exc:
        raise RuntimeError(f"扫码登录失败: {exc}") from exc

    cookie_str = str(raw.get("_cookie_str") or "")
    session = web_session_from_cookie(cookie_str)
    user_id = str(raw.get("_user_id") or "").strip()
    nickname = str(raw.get("_nickname") or "").strip()
    red_id = str(raw.get("_red_id") or "").strip()
    if not session or not user_id:
        raise TimeoutError("扫码会话已建立，但 cookie / UID 不完整，请重新扫码登录")
    device_id = str(raw.get("_device_id") or "").strip() or stable_device_id(user_id)

    if not nickname:
        try:
            from .client import RednoteClient
            from .im import account_summary

            me = await asyncio.to_thread(account_summary, RednoteClient(cookie=cookie_str))
            nickname = nickname or str(me.get("nickname") or "").strip()
            red_id = red_id or str(me.get("red_id") or "").strip()
            user_id = user_id or str(me.get("user_id") or "").strip()
            device_id = stable_device_id(user_id)
        except Exception:
            pass

    cookie_keys = len([part for part in cookie_str.split(";") if part.strip()])
    _progress(
        f"扫码成功 web_session=yes device_id={device_id} "
        f"cookie_keys={cookie_keys} nickname={nickname or '-'}",
        on_status,
    )
    return RednoteBrowserLoginResult(
        cookie=cookie_str,
        web_session=session,
        user_id=user_id,
        device_id=device_id,
        nickname=nickname,
        red_id=red_id,
    )


def save_browser_login_result(
    result: RednoteBrowserLoginResult,
    *,
    store: CredentialStore,
    browser_profile: str = "",
) -> None:
    """Persist the Rednote cookie section in the device slot."""
    save_rednote_cookie(
        result.cookie,
        store=store,
        user_id=str(result.user_id or ""),
        nickname=str(result.nickname or ""),
        red_id=str(result.red_id or ""),
        device_id=str(result.device_id or ""),
        browser_profile=browser_profile,
        source="browser:qr",
    )
