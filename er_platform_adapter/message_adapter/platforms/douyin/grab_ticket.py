"""Grab Douyin web_protect ticket (+ cookie) via Playwright.

The ticket comes from ``security-sdk/s_sdk_sign_data_key/web_protect`` and
the private key from ``security-sdk/s_sdk_crypt_sdk``. QR capture exports the
cookie and ticket from the same browser session.
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from typing import Any

from message_adapter.browser_profiles import BrowserProfile

from .credentials import sessionid_from_cookie

CRYPT_KEYS = ("security-sdk/s_sdk_crypt_sdk",)
PROTECT_KEYS = (
    "security-sdk/s_sdk_sign_data_key/web_protect",
    "security-sdk/s_sdk_sign_data_key/webprotect",
)


def _loads_nested(raw: str) -> dict[str, Any]:
    obj = json.loads(raw)
    if isinstance(obj, dict) and isinstance(obj.get("data"), str):
        try:
            inner = json.loads(obj["data"])
            if isinstance(inner, dict):
                return inner
        except Exception:
            pass
    return obj if isinstance(obj, dict) else {}


def parse_web_protect(web_protect_str: str, keys_str: str) -> dict[str, str]:
    web_protect = _loads_nested(web_protect_str)
    keys = _loads_nested(keys_str)
    return {
        "DY_TICKET": str(web_protect.get("ticket") or web_protect.get("Ticket") or ""),
        "DY_TS_SIGN": str(web_protect.get("ts_sign") or web_protect.get("tsSign") or ""),
        "DY_CLIENT_CERT": str(web_protect.get("client_cert") or web_protect.get("clientCert") or ""),
        "DY_PRIVATE_KEY": str(keys.get("ec_privateKey") or keys.get("ecPrivateKey") or keys.get("privateKey") or ""),
    }


async def export_douyin_cookie_str(context: Any) -> str:
    """Convert the Playwright cookie jar to a Douyin cookie header."""
    jar = await context.cookies()
    parts: list[str] = []
    seen: set[str] = set()
    for item in jar or []:
        domain = str(item.get("domain") or "")
        if "douyin.com" not in domain and "iesdouyin.com" not in domain:
            continue
        name = str(item.get("name") or "").strip()
        if not name or name in seen:
            continue
        seen.add(name)
        parts.append(f"{name}={item.get('value') or ''}")
    cookie_str = "; ".join(parts)
    if "sessionid=" not in cookie_str:
        return ""
    return cookie_str


async def extract_self_profile_from_page(page: Any) -> dict[str, str]:
    """在已登录的浏览器上下文里解析真实昵称（避免关掉浏览器后再用 requests 被风控）。"""
    empty = {"nickname": "", "unique_id": "", "uid": "", "sec_uid": ""}
    script = """
    async () => {
      const pick = (u) => {
        if (!u || typeof u !== 'object') return null;
        const nickname = String(u.nickname || u.nickName || u.nick_name || '').trim();
        const unique_id = String(u.unique_id || u.uniqueId || u.short_id || u.shortId || '').trim();
        const uid = String(u.uid || u.id || u.user_id || u.userId || '').trim();
        const sec_uid = String(u.sec_uid || u.secUid || u.sec_user_id || u.secUserId || '').trim();
        if (nickname || unique_id || uid) return {nickname, unique_id, uid, sec_uid};
        return null;
      };
      const walk = (node, depth=0) => {
        if (!node || depth > 8) return null;
        if (Array.isArray(node)) {
          for (const x of node) { const hit = walk(x, depth+1); if (hit) return hit; }
          return null;
        }
        if (typeof node !== 'object') return null;
        const direct = pick(node);
        if (direct && direct.nickname) return direct;
        for (const key of ['user', 'userInfo', 'user_info', 'userData', 'author', 'owner']) {
          if (node[key]) {
            const hit = pick(node[key]) || walk(node[key], depth+1);
            if (hit && (hit.nickname || hit.uid)) return hit;
          }
        }
        for (const v of Object.values(node)) {
          const hit = walk(v, depth+1);
          if (hit && hit.nickname) return hit;
        }
        return direct;
      };

      // 1) 页面内 fetch：与浏览器同源 cookie / 风控参数一致
      try {
        const url = '/aweme/v1/web/user/profile/self/?device_platform=webapp&aid=6383&channel=channel_pc_web';
        const r = await fetch(url, {credentials: 'include'});
        const j = await r.json();
        const hit = pick(j.user || j.user_info || (j.data && j.data.user));
        if (hit && (hit.nickname || hit.unique_id || hit.uid)) return hit;
      } catch (e) {}

      // 2) RENDER_DATA / 页面状态
      try {
        for (const el of document.querySelectorAll('script#RENDER_DATA, script[id^="RENDER_DATA"]')) {
          let text = el.textContent || '';
          try { text = decodeURIComponent(text); } catch (e) {}
          try {
            const hit = walk(JSON.parse(text));
            if (hit && (hit.nickname || hit.uid)) return hit;
          } catch (e) {}
        }
      } catch (e) {}

      // 3) 常见全局变量
      try {
        const globals = [window.__user__, window.USER, window._USER,
          window._SSR_HYDRATED_DATA, window.__INITIAL_STATE__];
        for (const g of globals) {
          const hit = walk(g);
          if (hit && (hit.nickname || hit.uid)) return hit;
        }
      } catch (e) {}

      return {nickname:'', unique_id:'', uid:'', sec_uid:''};
    }
    """
    try:
        data = await page.evaluate(script)
    except Exception:
        return dict(empty)
    if not isinstance(data, dict):
        return dict(empty)
    return {
        "nickname": str(data.get("nickname") or "").strip(),
        "unique_id": str(data.get("unique_id") or "").strip(),
        "uid": str(data.get("uid") or "").strip(),
        "sec_uid": str(data.get("sec_uid") or "").strip(),
    }


async def try_open_login_qr(page: Any) -> None:
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
    selectors = (
        'text="登录"',
        "text=登录",
        '[data-e2e="login"]',
        'button:has-text("登录")',
    )
    for sel in selectors:
        try:
            loc = page.locator(sel).first
            if await loc.is_visible(timeout=1500):
                await loc.click(timeout=3000)
                await page.wait_for_timeout(1000)
                return
        except Exception:
            continue
    try:
        await page.goto(
            "https://www.douyin.com/passport/web/login/",
            wait_until="domcontentloaded",
            timeout=60000,
        )
    except Exception:
        pass


async def read_ls_pair(page: Any) -> tuple[str, str, list[str]]:
    data = await page.evaluate(
        """([cryptKeys, protectKeys]) => {
            const all = Object.keys(localStorage);
            let keysStr = null, protectStr = null;
            for (const k of cryptKeys) {
                const v = localStorage.getItem(k);
                if (v) { keysStr = v; break; }
            }
            for (const k of protectKeys) {
                const v = localStorage.getItem(k);
                if (v) { protectStr = v; break; }
            }
            if (!keysStr || !protectStr) {
                for (const k of all) {
                    const low = k.toLowerCase();
                    const v = localStorage.getItem(k);
                    if (!v) continue;
                    if (!keysStr && (low.includes('crypt') || low.includes('private')))
                        keysStr = v;
                    if (!protectStr && (
                        low.includes('web_protect')
                        || low.includes('webprotect')
                        || (low.includes('sign') && low.includes('protect'))
                    ))
                        protectStr = v;
                }
            }
            return { keysStr, protectStr, all };
        }""",
        [list(CRYPT_KEYS), list(PROTECT_KEYS)],
    )
    return data.get("keysStr") or "", data.get("protectStr") or "", list(data.get("all") or [])


async def grab_with_qr(*, profile: BrowserProfile, timeout_s: int = 180) -> dict[str, Any]:
    """扫码登录后在同一个浏览器会话中同时抓取 cookie 与 ticket。

    返回 dict 含 DY_* 字段，以及 ``_cookie_str``（同源 session）。
    """
    async with profile.launch() as context:
        page = context.pages[0] if context.pages else await context.new_page()
        await page.goto("https://www.douyin.com/", wait_until="domcontentloaded", timeout=60000)
        await asyncio.sleep(2)
        await try_open_login_qr(page)
        print(
            "[ticket] 请在弹出的 Google Chrome 窗口里用抖音 App 扫码登录…",
            file=sys.stderr,
        )
        deadline = time.time() + timeout_s
        last_keys: list[str] = []
        while time.time() < deadline:
            await asyncio.sleep(2)
            try:
                keys_str, protect_str, last_keys = await read_ls_pair(page)
            except Exception:
                continue
            if keys_str and protect_str:
                cred = parse_web_protect(protect_str, keys_str)
                if cred["DY_TICKET"] and cred["DY_PRIVATE_KEY"]:
                    # 关掉浏览器前在页面上下文取真实昵称（requests 拉 profile 常被风控）
                    profile_data = await extract_self_profile_from_page(page)
                    if not profile_data.get("nickname"):
                        for url in (
                            "https://www.douyin.com/user/self",
                            "https://www.douyin.com/",
                        ):
                            try:
                                await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                                await page.wait_for_timeout(1500)
                                profile_data = await extract_self_profile_from_page(page)
                                if profile_data.get("nickname"):
                                    break
                            except Exception:
                                continue
                    cookie_str = await export_douyin_cookie_str(context)
                    print(
                        f"[ticket] 扫码成功 sessionid="
                        f"{'yes' if sessionid_from_cookie(cookie_str) else 'no'} "
                        f"cookie_keys={len(cookie_str.split('; ')) if cookie_str else 0} "
                        f"nickname={profile_data.get('nickname') or '-'}",
                        file=sys.stderr,
                    )
                    out: dict[str, Any] = dict(cred)
                    out["_cookie_str"] = cookie_str
                    out["_nickname"] = profile_data.get("nickname") or ""
                    out["_unique_id"] = profile_data.get("unique_id") or ""
                    out["_uid"] = profile_data.get("uid") or ""
                    return out
            # 登录后逛私信页，促发 web_protect
            if "login" not in page.url and time.time() + 45 > deadline:
                try:
                    await page.goto(
                        "https://www.douyin.com/message",
                        wait_until="domcontentloaded",
                        timeout=30000,
                    )
                except Exception:
                    pass
        securityish = [k for k in last_keys if any(x in k.lower() for x in ("security", "sdk", "protect", "sign", "crypt"))]
        raise TimeoutError(f"扫码超时：仍未抓到 web_protect。security 相关 key: {securityish[:20] or '无'}")
