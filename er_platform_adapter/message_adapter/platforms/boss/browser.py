"""BOSS login and sensitive operations in a persistent Chrome profile."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
import json
from pathlib import Path
import shutil
import time
from typing import Any

from message_adapter.browser_profiles import BrowserProfile
from .auth import Credential
from .constants import (
    BOSS_EXCHANGE_ACCEPT_URL,
    BOSS_EXCHANGE_CONTENT_URL,
    BOSS_EXCHANGE_REQUEST_URL,
    BOSS_FRIEND_DETAIL_URL,
    SESSION_COOKIES,
    WEB_BOSS_CHAT_URL,
    WEB_BOSS_LOGIN_URL,
)
from .exceptions import BossApiError, IdentityMismatchError, ParamError, SessionExpiredError


def _discard_restored_tabs(profile: BrowserProfile) -> None:
    """Drop Chrome's last tabs so login does not reopen the expired chat page."""
    raw_path = getattr(profile, "path", None)
    try:
        root = Path(raw_path) / "Default"
    except TypeError:
        return
    if not root.exists():
        return
    sessions = root / "Sessions"
    if sessions.exists():
        shutil.rmtree(sessions, ignore_errors=True)
    for name in ("Current Session", "Current Tabs", "Last Session", "Last Tabs"):
        path = root / name
        if path.exists():
            path.unlink(missing_ok=True)


async def _clear_zhipin_cookies(context: Any) -> None:
    clear_cookies = getattr(context, "clear_cookies", None)
    if clear_cookies is not None:
        await clear_cookies()


async def _foreground_page(context: Any) -> Any:
    pages = list(context.pages)
    page = pages[0] if pages else await context.new_page()
    for extra in pages[1:]:
        url = str(getattr(extra, "url", "") or "")
        if url.startswith("about:"):
            try:
                await extra.close()
            except Exception:
                continue
    return page


async def _open_login_page(page: Any) -> None:
    url = str(getattr(page, "url", "") or "")
    if "/web/user/" not in url:
        await page.goto(WEB_BOSS_LOGIN_URL, wait_until="domcontentloaded", timeout=60_000)
    else:
        reload = getattr(page, "reload", None)
        if reload is not None:
            await reload(wait_until="domcontentloaded", timeout=60_000)
    bring_to_front = getattr(page, "bring_to_front", None)
    if bring_to_front is not None:
        await bring_to_front()
    await _open_qr_tab(page)


def _zhipin_cookie_map(cookies: list[dict[str, Any]]) -> dict[str, str]:
    return {
        str(item.get("name") or ""): str(item.get("value") or "")
        for item in cookies
        if "zhipin.com" in str(item.get("domain") or "") and item.get("name") and item.get("value")
    }


class _PageCommand:
    def __init__(self, socket: Any, session_id: str) -> None:
        self._socket = socket
        self._session_id = session_id
        self._next_id = 10

    async def __call__(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        self._next_id += 1
        message_id = self._next_id
        payload: dict[str, Any] = {"id": message_id, "method": method, "sessionId": self._session_id}
        if params:
            payload["params"] = params
        await self._socket.send(json.dumps(payload))
        while True:
            incoming = json.loads(await asyncio.wait_for(self._socket.recv(), timeout=10))
            if incoming.get("id") != message_id:
                continue
            error = incoming.get("error")
            if error:
                raise RuntimeError(str(error.get("message") or "CDP 调用失败"))
            result = incoming.get("result")
            return result if isinstance(result, dict) else {}


def _login_page_target(targets: list[dict[str, Any]]) -> dict[str, Any] | None:
    pages = [item for item in targets if item.get("type") == "page"]
    for page in pages:
        if "zhipin.com" in str(page.get("url") or ""):
            return page
    return pages[0] if pages else None


async def _with_login_page(endpoint: str, action: Callable[[_PageCommand], Any]) -> Any:
    import urllib.request
    import websockets

    version = json.load(urllib.request.urlopen(f"{endpoint}/json/version", timeout=2))
    targets = json.load(urllib.request.urlopen(f"{endpoint}/json/list", timeout=2))
    page = _login_page_target(targets)
    if page is None or not page.get("id"):
        raise RuntimeError("BOSS 登录页已关闭")
    socket_url = str(version.get("webSocketDebuggerUrl") or "")
    async with websockets.connect(socket_url, max_size=8_000_000) as socket:
        await socket.send(json.dumps({
            "id": 1,
            "method": "Target.attachToTarget",
            "params": {"targetId": page["id"], "flatten": True},
        }))
        session_id = ""
        while not session_id:
            incoming = json.loads(await asyncio.wait_for(socket.recv(), timeout=10))
            if incoming.get("method") == "Target.attachedToTarget":
                session_id = str((incoming.get("params") or {}).get("sessionId") or "")
            elif incoming.get("id") == 1 and incoming.get("error"):
                raise RuntimeError("无法连接 BOSS 登录页")
        try:
            return await action(_PageCommand(socket, session_id))
        finally:
            await socket.send(json.dumps({
                "id": 2,
                "method": "Target.detachFromTarget",
                "params": {"sessionId": session_id},
            }))


async def _reveal_login_qr(endpoint: str) -> None:
    """Open the QR tab without enabling a page debugger that BOSS treats as DevTools."""
    async def click_qr(command: _PageCommand) -> None:
        await command("DOM.getDocument", {"depth": 0, "pierce": True})
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            found = await command("DOM.performSearch", {"query": "APP扫码登录"})
            if int(found.get("resultCount") or 0) < 1:
                await asyncio.sleep(0.4)
                continue
            nodes = await command(
                "DOM.getSearchResults",
                {"searchId": found.get("searchId"), "fromIndex": 0, "toIndex": 1},
            )
            node_ids = list(nodes.get("nodeIds") or [])
            if not node_ids:
                return
            box = await command("DOM.getBoxModel", {"nodeId": node_ids[0]})
            quad = list((box.get("model") or {}).get("content") or [])
            if len(quad) < 8:
                return
            x = sum(float(quad[index]) for index in (0, 2, 4, 6)) / 4
            y = sum(float(quad[index]) for index in (1, 3, 5, 7)) / 4
            for event in ("mousePressed", "mouseReleased"):
                await command("Input.dispatchMouseEvent", {
                    "type": event,
                    "x": x,
                    "y": y,
                    "button": "left",
                    "clickCount": 1,
                })
            return

    try:
        await _with_login_page(endpoint, click_qr)
    except Exception:
        return


async def _read_zhipin_cookies(endpoint: str) -> dict[str, str]:
    async def read(command: _PageCommand) -> dict[str, str]:
        result = await command("Network.getCookies", {"urls": [WEB_BOSS_LOGIN_URL, WEB_BOSS_CHAT_URL]})
        cookies = result.get("cookies")
        return _zhipin_cookie_map(cookies if isinstance(cookies, list) else [])

    return await _with_login_page(endpoint, read)


async def _login_with_open_chrome(
    profile: BrowserProfile,
    open_chrome: Callable[..., AbstractAsyncContextManager[str]],
    *,
    timeout_s: int,
    emit: Callable[[str], None],
) -> Credential:
    async with open_chrome(start_url=WEB_BOSS_LOGIN_URL) as endpoint:
        await _reveal_login_qr(endpoint)
        emit("请在打开的 Google Chrome 中完成 BOSS 直聘扫码登录")
        deadline = time.monotonic() + max(30, int(timeout_s))
        cookies: dict[str, str] = {}
        while time.monotonic() < deadline:
            cookies = await _read_zhipin_cookies(endpoint)
            if SESSION_COOKIES.issubset(cookies):
                await asyncio.sleep(2)
                cookies = await _read_zhipin_cookies(endpoint)
                break
            await asyncio.sleep(2)
        if not SESSION_COOKIES.issubset(cookies):
            missing = ", ".join(sorted(SESSION_COOKIES - set(cookies)))
            raise TimeoutError(f"BOSS 扫码登录超时，仍缺少 Cookie: {missing}")
        return Credential(cookies, browser_profile=str(profile.path))


async def _open_qr_tab(page: Any) -> None:
    if getattr(page, "get_by_text", None) is None:
        return
    try:
        sms = page.get_by_text("验证码登录")
        if await sms.count() == 0:
            return
        tab = page.get_by_text("APP扫码登录", exact=True)
        if await tab.count():
            await tab.first.click(timeout=1_000)
    except Exception:
        return


async def login_with_profile(
    profile: BrowserProfile,
    *,
    timeout_s: int = 300,
    on_status: Callable[[str], None] | None = None,
) -> Credential:
    """Open the platform Chrome profile and wait for a complete BOSS login."""
    def emit(message: str) -> None:
        if on_status is not None:
            on_status(message)

    emit("正在清理本机浏览器登录态")
    clear_profile = getattr(profile, "clear", None)
    if clear_profile is not None:
        clear_profile()
    _discard_restored_tabs(profile)
    open_chrome = getattr(profile, "open_chrome", None)
    if open_chrome is not None:
        # Read cookies over CDP without attaching Playwright. The login page
        # calls window.close() when it sees that page debugger.
        return await _login_with_open_chrome(profile, open_chrome, timeout_s=timeout_s, emit=emit)
    open_browser = getattr(profile, "launch_over_cdp", None)
    browser_cm = (
        open_browser(start_url=WEB_BOSS_LOGIN_URL)
        if open_browser is not None
        else profile.launch()
    )
    async with browser_cm as context:
        # Do not open about:blank and do not abort BOSS redirects. Aborting the
        # login redirect is what left the visible tab on about:blank.
        await _clear_zhipin_cookies(context)
        page = await _foreground_page(context)
        await _open_login_page(page)
        emit("请在打开的 Google Chrome 中完成 BOSS 直聘扫码登录")
        deadline = time.monotonic() + max(30, int(timeout_s))
        cookies: dict[str, str] = {}
        while time.monotonic() < deadline:
            cookies = await _cookies(context)
            if SESSION_COOKIES.issubset(cookies):
                break
            await asyncio.sleep(2)
        if not SESSION_COOKIES.issubset(cookies):
            missing = ", ".join(sorted(SESSION_COOKIES - set(cookies)))
            raise TimeoutError(f"BOSS 扫码登录超时，仍缺少 Cookie: {missing}")

        # Let the real page finish its security bootstrap and persist all
        # browser-managed storage before the profile is closed.
        await page.goto(WEB_BOSS_CHAT_URL, wait_until="domcontentloaded", timeout=60_000)
        await page.wait_for_timeout(2_000)
        cookies = await _cookies(context)
        credential = Credential(cookies, browser_profile=str(profile.path))
        emit("扫码成功，正在验证 BOSS 消息通道")
        return credential


async def _cookies(context: Any) -> dict[str, str]:
    return {
        str(item.get("name") or ""): str(item.get("value") or "")
        for item in await context.cookies()
        if "zhipin.com" in str(item.get("domain") or "") and item.get("name") and item.get("value")
    }


class BossBrowserSession:
    """Execute BOSS security-sensitive HTTP calls inside the authenticated page."""

    def __init__(self, profile: BrowserProfile):
        self.profile = profile
        self._launcher: AbstractAsyncContextManager[Any] | None = None
        self._context: Any = None
        self._page: Any = None

    async def __aenter__(self) -> "BossBrowserSession":
        self._launcher = self.profile.launch()
        self._context = await self._launcher.__aenter__()
        self._page = self._context.pages[0] if self._context.pages else await self._context.new_page()
        await self._page.goto(WEB_BOSS_CHAT_URL, wait_until="domcontentloaded", timeout=60_000)
        return self

    async def __aexit__(self, *args: Any) -> None:
        if self._launcher is not None:
            await self._launcher.__aexit__(*args)
        self._launcher = None
        self._context = None
        self._page = None

    async def get_friend_details(self, friend_ids: list[int]) -> list[dict[str, Any]]:
        payload = await self._post(
            BOSS_FRIEND_DETAIL_URL,
            {"friendIds": ",".join(str(value) for value in friend_ids)},
            "候选人详情",
        )
        return [dict(item) for item in payload.get("friendList") or []]

    async def request_wechat_exchange(
        self,
        *,
        security_id: str,
        unique_id: str,
        name: str,
    ) -> dict[str, Any]:
        return await self._post(
            BOSS_EXCHANGE_REQUEST_URL,
            {"type": 2, "securityId": security_id, "uniqueId": unique_id, "name": name},
            "发起微信交换",
        )

    async def accept_wechat_exchange(self, *, security_id: str, platform_message_id: int) -> dict[str, Any]:
        return await self._post(
            BOSS_EXCHANGE_ACCEPT_URL,
            {"securityId": security_id, "mid": int(platform_message_id), "type": 2},
            "同意微信交换",
        )

    async def get_exchange_content(self, audience_id: int) -> dict[str, Any]:
        return await self._post(
            BOSS_EXCHANGE_CONTENT_URL,
            {"uid": int(audience_id)},
            "查看交换结果",
        )

    async def _post(self, path: str, data: dict[str, Any], action: str) -> dict[str, Any]:
        if self._page is None:
            raise RuntimeError("BossBrowserSession must be used as an async context manager")
        payload = await self._page.evaluate(
            """async ({path, data}) => {
                const body = new URLSearchParams();
                for (const [key, value] of Object.entries(data)) body.set(key, String(value));
                const response = await fetch(path, {
                    method: 'POST',
                    credentials: 'include',
                    headers: {
                        'Content-Type': 'application/x-www-form-urlencoded;charset=UTF-8',
                        'X-Requested-With': 'XMLHttpRequest'
                    },
                    body: body.toString()
                });
                return {status: response.status, text: await response.text()};
            }""",
            {"path": path, "data": data},
        )
        status = int(payload.get("status") or 0)
        text = str(payload.get("text") or "")
        if status < 200 or status >= 300:
            raise BossApiError(f"{action}: HTTP {status}", code=status)
        try:
            response = json.loads(text)
        except (TypeError, ValueError) as exc:
            raise BossApiError(f"{action}: BOSS 返回了非 JSON 响应") from exc
        code = int(response.get("code", -1))
        if code == 0:
            result = response.get("zpData") or {}
            return result if isinstance(result, dict) else {"result": result}
        message = str(response.get("message") or "unknown error")
        if code == 37:
            raise SessionExpiredError()
        if code == 24:
            raise IdentityMismatchError()
        if code in {17, 19}:
            raise ParamError(message, code=code)
        raise BossApiError(f"{action}: {message} (code={code})", code=code, response=response)
