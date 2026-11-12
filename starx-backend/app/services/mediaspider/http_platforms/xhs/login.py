# -*- coding: utf-8 -*-
"""小红书 PC 扫码 / 手机号登录。

默认 Playwright 浏览器；纯 HTTP 可用 ``method='http'``。
"""

from __future__ import annotations

import sys
from typing import Literal, Optional


def _log(msg: str) -> None:
    print(msg, file=sys.stderr)


def _require_login_api():
    try:
        from app.services.mediaspider.http_platforms.xhs.pc_auth.login_apis import (
            XHSLoginApi,
        )
    except ImportError as exc:
        raise RuntimeError(
            "缺少登录依赖。请执行: pip install curl_cffi loguru qrcode && "
            "cd app/services/mediaspider/http_platforms/xhs/pc_auth && npm install"
        ) from exc
    return XHSLoginApi


def _lease_proxy(use_proxy: bool):
    from app.services.mediaspider.http_platforms.common.proxy import (
        lease_requests_proxies_sync,
    )

    return lease_requests_proxies_sync(enabled=use_proxy)


def login_by_qrcode(
    *,
    timeout_sec: float = 180,
    show_in_terminal: bool = True,
    use_proxy: bool = False,
    headless: bool = False,
    method: Literal["browser", "http"] = "browser",
) -> str:
    """扫码登录，返回完整 Cookie（需含 web_session）。"""

    if method == "http":
        XHSLoginApi = _require_login_api()
        proxies = _lease_proxy(use_proxy)
        api = XHSLoginApi(proxies=proxies)
        try:
            cookie = api.qrcode_login(
                show_in_terminal=show_in_terminal,
                timeout_seconds=timeout_sec,
            )
        finally:
            try:
                api.http.close()
            except Exception:
                pass
    else:
        from app.services.mediaspider.http_platforms.xhs.browser_login import (
            login_by_qrcode as browser_qr,
        )

        proxies = _lease_proxy(use_proxy) if use_proxy else None
        cookie = browser_qr(
            timeout_sec=timeout_sec,
            show_in_terminal=show_in_terminal,
            headless=headless,
            proxy=proxies,
        )
        cookie = str(getattr(cookie, "cookie", cookie) or cookie)

    if not cookie or "web_session=" not in str(cookie):
        raise RuntimeError("扫码登录失败或未拿到 web_session")
    _log("扫码登录成功")
    return str(cookie)


def login_by_phone(
    *,
    phone: str = "",
    timeout_sec: float = 180,
    use_proxy: bool = False,
    headless: bool = False,
    method: Literal["browser", "http"] = "browser",
) -> str:
    """手机号验证码登录，返回完整 Cookie。"""

    if method == "http":
        del timeout_sec
        XHSLoginApi = _require_login_api()
        phone = (phone or "").strip()
        proxies = _lease_proxy(use_proxy)
        api = XHSLoginApi(proxies=proxies)
        try:
            if not phone:
                cookie = api.phone_login()
            else:
                cookie = _phone_login_with_number(api, phone)
        finally:
            try:
                api.http.close()
            except Exception:
                pass
    else:
        from app.services.mediaspider.http_platforms.xhs.browser_login import (
            login_by_phone as browser_phone,
        )

        proxies = _lease_proxy(use_proxy) if use_proxy else None
        cookie = browser_phone(
            phone=phone,
            timeout_sec=timeout_sec,
            headless=headless,
            proxy=proxies,
        )
        cookie = str(getattr(cookie, "cookie", cookie) or cookie)

    if not cookie or "web_session=" not in str(cookie):
        raise RuntimeError("手机号登录失败或未拿到 web_session")
    _log("手机号登录成功")
    return str(cookie)


def _phone_login_with_number(api, phone: str) -> Optional[str]:
    from loguru import logger

    logger.info("[1/5] 正在初始化匿名设备...")
    try:
        cookies = api.generate_init_cookies()
        api.ensure_webprofile(cookies)
    except Exception as exc:
        logger.error(f"匿名设备验收失败，未发送验证码: {exc}")
        return None

    logger.info("[2/5] 正在发送验证码...")
    success, msg, _ = api.send_phone_code(phone, cookies)
    if not success:
        logger.error(f"发送失败: {msg}")
        return None
    logger.info("验证码已发送")

    code = input("请输入验证码: ").strip()
    logger.info("[3/5] 正在验证...")
    success, msg, result = api.login_by_phone(phone, code, cookies)
    if not success:
        logger.error(f"验证失败: {msg}")
        return None
    cookies = result["cookies"]

    logger.info("[4/5] 正在合并正式会话...")
    success, user_info, cookies = api.get_user_info(cookies)
    if not success or user_info.get("guest") is not False:
        logger.error("正式会话验证失败，拒绝返回访客 Cookie")
        return None
    logger.info(
        f'用户: {user_info.get("nickname", "未知")} '
        f'(RedID: {user_info.get("red_id", "未知")})'
    )
    cookies_str = api.cookies_to_str(cookies)
    logger.success("[5/5] 登录成功，Cookie 已通过返回值交给调用方")
    return cookies_str


__all__ = [
    "login_by_phone",
    "login_by_qrcode",
]
