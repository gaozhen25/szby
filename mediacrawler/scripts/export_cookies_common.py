#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
扫码登录后导出 Cookie（热点宝 / 快手）。

小红书 / 抖音请用::

    uv run python scripts/export_cookies.py

本模块仅供::

    export_dyhot_cookies.py / export_ks_cookies.py
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple

ROOT = Path(__file__).resolve().parents[1]
SECRETS_DIR = ROOT / "secrets"

PLATFORM_META: Dict[str, Dict] = {
    "dy": {
        "label": "抖音搜索",
        "config_platform": "dy",
        "default_output": SECRETS_DIR / "dy.cookies.json",
        "required_any": ("sessionid", "LOGIN_STATUS"),
        "cookie_urls": [
            "https://douyin.com",
            "https://www.douyin.com",
            "https://creator.douyin.com",
            "https://douhot.douyin.com",
            "https://live.douyin.com",
        ],
    },
    "xhs": {
        "label": "小红书",
        "config_platform": "xhs",
        "default_output": SECRETS_DIR / "xhs.cookies.json",
        "required_any": ("web_session",),
        "cookie_urls": None,  # 按 XHS_INTERNATIONAL 在运行时决定
    },
    "dyhot": {
        "label": "抖音热点宝",
        "config_platform": "dyhot",
        "default_output": SECRETS_DIR / "dyhot.cookies.json",
        "required_any": ("sessionid", "sessionid_douhot"),
        "cookie_urls": [
            "https://douhot.douyin.com",
            "https://www.douyin.com",
            "https://douyin.com",
        ],
    },
    "ks": {
        "label": "快手",
        "config_platform": "ks",
        "default_output": SECRETS_DIR / "ks.cookies.json",
        "required_any": ("passToken",),
        "cookie_urls": ["https://www.kuaishou.com"],
    },
}


def _setup_runtime() -> None:
    os.chdir(ROOT)
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))


def _apply_export_config(platform: str) -> None:
    import config

    meta = PLATFORM_META[platform]
    config.PLATFORM = meta["config_platform"]
    config.LOGIN_TYPE = "qrcode"
    config.COOKIES = ""
    # 原始 CDP：独立 browser_data/cdp_*_user_data_dir + storage_state 复用登录
    config.HEADLESS = False
    config.CDP_HEADLESS = False
    config.ENABLE_CDP_MODE = True
    config.CDP_USE_SYSTEM_PROFILE = False
    config.CDP_CONNECT_EXISTING = False
    config.SAVE_LOGIN_STATE = True
    config.AUTO_CLOSE_BROWSER = True
    config.ENABLE_IP_PROXY = False


def _cookie_urls_for(platform: str) -> List[str]:
    meta = PLATFORM_META[platform]
    if meta["cookie_urls"] is not None:
        return list(meta["cookie_urls"])
    import config

    if config.XHS_INTERNATIONAL:
        return ["https://www.rednote.com"]
    return ["https://www.xiaohongshu.com"]


def _merge_cookie_string(cookies: Sequence[dict]) -> Tuple[str, Dict[str, str]]:
    """同名 Cookie 后者覆盖前者，避免多域重复。"""
    merged: Dict[str, str] = {}
    for item in cookies:
        name = item.get("name")
        value = item.get("value")
        if name and value is not None:
            merged[str(name)] = str(value)
    cookie_str = ";".join(f"{k}={v}" for k, v in merged.items())
    return cookie_str, merged


async def _collect_cookies(browser_context, urls: List[str]) -> Tuple[str, Dict[str, str]]:
    from tools import utils

    raw = await browser_context.cookies(urls=urls)
    return _merge_cookie_string(raw)


def _validate(platform: str, cookie_dict: Dict[str, str]) -> List[str]:
    meta = PLATFORM_META[platform]
    keys = meta.get("required_any") or ()
    if not keys:
        return []
    if any(cookie_dict.get(k) for k in keys):
        return []
    return [f"{' 或 '.join(keys)} 至少一项"]


def _write_cookie_file(
    path: Path,
    cookie_str: str,
    *,
    platform: str,
    cookie_dict: Optional[Dict[str, str]] = None,
    account_id: str = "default",
) -> Path:
    """写入 Cookie：默认 JSON（仅 platform + cookies）；路径以 .cookies 结尾则写纯文本。"""
    import json

    _ = cookie_dict, account_id
    path.parent.mkdir(parents=True, exist_ok=True)
    cookie = cookie_str.strip().replace("\n", "").replace("\r", "")

    # 显式纯文本路径
    if path.name.endswith(".cookies") or (
        ".cookies." in path.name and not path.name.endswith(".json")
    ):
        path.write_text(cookie + "\n", encoding="utf-8")
        try:
            path.chmod(0o600)
        except OSError:
            pass
        return path

    if path.suffix != ".json":
        path = Path(str(path) + ".json")

    payload = {"platform": platform, "cookies": cookie}
    path.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return path


async def _launch_context(crawler, playwright):
    import config
    from tools import utils
    from tools.cdp_browser import CDPBrowserManager

    headless = bool(config.HEADLESS if not config.ENABLE_CDP_MODE else config.CDP_HEADLESS)
    mode = "无头" if headless else "有头"
    if config.ENABLE_CDP_MODE:
        # 直接走 CDP，禁止 crawler 回退到 Playwright（否则看不到本地 Chrome）
        utils.logger.info(f"[export_cookies] 使用 CDP 模式启动浏览器（{mode}）")
        manager = CDPBrowserManager()
        crawler.cdp_manager = manager
        browser_context = await manager.launch_and_connect(
            playwright=playwright,
            playwright_proxy=None,
            user_agent=getattr(crawler, "user_agent", None),
            headless=headless,
        )
        try:
            await manager.add_stealth_script()
        except Exception:
            pass
        info = await manager.get_browser_info()
        utils.logger.info(f"[export_cookies] CDP 已连接: {info}")
        return browser_context

    utils.logger.info(f"[export_cookies] 使用标准模式启动浏览器（{mode}）")
    chromium = playwright.chromium
    user_agent = getattr(crawler, "user_agent", None)
    browser_context = await crawler.launch_browser(
        chromium, None, user_agent, headless=headless
    )
    stealth = ROOT / "libs" / "stealth.min.js"
    if stealth.is_file():
        await browser_context.add_init_script(path=str(stealth))
    return browser_context


async def _cleanup_cdp(crawler) -> None:
    cdp_manager = getattr(crawler, "cdp_manager", None)
    if cdp_manager:
        try:
            await cdp_manager.cleanup()
        except Exception:
            pass


async def _is_already_logged_in(
    platform: str,
    browser_context,
    context_page,
) -> bool:
    """若浏览器上下文已有登录态，则跳过扫码，直接导出 Cookie。"""
    from tools import utils

    urls = _cookie_urls_for(platform)
    raw = await browser_context.cookies(urls=urls)
    _, cookie_dict = _merge_cookie_string(raw)

    if platform == "dy":
        if cookie_dict.get("LOGIN_STATUS") == "1" or cookie_dict.get("sessionid"):
            utils.logger.info("[export_cookies] 抖音已登录，跳过扫码，直接导出 Cookie")
            return True
        return False

    if platform == "dyhot":
        if (
            cookie_dict.get("sessionid")
            or cookie_dict.get("sessionid_douhot")
            or cookie_dict.get("sessionid_ss")
        ):
            utils.logger.info("[export_cookies] 热点宝已登录，跳过扫码，直接导出 Cookie")
            return True
        return False

    if platform == "ks":
        if cookie_dict.get("passToken"):
            utils.logger.info("[export_cookies] 快手已登录，跳过扫码，直接导出 Cookie")
            return True
        return False

    if platform == "xhs":
        try:
            user_profile_selector = (
                "xpath=//a[contains(@href, '/user/profile/')]//span[text()='我']"
            )
            if await context_page.is_visible(user_profile_selector, timeout=800):
                utils.logger.info(
                    "[export_cookies] 小红书已登录（UI「我」），跳过扫码，直接导出 Cookie"
                )
                return True
        except Exception:
            pass
        if cookie_dict.get("web_session"):
            utils.logger.info(
                "[export_cookies] 小红书已有 web_session，跳过扫码，直接导出 Cookie"
            )
            return True
        return False

    return False


async def _export_dy(browser_context, context_page) -> None:
    from media_platform.douyin.login import DouYinLogin
    from tools import utils

    await context_page.goto("https://www.douyin.com", wait_until="domcontentloaded")
    if await _is_already_logged_in("dy", browser_context, context_page):
        return

    utils.logger.info("[export_cookies] 未登录，开始抖音扫码")
    login_obj = DouYinLogin(
        login_type="qrcode",
        login_phone="",
        browser_context=browser_context,
        context_page=context_page,
        cookie_str="",
    )
    await login_obj.begin()


async def _export_xhs(browser_context, context_page) -> None:
    import asyncio

    import config
    from media_platform.xhs.login import XiaoHongShuLogin
    from tools import utils

    index_url = (
        "https://www.rednote.com"
        if config.XHS_INTERNATIONAL
        else "https://www.xiaohongshu.com"
    )
    await context_page.goto(index_url, wait_until="domcontentloaded", timeout=60000)
    await asyncio.sleep(1.5)

    if await _is_already_logged_in("xhs", browser_context, context_page):
        return

    qrcode_img_selector = "xpath=//img[@class='qrcode-img']"
    has_qr = await context_page.locator(qrcode_img_selector).count() > 0
    if not has_qr:
        login_selectors = [
            "xpath=//*[@id='app']/div[1]/div[2]/div[1]/ul/div[1]/button",
            "xpath=//button[contains(., '登录')]",
            "text=登录",
        ]
        for selector in login_selectors:
            try:
                loc = context_page.locator(selector).first
                if await loc.count() == 0:
                    continue
                await loc.click(timeout=3000)
                utils.logger.info(f"[export_cookies] 已点击登录入口: {selector}")
                break
            except Exception:
                continue
        else:
            utils.logger.warning(
                "[export_cookies] 未自动点到登录按钮，请在浏览器窗口手动点「登录」"
            )

    utils.logger.info("[export_cookies] 请在 CDP 浏览器窗口内扫码登录")
    login_obj = XiaoHongShuLogin(
        login_type="qrcode",
        login_phone="",
        browser_context=browser_context,
        context_page=context_page,
        cookie_str="",
    )
    await login_obj.begin()


async def _export_dyhot(browser_context, context_page) -> None:
    """打开热点宝；复用 CDP 目录登录态，已登录则直接导出。"""
    from tools import utils

    # 先看 CDP user-data 里是否已有登录 Cookie（与小红书复用方式一致）
    if await _is_already_logged_in("dyhot", browser_context, context_page):
        await context_page.goto(
            "https://douhot.douyin.com/",
            wait_until="domcontentloaded",
            timeout=60000,
        )
        await asyncio.sleep(2)
        url = context_page.url or ""
        if "douhot.douyin.com" in url and "open.douyin.com" not in url:
            utils.logger.info(
                f"[export_cookies] 热点宝登录态已复用，当前页: {url}"
            )
            return
        utils.logger.warning(
            f"[export_cookies] 有 session Cookie 但仍跳转授权页: {url}，请完成一次授权"
        )
    else:
        await context_page.goto(
            "https://douhot.douyin.com/",
            wait_until="domcontentloaded",
            timeout=60000,
        )
        await asyncio.sleep(1.5)
        if await _is_already_logged_in("dyhot", browser_context, context_page):
            url = context_page.url or ""
            if "douhot.douyin.com" in url and "open.douyin.com" not in url:
                utils.logger.info("[export_cookies] 热点宝已登录，跳过扫码")
                return

    utils.logger.info(
        "[export_cookies] 请在 CDP 浏览器中完成「抖音热点宝」登录/授权；"
        "完成后会写入 browser_data 以便下次复用"
    )

    deadline_rounds = 90
    for i in range(deadline_rounds):
        url = context_page.url or ""
        logged = await _is_already_logged_in("dyhot", browser_context, context_page)
        on_douhot = "douhot.douyin.com" in url and "open.douyin.com" not in url
        if logged and on_douhot:
            await asyncio.sleep(2)
            return

        if i == 0 or i % 10 == 0:
            utils.logger.warning(
                f"[export_cookies] 仍未登录热点宝 ({i * 2}s) url={url}；"
                "请扫码/授权，确认能看到搜索热点榜"
            )
        await asyncio.sleep(2)

    raise RuntimeError(
        "等待热点宝登录超时：Cookie 中仍无 sessionid / sessionid_douhot。"
        "请确认已登录 douhot.douyin.com 后再重新导出。"
    )


async def _export_ks(browser_context, context_page) -> None:
    from media_platform.kuaishou.login import KuaishouLogin
    from tools import utils

    await context_page.goto(
        "https://www.kuaishou.com?isHome=1",
        wait_until="domcontentloaded",
    )
    await asyncio.sleep(1.5)

    if await _is_already_logged_in("ks", browser_context, context_page):
        return

    utils.logger.info("[export_cookies] 未登录，开始快手扫码")
    login_obj = KuaishouLogin(
        login_type="qrcode",
        login_phone="",
        browser_context=browser_context,
        context_page=context_page,
        cookie_str="",
    )
    await login_obj.begin()


LOGIN_HANDLERS: Dict[str, Callable] = {
    "dy": _export_dy,
    "xhs": _export_xhs,
    "dyhot": _export_dyhot,
    "ks": _export_ks,
}

CRAWLER_FACTORY: Dict[str, Callable] = {
    "dy": lambda: __import__("media_platform.douyin.core", fromlist=["DouYinCrawler"]).DouYinCrawler(),
    "xhs": lambda: __import__("media_platform.xhs.core", fromlist=["XiaoHongShuCrawler"]).XiaoHongShuCrawler(),
    "dyhot": lambda: __import__("media_platform.dyhot.core", fromlist=["DouHotCrawler"]).DouHotCrawler(),
    "ks": lambda: __import__("media_platform.kuaishou.core", fromlist=["KuaishouCrawler"]).KuaishouCrawler(),
}


async def export_cookies_async(
    platform: str,
    output: Optional[Path] = None,
    *,
    use_cdp: Optional[bool] = None,
    account_id: str = "default",
    headless: Optional[bool] = None,
) -> Path:
    if platform not in PLATFORM_META:
        raise ValueError(f"未知平台: {platform}")

    _setup_runtime()
    _apply_export_config(platform)

    import config
    from playwright.async_api import async_playwright
    from tools import utils

    if use_cdp is not None:
        config.ENABLE_CDP_MODE = use_cdp
    if headless is not None:
        config.HEADLESS = headless
        config.CDP_HEADLESS = headless

    meta = PLATFORM_META[platform]
    out_path = (output or meta["default_output"]).expanduser()
    if not out_path.is_absolute():
        out_path = (ROOT / out_path).resolve()
    # 多账号：未显式 -o 时写 secrets/{platform}.cookies.{account_id}.json
    if not output and account_id and account_id != "default":
        out_path = SECRETS_DIR / f"{platform}.cookies.{account_id}.json"

    headless_now = bool(
        config.HEADLESS if not config.ENABLE_CDP_MODE else config.CDP_HEADLESS
    )
    if getattr(config, "CDP_USE_SYSTEM_PROFILE", False):
        utils.logger.info(
            f"[export_cookies] {meta['label']}：CDP 打开日常浏览器 Profile，"
            f"已登录则无需扫码 → {out_path}"
        )
        utils.logger.info(
            "[export_cookies] 若 Chrome 已打开，脚本会自动退出并用 CDP 重新打开（保留登录态）"
        )
    else:
        utils.logger.info(
            f"[export_cookies] {meta['label']}：原始 CDP（browser_data 复用），"
            f"已登录则跳过扫码 → {out_path}"
        )
    if headless_now:
        utils.logger.info(
            "[export_cookies] 当前为无头；如需看页面请加 --headed"
        )

    crawler = CRAWLER_FACTORY[platform]()
    cookie_urls = _cookie_urls_for(platform)

    async with async_playwright() as playwright:
        browser_context = await _launch_context(crawler, playwright)
        context_page = await browser_context.new_page()
        try:
            await LOGIN_HANDLERS[platform](browser_context, context_page)
            cookie_str, cookie_dict = await _collect_cookies(browser_context, cookie_urls)
            if not cookie_str:
                raise RuntimeError("未采集到 Cookie，请确认登录是否成功")

            missing = _validate(platform, cookie_dict)
            if missing:
                utils.logger.warning(
                    f"[export_cookies] Cookie 缺少常见字段: {', '.join(missing)}；仍将写入文件"
                )

            out_path = _write_cookie_file(
                out_path,
                cookie_str,
                platform=platform,
                cookie_dict=cookie_dict,
                account_id=account_id,
            )
            utils.logger.info(
                f"[export_cookies] 已写入 {out_path} "
                f"(account={account_id}, {len(cookie_dict)} 个键, {len(cookie_str)} 字符)"
            )
            # 先落盘登录态，再关浏览器（否则像热点宝无法像小红书那样复用）
            try:
                import config as cfg
                from tools import crawler_util as cu

                if cfg.SAVE_LOGIN_STATE:
                    await cu.save_login_storage_state(browser_context, cfg.PLATFORM)
                    await asyncio.sleep(1.5)
            except Exception as exc:
                utils.logger.warning(f"[export_cookies] 保存登录态失败: {exc}")
            return out_path
        finally:
            # 由 CDP cleanup 负责关浏览器；勿先 close context，否则存不了 storage_state
            await _cleanup_cdp(crawler)
            if not getattr(crawler, "cdp_manager", None):
                try:
                    await browser_context.close()
                except Exception:
                    pass


def build_arg_parser(platform: str) -> argparse.ArgumentParser:
    meta = PLATFORM_META[platform]
    parser = argparse.ArgumentParser(
        description=f"扫码登录并导出 {meta['label']} Cookie 到 secrets/",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例:\n"
            f"  uv run python scripts/export_{platform}_cookies.py\n"
            f"  uv run python scripts/export_{platform}_cookies.py -o secrets/{platform}.cookies.json\n"
            f"  uv run python scripts/export_{platform}_cookies.py --account-id acc2\n"
        ),
    )
    parser.add_argument(
        "-o",
        "--output",
        default="",
        help=f"输出路径，默认 {meta['default_output'].relative_to(ROOT)}（仅含 platform/cookies）",
    )
    parser.add_argument(
        "--account-id",
        default="default",
        help="多账号时写入 secrets/{platform}.cookies.<id>.json（默认写主文件）",
    )
    parser.add_argument(
        "--no-cdp",
        action="store_true",
        help="禁用 CDP，改用 Playwright 自带 Chromium",
    )
    parser.add_argument(
        "--cdp",
        action="store_true",
        help="强制启用 CDP（默认已启用，可省略）",
    )
    parser.add_argument(
        "--headed",
        action="store_true",
        help="有头浏览器（默认已是有头，可省略）",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="无头浏览器（一般不推荐；扫码需能看到页面）",
    )
    return parser


def main(platform: str, argv: Optional[Sequence[str]] = None) -> int:
    parser = build_arg_parser(platform)
    args = parser.parse_args(list(argv) if argv is not None else None)

    use_cdp: Optional[bool] = None
    if args.cdp and args.no_cdp:
        print("不能同时指定 --cdp 与 --no-cdp", file=sys.stderr)
        return 2
    if args.cdp:
        use_cdp = True
    elif args.no_cdp:
        use_cdp = False

    headless: Optional[bool] = None
    if args.headed and args.headless:
        print("不能同时指定 --headed 与 --headless", file=sys.stderr)
        return 2
    if args.headed:
        headless = False
    elif args.headless:
        headless = True

    output = Path(args.output) if args.output else None
    try:
        out_path = asyncio.run(
            export_cookies_async(
                platform,
                output=output,
                use_cdp=use_cdp,
                account_id=args.account_id or "default",
                headless=headless,
            )
        )
    except KeyboardInterrupt:
        print("\n已取消", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"导出失败: {exc}", file=sys.stderr)
        return 1

    print(f"Cookie 已保存: {out_path}")
    if platform == "ks":
        print(
            "验证: uv run main.py --platform ks --lt cookie "
            f'--cookies "$(cat {out_path})" --type search --keywords 足球 --headless true'
        )
    else:
        print(f"验证: uv run python scripts/run_with_cookies.py {platform} --max-notes 10")
    return 0
