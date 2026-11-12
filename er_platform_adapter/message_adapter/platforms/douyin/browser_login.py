"""Douyin web login via headed Playwright browser (scan QR → cookie + ticket)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from message_adapter.browser_profiles import BrowserProfile
from message_adapter.storage import CredentialStore

from .credentials import save_douyin_cookie, save_im_cred, sessionid_from_cookie
from .grab_ticket import grab_with_qr


@dataclass
class DouyinBrowserLoginResult:
    cookie: str
    sessionid: str
    account_name: str
    ticket: dict[str, str]
    nickname: str = ""
    uid: str = ""


async def login_interactive(
    *,
    profile: BrowserProfile,
    headless: bool = False,
    login_timeout_s: int = 300,
    ticket_timeout_s: int = 120,
    account_name: str = "",
    on_status: Callable[[str], None] | None = None,
) -> DouyinBrowserLoginResult:
    """扫码登录并在同一次会话抓取 cookie + ticket。"""
    if headless:
        raise RuntimeError("扫码登录需要有界面浏览器，请去掉 --headless")

    def emit(msg: str) -> None:
        if on_status:
            on_status(msg)

    emit("正在打开抖音网页，请扫码登录…")
    timeout_s = max(int(login_timeout_s or 0), int(ticket_timeout_s or 0), 180)
    try:
        raw = await grab_with_qr(profile=profile, timeout_s=timeout_s)
    except TimeoutError:
        raise
    except Exception as exc:
        raise RuntimeError(f"扫码登录失败: {exc}") from exc

    cookie_str = str(raw.get("_cookie_str") or "")
    sid = sessionid_from_cookie(cookie_str)
    ticket = {k: str(raw.get(k) or "") for k in ("DY_TICKET", "DY_TS_SIGN", "DY_CLIENT_CERT", "DY_PRIVATE_KEY") if raw.get(k)}
    if not ticket.get("DY_TICKET") or not ticket.get("DY_PRIVATE_KEY"):
        raise TimeoutError("扫码会话已建立，但发信凭据不完整，请重新执行 adapter douyin login")

    resolved = account_name.strip()
    nickname = str(raw.get("_nickname") or "").strip()
    unique_id = str(raw.get("_unique_id") or "").strip()
    uid = str(raw.get("_uid") or "").strip()
    if not (nickname and (unique_id or uid)):
        try:
            from .protocol import account_summary, load_auth

            me = account_summary(load_auth(cookie=cookie_str))
            nickname = nickname or str(me.get("nickname") or "").strip()
            unique_id = unique_id or str(me.get("unique_id") or "").strip()
            uid = uid or str(me.get("uid") or "").strip()
        except Exception:
            pass
    if not resolved:
        resolved = nickname or unique_id or sid[:8] or "douyin"

    emit("扫码成功，已拿到同源 cookie + ticket")
    return DouyinBrowserLoginResult(
        cookie=cookie_str,
        sessionid=sid,
        account_name=resolved,
        ticket=ticket,
        nickname=nickname,
        uid=uid,
    )


def save_browser_login_result(
    result: DouyinBrowserLoginResult,
    *,
    store: CredentialStore,
    browser_profile: str = "",
) -> tuple[str, str]:
    """Persist both credential sections in the device's Douyin slot."""
    save_douyin_cookie(
        result.cookie,
        store=store,
        name=result.account_name,
        source="browser:qr",
        uid=str(result.uid or ""),
        nickname=str(result.nickname or ""),
        browser_profile=browser_profile,
    )
    save_im_cred(
        result.ticket,
        store=store,
        sessionid=result.sessionid,
    )
    return result.account_name, result.sessionid
