"""Douyin web login via headed Playwright browser (scan QR → cookie + ticket).

对齐 spider/js ``dy_im_grab_ticket.py --qr``：同一次扫码会话追加 cookie 与 ticket。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

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


def _ensure_playwright() -> None:
    try:
        import playwright  # noqa: F401
    except ImportError as exc:
        raise RuntimeError(
            "Playwright 未安装。请执行: uv sync --extra browser && uv run playwright install chromium"
        ) from exc
    from pathlib import Path

    cache = Path.home() / "Library" / "Caches" / "ms-playwright"
    if not any(cache.glob("chromium-*")):
        raise RuntimeError(
            "Playwright Chromium 未安装。请执行: uv run playwright install chromium"
        )


async def login_interactive(
    *,
    headless: bool = False,
    login_timeout_s: int = 300,
    ticket_timeout_s: int = 120,
    account_name: str = "",
    on_status: Callable[[str], None] | None = None,
) -> DouyinBrowserLoginResult:
    """扫码登录，同一次会话抓取 cookie + ticket（与 spider --qr 相同）。"""
    _ensure_playwright()
    if headless:
        raise RuntimeError("扫码登录需要有界面浏览器，请去掉 --headless")

    def emit(msg: str) -> None:
        if on_status:
            on_status(msg)

    emit("正在打开抖音网页，请扫码登录…")
    timeout_s = max(int(login_timeout_s or 0), int(ticket_timeout_s or 0), 180)
    try:
        raw = await grab_with_qr(timeout_s=timeout_s)
    except TimeoutError:
        raise
    except Exception as exc:
        raise RuntimeError(f"扫码登录失败: {exc}") from exc

    cookie_str = str(raw.get("_cookie_str") or "")
    sid = sessionid_from_cookie(cookie_str)
    ticket = {
        k: str(raw.get(k) or "")
        for k in ("DY_TICKET", "DY_TS_SIGN", "DY_CLIENT_CERT", "DY_PRIVATE_KEY")
        if raw.get(k)
    }
    if not ticket.get("DY_TICKET") or not ticket.get("DY_PRIVATE_KEY"):
        if cookie_str and sid:
            resolved = account_name.strip() or sid[:8] or "douyin"
            save_douyin_cookie(
                cookie_str,
                name=resolved,
                source="browser:qr",
                append=True,
                set_active=True,
            )
        raise TimeoutError(
            "cookie 可能已拿到，但发信 ticket 不完整。"
            "请执行: boss douyin grab-ticket --qr"
        )

    resolved = account_name.strip()
    nickname = str(raw.get("_nickname") or "").strip()
    unique_id = str(raw.get("_unique_id") or "").strip()
    uid = str(raw.get("_uid") or "").strip()
    if not (nickname and (unique_id or uid)):
        try:
            from .im import account_summary, load_auth

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


def save_browser_login_result(result: DouyinBrowserLoginResult) -> tuple[str, str]:
    """追加（upsert by sessionid）写入 cookies.json 与 im_cred.json。"""
    save_douyin_cookie(
        result.cookie,
        name=result.account_name,
        source="browser:qr",
        append=True,
        set_active=True,
        uid=str(result.uid or ""),
        nickname=str(result.nickname or ""),
    )
    save_im_cred(
        result.ticket,
        account_name=result.account_name,
        sessionid=result.sessionid,
        append=True,
        set_active=True,
    )
    return result.account_name, result.sessionid
