"""本地生成 BOSS __zp_stoken__（Playwright 无头 Chromium 方案）。

用法（在项目根目录）:
    uv run python -m boss_cli._stoken_gen

说明:
    - 默认启动【无头】Chromium：优先真实 Chrome 的 headless=new 模式（channel="chrome"），
      指纹接近真实浏览器；启动失败时退回内置 Chromium 无头。
    - 关键: --disable-blink-features=AutomationControlled + 覆盖 navigator.webdriver
      否则 BOSS security JS 识别为自动化环境, 生成的 stoken 会被服务器拒绝(code=37)
    - 打开 BOSS 求职搜索页, 让页面 JS 生成 __zp_stoken__ cookie
    - 在页面上下文内 fetch 搜索接口自校验 (code=0 即有效)
    - cookie 来源: 优先使用调用方传入的会话 cookies（如扫码登录所得）;
      未传入时才尝试从本机 Chrome 提取（inject_cookies=True）
    - 全流程无浏览器窗口弹出（headless）

验证结论(2026-08-26):
    - 纯 jsdom 补环境: 服务器拒绝(37/38)
    - headless/headful Playwright 无反检测: 拒绝(37)
    - 反检测 headless + 页面内 fetch: 通过(code=0, 15 条)
    - stoken 必须由页面上下文随请求发送, 提取后用 httpx 单独发会被拒
"""

from __future__ import annotations

import argparse
import json
import logging
import subprocess
import sys
import time

from playwright.sync_api import sync_playwright

from .constants import HEADERS

logger = logging.getLogger(__name__)

# 打开 BOSS 求职搜索页触发 security JS 生成 stoken
TRIGGER_URL = "https://www.zhipin.com/web/geek/job?query=python&city=101190400"
# 自校验接口(页面内 fetch)
VERIFY_URL = (
    "https://www.zhipin.com/wapi/zpgeek/search/joblist.json"
    "?query=python&city=101280600&page=1&pageSize=15"
)

# 反检测启动参数（无头/有头共用）
_ANTI_DETECT_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--disable-infobars",
    "--no-first-run",
    "--no-default-browser-check",
    "--disable-extensions",
]

# 反检测页面脚本: 抹平自动化指纹
_ANTI_DETECT_INIT_SCRIPT = """
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
window.chrome = window.chrome || {runtime: {}};
Object.defineProperty(navigator, 'languages', {get: () => ['zh-CN', 'zh', 'en']});
Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
"""


def extract_chrome_cookies(retries: int = 1) -> dict[str, str]:
    """从本机 Chrome 提取 zhipin cookie（仅当调用方未传入会话 cookies 时兜底）。

    仅尝试 1 次、单次超时 8s：Chrome 开着时会锁库导致读取失败，
    此时快速返回空 dict（生成方降级为匿名 stoken），不做长时间重试。
    """
    script = r'''
import json, sys, os
import browser_cookie3 as bc3
root = os.path.expanduser("~/Library/Application Support/Google/Chrome")
cj = bc3.chrome(cookie_file=os.path.join(root, "Default", "Cookies"), domain_name="zhipin.com")
cookies = {c.name: c.value for c in cj if "zhipin" in (c.domain or "")}
print(json.dumps(cookies))
'''
    for attempt in range(retries):
        try:
            r = subprocess.run(
                [sys.executable, "-c", script],
                capture_output=True, text=True, timeout=8,
            )
            cookies = json.loads(r.stdout.strip())
            if cookies:
                return cookies
            logger.warning("cookie 提取为空")
        except Exception as exc:
            logger.warning("cookie 提取第 %d 次失败(快速降级): %s", attempt + 1, str(exc)[:60])
    return {}


def gen_stoken(
    *,
    cookies: dict[str, str] | None = None,
    inject_cookies: bool = True,
    verify: bool = True,
    headless: bool = True,
) -> str:
    """反检测生成 __zp_stoken__, 返回 stoken 值(空串表示失败)。

    - ``headless=True``(默认): 无头, 优先真实 Chrome headless=new(channel="chrome"),
      指纹接近真实浏览器可过 BOSS 风控(code=0); 失败退回内置 Chromium 无头。
    - ``headless=False``: 有界面(仅 --headed 调试用)。
    - ``cookies``: 传入时优先使用（如扫码登录所得会话 cookie）;
      未传入且 ``inject_cookies=True`` 时才尝试从本机 Chrome 提取。
    """
    session = dict(cookies) if cookies else {}
    if not session and inject_cookies:
        session = extract_chrome_cookies()
        logger.info("注入用户 cookie: %d 个 (wt2=%s)", len(session), "wt2" in session)
    elif session:
        logger.info("注入会话 cookie: %d 个 (wt2=%s)", len(session), "wt2" in session)

    code: int = -1
    with sync_playwright() as p:
        if headless:
            # 无头必须用真实 Chrome 的 headless=new 模式：
            # Playwright 自带 Chromium 无头指纹太假会被 BOSS 识破(code=38)；
            # 真实 Chrome headless=new 指纹接近真实浏览器，可过(code=0)。
            try:
                browser = p.chromium.launch(
                    channel="chrome", headless=True, args=list(_ANTI_DETECT_ARGS),
                )
            except Exception as exc:
                logger.warning("真实 Chrome 无头启动失败(%s)，退回内置 Chromium 无头", str(exc))
                browser = p.chromium.launch(
                    headless=True, args=list(_ANTI_DETECT_ARGS),
                )
        else:
            browser = p.chromium.launch(
                headless=False, args=list(_ANTI_DETECT_ARGS),
            )
        ctx = browser.new_context(
            user_agent=HEADERS["User-Agent"],
            viewport={"width": 1536, "height": 864},
        )
        ctx.add_init_script(_ANTI_DETECT_INIT_SCRIPT)
        for k, v in session.items():
            try:
                ctx.add_cookies(
                    [{"name": k, "value": v, "domain": ".zhipin.com", "path": "/"}]
                )
            except Exception as exc:
                logger.warning("注入 cookie %s 失败: %s", k, str(exc)[:40])

        page = ctx.new_page()
        page.goto(TRIGGER_URL, wait_until="domcontentloaded", timeout=30000)
        # 事件驱动等待 stoken 出现（security JS 通常 2-5s 内写入，写好后立即返回）
        stoken = ""
        deadline = time.time() + 25
        while time.time() < deadline:
            stoken = {
                c["name"]: c["value"] for c in ctx.cookies()
            }.get("__zp_stoken__", "")
            if stoken:
                break
            page.wait_for_timeout(1500)

        if stoken and verify:
            try:
                res = page.evaluate(
                    f"""async () => {{
                        const r = await fetch('{VERIFY_URL}');
                        return await r.json();
                    }}"""
                )
                code = int(res.get("code", -1))
                logger.info("页面内自校验 code=%s msg=%s", code, str(res.get("message"))[:30])
                if code != 0:
                    logger.warning("stoken 自校验失败, 可能仍被风控")
            except Exception as exc:
                logger.warning("页面内自校验异常: %s", str(exc)[:80])

        browser.close()
    return stoken


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-inject", action="store_true", help="不从 Chrome 提取 cookie")
    parser.add_argument("--no-verify", action="store_true", help="跳过页面内自校验")
    parser.add_argument("--headed", action="store_true", help="有界面模式（调试用）")
    parser.add_argument("--json", action="store_true", help="仅输出 JSON")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    stoken = gen_stoken(
        inject_cookies=not args.no_inject,
        verify=not args.no_verify,
        headless=not args.headed,
    )

    if args.json:
        print(json.dumps({"ok": bool(stoken), "stoken": stoken}))
    else:
        if stoken:
            print(f"✅ __zp_stoken__ = {stoken[:40]}... (len={len(stoken)})")
        else:
            print("❌ 未生成 __zp_stoken__")


if __name__ == "__main__":
    main()
