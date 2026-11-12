#!/usr/bin/env python3
"""Grab Douyin web_protect ticket (+ cookie) via Playwright.

对齐 spider/js/scripts/dy_im_grab_ticket.py：
  - ticket 来自 localStorage ``security-sdk/s_sdk_sign_data_key/web_protect``
  - 私钥来自 ``security-sdk/s_sdk_crypt_sdk``
  - ``--qr``：同一次扫码会话里同时导出 cookie jar + ticket（同源 sessionid）
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from typing import Any

from boss_cli.constants import DOUYIN_COOKIE_FILE, DOUYIN_IM_CRED_FILE

from .credentials import (
    load_douyin_cookie,
    save_douyin_cookie,
    save_im_cred,
    sessionid_from_cookie,
)

CRYPT_KEYS = (
    "security-sdk/s_sdk_crypt_sdk",
)
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
        "DY_CLIENT_CERT": str(
            web_protect.get("client_cert") or web_protect.get("clientCert") or ""
        ),
        "DY_PRIVATE_KEY": str(
            keys.get("ec_privateKey")
            or keys.get("ecPrivateKey")
            or keys.get("privateKey")
            or ""
        ),
    }


async def export_douyin_cookie_str(context: Any) -> str:
    """Playwright cookie jar → cookies.json 用的 ; 拼接串（仅 douyin 域）。"""
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


async def prepare_page_for_ticket(page: Any) -> None:
    """Scroll/interact so security-sdk writes web_protect keys."""
    targets = (
        "https://www.douyin.com/",
        "https://www.douyin.com/user/self",
        "https://www.douyin.com/message",
        "https://www.douyin.com/follow",
    )
    for url in targets:
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=60000)
        except Exception:
            continue
        await page.wait_for_timeout(2000)
        for _ in range(4):
            try:
                await page.mouse.wheel(0, 800)
            except Exception:
                pass
            await page.wait_for_timeout(800)
        keys_str, protect_str, _ = await read_ls_pair(page)
        if keys_str and protect_str:
            return


async def poll_web_protect(page: Any, *, deadline: float) -> dict[str, str]:
    last_keys: list[str] = []
    while time.time() < deadline:
        try:
            keys_str, protect_str, last_keys = await read_ls_pair(page)
        except Exception:
            await asyncio.sleep(1.5)
            continue
        if keys_str and protect_str:
            cred = parse_web_protect(protect_str, keys_str)
            if cred["DY_TICKET"] and cred["DY_PRIVATE_KEY"]:
                return cred
        try:
            await page.mouse.wheel(0, 600)
        except Exception:
            pass
        await asyncio.sleep(2)
    securityish = [
        k
        for k in last_keys
        if any(x in k.lower() for x in ("security", "sdk", "protect", "sign", "crypt"))
    ]
    raise TimeoutError(
        "未抓到 web_protect / crypt keys。\n"
        f"  localStorage security 相关: {securityish[:20] or '无'}\n"
        "  请改用扫码: boss douyin login  或  boss douyin grab-ticket --qr"
    )


async def _launch(headless: bool):
    from playwright.async_api import async_playwright

    p = await async_playwright().start()
    browser = await p.chromium.launch(
        headless=headless,
        args=["--disable-blink-features=AutomationControlled"],
    )
    context = await browser.new_context(
        user_agent=(
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/122.0.0.0 Safari/537.36"
        ),
        locale="zh-CN",
        viewport={"width": 1280, "height": 800},
    )
    await context.add_init_script(
        "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
    )
    return p, browser, context


async def grab(cookie_str: str, *, headless: bool = True, timeout_s: int = 90) -> dict[str, str]:
    """旧路径：注入已有 cookie 再读 localStorage（常缺 web_protect，优先用 grab_with_qr）。"""
    p, browser, context = await _launch(headless)
    try:
        cookies = []
        for part in cookie_str.split(";"):
            part = part.strip()
            if "=" not in part:
                continue
            name, _, value = part.partition("=")
            name, value = name.strip(), value.strip()
            if name:
                cookies.append(
                    {"name": name, "value": value, "domain": ".douyin.com", "path": "/"}
                )
        await context.add_cookies(cookies)
        page = await context.new_page()
        await prepare_page_for_ticket(page)
        return await poll_web_protect(page, deadline=time.time() + timeout_s)
    finally:
        await browser.close()
        await p.stop()


async def grab_with_qr(*, timeout_s: int = 180) -> dict[str, Any]:
    """扫码登录后同时抓 cookie + ticket（与 spider dy_im_grab_ticket --qr 同思路）。

    返回 dict 含 DY_* 字段，以及 ``_cookie_str``（同源 session）。
    """
    p, browser, context = await _launch(headless=False)
    try:
        page = await context.new_page()
        await page.goto("https://www.douyin.com/", wait_until="domcontentloaded", timeout=60000)
        await asyncio.sleep(2)
        await try_open_login_qr(page)
        print(
            "[ticket] 请在弹出的 Chromium 窗口里用抖音 App 扫码登录…",
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
                    cookie_str = await export_douyin_cookie_str(context)
                    # 关掉浏览器前在页面上下文取真实昵称（requests 拉 profile 常被风控）
                    profile = await extract_self_profile_from_page(page)
                    if not profile.get("nickname"):
                        for url in (
                            "https://www.douyin.com/user/self",
                            "https://www.douyin.com/",
                        ):
                            try:
                                await page.goto(
                                    url, wait_until="domcontentloaded", timeout=30000
                                )
                                await page.wait_for_timeout(1500)
                                profile = await extract_self_profile_from_page(page)
                                if profile.get("nickname"):
                                    break
                            except Exception:
                                continue
                    print(
                        f"[ticket] 扫码成功 sessionid="
                        f"{'yes' if sessionid_from_cookie(cookie_str) else 'no'} "
                        f"cookie_keys={len(cookie_str.split('; ')) if cookie_str else 0} "
                        f"nickname={profile.get('nickname') or '-'}",
                        file=sys.stderr,
                    )
                    out: dict[str, Any] = dict(cred)
                    out["_cookie_str"] = cookie_str
                    out["_nickname"] = profile.get("nickname") or ""
                    out["_unique_id"] = profile.get("unique_id") or ""
                    out["_uid"] = profile.get("uid") or ""
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
        securityish = [
            k
            for k in last_keys
            if any(x in k.lower() for x in ("security", "sdk", "protect", "sign", "crypt"))
        ]
        raise TimeoutError(
            f"扫码超时：仍未抓到 web_protect。security 相关 key: {securityish[:20] or '无'}"
        )
    finally:
        await browser.close()
        await p.stop()


def save_qr_grab_result(
    cred: dict[str, Any],
    *,
    account_name: str = "",
    sync_cookie: bool = True,
) -> tuple[str, str]:
    """追加写入 cookies.json + im_cred.json（按 sessionid upsert，不覆盖其它账号）。"""
    cookie_str = str(cred.pop("_cookie_str", "") or "")
    ticket = {k: str(cred.get(k) or "") for k in (
        "DY_TICKET", "DY_TS_SIGN", "DY_CLIENT_CERT", "DY_PRIVATE_KEY"
    ) if cred.get(k)}
    if not ticket.get("DY_TICKET") or not ticket.get("DY_PRIVATE_KEY"):
        raise ValueError("ticket 不完整")

    sid = sessionid_from_cookie(cookie_str)
    resolved = account_name.strip()
    # 优先用扫码浏览器里拿到的真实昵称，再回退 HTTP profile（常被风控）
    nickname = str(cred.pop("_nickname", "") or "").strip()
    unique_id = str(cred.pop("_unique_id", "") or "").strip()
    uid = str(cred.pop("_uid", "") or "").strip()
    if cookie_str and not (nickname and (unique_id or uid)):
        try:
            from .im import account_summary, load_auth

            me = account_summary(load_auth(cookie=cookie_str))
            nickname = nickname or str(me.get("nickname") or "").strip()
            unique_id = unique_id or str(me.get("unique_id") or "").strip()
            uid = uid or str(me.get("uid") or "").strip()
        except Exception:
            pass
    if not resolved:
        resolved = nickname or unique_id or (sid[:8] if sid else "douyin")
    if not resolved:
        resolved = sid[:8] or "douyin"
    if not uid:
        # 最后手段：多会话多数票；单会话不猜（避免和对方互换）
        try:
            from .im import infer_self_uid, load_auth, list_conversations

            auth = load_auth(cookie=cookie_str, account_name=resolved, uid="")
            convs = list_conversations(auth, page_size=40, max_pages=1)
            uid = infer_self_uid(auth, convs=convs)
        except Exception:
            uid = ""
    if not uid:
        print(
            "[ticket] 警告：未能解析真实 uid。发信/实时收信可能异常。"
            "请重跑 grab-ticket --qr，或手动把 uid 写入 cookies.json",
            file=sys.stderr,
        )
    else:
        print(f"[ticket] account={resolved} uid={uid}", file=sys.stderr)

    if sync_cookie:
        if not cookie_str or not sid:
            raise ValueError("扫码 cookie 缺少 sessionid，拒绝写回（ticket 必须与 session 同源）")
        save_douyin_cookie(
            cookie_str,
            name=resolved,
            source="browser:qr",
            append=True,
            set_active=True,
            uid=uid,
            unique_id=unique_id,
            nickname=nickname,
        )
    save_im_cred(ticket, account_name=resolved, sessionid=sid, append=True, set_active=True)
    return resolved, sid


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="抓抖音发信 web_protect ticket（追加多账号）")
    ap.add_argument("--qr", action="store_true", help="扫码登录，同时追加 cookie + ticket（推荐）")
    ap.add_argument("--headed", action="store_true", help="cookie 模式有界面")
    ap.add_argument("--name", default="", help="账号名称（默认用抖音昵称 / 当前账号）")
    ap.add_argument("--timeout", type=int, default=0, help="超时秒数（默认 qr=180 / cookie=90）")
    ap.add_argument(
        "--no-sync-cookie",
        action="store_true",
        help="扫码成功后不写回 cookies.json（默认会同步，否则 ticket 与 session 错位）",
    )
    args = ap.parse_args(argv)

    if args.qr:
        timeout = args.timeout or 180
        print("[ticket] mode=qr (scan login, append cookie+ticket)", file=sys.stderr)
        cred = asyncio.run(grab_with_qr(timeout_s=timeout))
        name, sid = save_qr_grab_result(
            cred,
            account_name=args.name,
            sync_cookie=not args.no_sync_cookie,
        )
        print(
            f"[ticket] appended account={name} sid={sid[:8]}… "
            f"cookie→{DOUYIN_COOKIE_FILE} ticket→{DOUYIN_IM_CRED_FILE}"
        )
        return

    timeout = args.timeout or 90
    acc = load_douyin_cookie(account_name=args.name)
    print(
        f"[ticket] mode=cookie account={acc.name} headed={args.headed}",
        file=sys.stderr,
    )
    print(
        "[ticket] 提示: 若只有 crypt 没有 web_protect，请改用 --qr",
        file=sys.stderr,
    )
    payload = asyncio.run(grab(acc.cookie, headless=not args.headed, timeout_s=timeout))
    save_im_cred(payload, account_name=acc.name, sessionid=acc.sessionid, append=True)
    print(
        f"[ticket] saved {DOUYIN_IM_CRED_FILE} account={acc.name} "
        f"ticket={bool(payload['DY_TICKET'])} priv={bool(payload['DY_PRIVATE_KEY'])}"
    )


if __name__ == "__main__":
    main()
