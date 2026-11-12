"""Generate BOSS ``__zp_stoken__`` the same way as the boss CLI.

The cookie is written by the site's security script. A headless Chrome visit
with the saved session lets that script run, then the value is reused on the
HTTP client. This never reads the user's everyday Chrome profile.
"""

from __future__ import annotations

import logging
import time

from .constants import HEADERS

logger = logging.getLogger(__name__)

STOKEN_COOKIE = "__zp_stoken__"
TRIGGER_URL = "https://www.zhipin.com/web/geek/job?query=python&city=101190400"
VERIFY_URL = (
    "https://www.zhipin.com/wapi/zpgeek/search/joblist.json"
    "?query=python&city=101280600&page=1&pageSize=15"
)
_ANTI_DETECT_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--disable-infobars",
    "--no-first-run",
    "--no-default-browser-check",
    "--disable-extensions",
]
_ANTI_DETECT_INIT_SCRIPT = """
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
window.chrome = window.chrome || {runtime: {}};
Object.defineProperty(navigator, 'languages', {get: () => ['zh-CN', 'zh', 'en']});
Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
"""


def generate_stoken(cookies: dict[str, str] | None = None, *, verify: bool = True) -> str:
    """Return a fresh ``__zp_stoken__``, or an empty string when generation fails."""
    session = {key: value for key, value in (cookies or {}).items() if value}
    if not session:
        logger.warning("跳过生成 __zp_stoken__：没有可用的登录会话")
        return ""
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:
        logger.warning("__zp_stoken__ 生成模块不可用: %s", exc)
        return ""

    logger.info("正在通过无头浏览器生成 __zp_stoken__（约 5-15s）")
    try:
        with sync_playwright() as playwright:
            browser = _launch_chrome(playwright)
            try:
                context = browser.new_context(
                    user_agent=HEADERS["User-Agent"],
                    viewport={"width": 1536, "height": 864},
                )
                context.add_init_script(_ANTI_DETECT_INIT_SCRIPT)
                for name, value in session.items():
                    try:
                        context.add_cookies([{"name": name, "value": value, "domain": ".zhipin.com", "path": "/"}])
                    except Exception as exc:
                        logger.warning("注入会话 cookie %s 失败: %s", name, exc)
                page = context.new_page()
                page.goto(TRIGGER_URL, wait_until="domcontentloaded", timeout=30000)
                stoken = _wait_for_stoken(context, page)
                if stoken and verify:
                    _verify_in_page(page)
                return stoken
            finally:
                try:
                    browser.close()
                except Exception:
                    logger.debug("关闭生成 __zp_stoken__ 的浏览器失败", exc_info=True)
    except Exception as exc:
        logger.warning("生成 __zp_stoken__ 失败: %s", exc)
        return ""


def _launch_chrome(playwright: object):
    chromium = playwright.chromium  # type: ignore[attr-defined]
    try:
        return chromium.launch(channel="chrome", headless=True, args=list(_ANTI_DETECT_ARGS))
    except Exception as exc:
        logger.warning("真实 Chrome 无头启动失败(%s)，退回内置 Chromium", exc)
        return chromium.launch(headless=True, args=list(_ANTI_DETECT_ARGS))


def _wait_for_stoken(context: object, page: object) -> str:
    deadline = time.time() + 25
    while time.time() < deadline:
        cookies = {item["name"]: item["value"] for item in context.cookies()}  # type: ignore[attr-defined]
        stoken = str(cookies.get(STOKEN_COOKIE) or "")
        if stoken:
            logger.info("已生成 __zp_stoken__")
            return stoken
        page.wait_for_timeout(1500)  # type: ignore[attr-defined]
    logger.warning("未能生成 __zp_stoken__")
    return ""


def _verify_in_page(page: object) -> None:
    try:
        payload = page.evaluate(  # type: ignore[attr-defined]
            """async (url) => {
                const response = await fetch(url);
                return await response.json();
            }""",
            VERIFY_URL,
        )
        code = int(payload.get("code", -1)) if isinstance(payload, dict) else -1
        logger.info("页面内 __zp_stoken__ 自校验 code=%s", code)
        if code != 0:
            logger.warning("__zp_stoken__ 自校验未通过，后续请求可能仍被风控")
    except Exception as exc:
        logger.warning("页面内 __zp_stoken__ 自校验异常: %s", exc)
