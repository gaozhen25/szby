# -*- coding: utf-8 -*-
# Copyright (c) 2025 relakkes@gmail.com
#
# This file is part of MediaCrawler project.
# Repository: https://github.com/NanmiCoder/MediaCrawler/blob/main/tools/crawler_util.py
# GitHub: https://github.com/NanmiCoder
# Licensed under NON-COMMERCIAL LEARNING LICENSE 1.1
#

# 声明：本代码仅供学习和研究目的使用。使用者应遵守以下原则：
# 1. 不得用于任何商业用途。
# 2. 使用时应遵守目标平台的使用条款和robots.txt规则。
# 3. 不得进行大规模爬取或对平台造成运营干扰。
# 4. 应合理控制请求频率，避免给目标平台带来不必要的负担。
# 5. 不得用于任何非法或不当的用途。
#
# 详细许可条款请参阅项目根目录下的LICENSE文件。
# 使用本代码即表示您同意遵守上述原则和LICENSE中的所有条款。


# -*- coding: utf-8 -*-
# @Author  : relakkes@gmail.com
# @Time    : 2023/12/2 12:53
# @Desc    : Crawler utility functions

import asyncio
import base64
import json
import os
import random
import re
import urllib
import urllib.parse
from typing import Dict, List, Optional, Tuple, cast

import httpx
from playwright.async_api import BrowserContext, Cookie, Page

from .httpx_util import make_async_client


def _logger():
    """延迟取 logger，避免与 tools.utils 循环导入。"""
    from . import utils

    return utils.logger


def normalize_qrcode_src(src: str) -> str:
    """Normalize Playwright ``src`` values such as ``data:image/png;base64,...``."""
    normalized = (src or "").strip().strip("'\"")
    if not normalized or normalized in {"None", "null", "undefined"}:
        return ""
    return normalized


def get_account_id() -> str:
    """Safe account id for paths (empty if single-account)."""
    import config
    import re

    raw = (getattr(config, "ACCOUNT_ID", "") or "").strip()
    if not raw:
        return ""
    return re.sub(r"[^\w.-]+", "_", raw)[:64]


def get_browser_user_data_dirname(platform: str, *, cdp: bool = False) -> str:
    """
    browser_data 子目录名。多账号时追加 ACCOUNT_ID，避免并发抢同一 Chrome profile。
    例: xhs_user_data_dir / cdp_xhs_acc1_user_data_dir
    """
    import config

    account = get_account_id()
    base = config.USER_DATA_DIR % platform  # e.g. xhs_user_data_dir
    if account:
        # xhs_user_data_dir -> xhs_acc1_user_data_dir
        if base.endswith("_user_data_dir"):
            base = f"{platform}_{account}_user_data_dir"
        else:
            base = f"{base}_{account}"
    prefix = "cdp_" if cdp else ""
    return f"{prefix}{base}"


def get_login_storage_state_path(platform: str) -> str:
    """Path for Playwright storage_state JSON backup of login cookies."""
    import config

    account = get_account_id()
    suffix = f"_{account}" if account else ""
    if config.ENABLE_CDP_MODE:
        filename = f"cdp_{platform}{suffix}_storage_state.json"
    else:
        filename = f"{platform}{suffix}_storage_state.json"
    return os.path.join(os.getcwd(), "browser_data", filename)


async def save_login_storage_state(browser_context: BrowserContext, platform: str) -> None:
    """Persist cookies to JSON so login survives abrupt browser shutdown."""
    import config

    if not config.SAVE_LOGIN_STATE:
        return
    # Cookie 模式以 secrets/*.cookies / --cookies 为准，不写旧 browser_data storage_state
    if getattr(config, "LOGIN_TYPE", "") == "cookie":
        return
    path = get_login_storage_state_path(platform)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    try:
        await browser_context.storage_state(path=path)
        _logger().info(f"[save_login_storage_state] Saved login state to {path}")
    except Exception as exc:
        _logger().warning(f"[save_login_storage_state] Failed to save {path}: {exc}")


async def load_login_storage_state(browser_context: BrowserContext, platform: str) -> bool:
    """Restore cookies from JSON backup before login check."""
    import config

    if not config.SAVE_LOGIN_STATE:
        return False
    # Cookie 模式不加载旧状态，避免覆盖 / 混入过期 Cookie 触发风控
    if getattr(config, "LOGIN_TYPE", "") == "cookie":
        return False
    path = get_login_storage_state_path(platform)
    if not os.path.exists(path):
        return False
    try:
        with open(path, encoding="utf-8") as f:
            state = json.load(f)
        cookies = state.get("cookies") or []
        if not cookies:
            return False
        await browser_context.add_cookies(cookies)
        _logger().info(
            f"[load_login_storage_state] Restored {len(cookies)} cookies from {path}"
        )
        return True
    except Exception as exc:
        _logger().warning(f"[load_login_storage_state] Failed to load {path}: {exc}")
        return False


def show_qrcode(qr_code) -> None:  # type: ignore
    """不在本地弹窗，请在 CDP/浏览器窗口内扫码。"""
    if qr_code:
        _logger().info("[show_qrcode] 请在浏览器窗口内扫描二维码")


async def find_login_qrcode(page: Page, selector: str) -> str:
    """Find login qrcode image from target selector."""
    try:
        elements = await page.wait_for_selector(selector=selector)

        login_qrcode_img = ""
        for _ in range(30):
            login_qrcode_img = normalize_qrcode_src(str(await elements.get_property("src")))  # type: ignore
            if login_qrcode_img:
                break
            await asyncio.sleep(0.2)

        if not login_qrcode_img:
            return ""

        if login_qrcode_img.startswith("data:image"):
            _logger().info("[find_login_qrcode] get qrcode by data uri")
            return login_qrcode_img

        if login_qrcode_img.startswith("http://") or login_qrcode_img.startswith("https://"):
            async with make_async_client(follow_redirects=True) as client:
                _logger().info(f"[find_login_qrcode] get qrcode by url:{login_qrcode_img}")
                resp = await client.get(login_qrcode_img, headers={"User-Agent": get_user_agent()})
                if resp.status_code == 200:
                    image_data = resp.content
                    base64_image = base64.b64encode(image_data).decode("utf-8")
                    return f"data:image/png;base64,{base64_image}"
                raise Exception(f"fetch login image url failed, response message:{resp.text}")

        return login_qrcode_img

    except Exception as e:
        print(e)
        return ""


async def find_qrcode_img_from_canvas(page: Page, canvas_selector: str) -> str:
    """
    find qrcode image from canvas element
    Args:
        page:
        canvas_selector:

    Returns:

    """

    # Wait for Canvas element to load
    canvas = await page.wait_for_selector(canvas_selector)

    # Take screenshot of Canvas element
    screenshot = await canvas.screenshot()

    # Convert screenshot to base64 format
    base64_image = base64.b64encode(screenshot).decode('utf-8')
    return base64_image


def get_user_agent() -> str:
    ua_list = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/104.0.5112.79 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/104.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_14_6) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/104.0.0.0 Safari/537.36",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/103.0.5060.53 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_3) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/99.0.4844.84 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.5112.79 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_14_6) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.5060.53 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_3) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.4844.84 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/117.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/116.0.5112.79 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_14_6) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/113.0.0.0 Safari/537.36",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/112.0.5060.53 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_3) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/111.0.4844.84 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/110.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/109.0.5112.79 Safari/537.36"
    ]
    return random.choice(ua_list)


def get_mobile_user_agent() -> str:
    ua_list = [
        "Mozilla/5.0 (iPhone; CPU iPhone OS 18_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.5 Mobile/15E148 Safari/604.1"
    ]
    return random.choice(ua_list)


def convert_cookies(cookies: Optional[List[Cookie]]) -> Tuple[str, Dict]:
    if not cookies:
        return "", {}
    cookies_str = ";".join([f"{cookie.get('name')}={cookie.get('value')}" for cookie in cookies])
    cookie_dict = dict()
    for cookie in cookies:
        cookie_dict[cookie.get('name')] = cookie.get('value')
    return cookies_str, cookie_dict


async def convert_browser_context_cookies(
    browser_context: BrowserContext, urls: Optional[List[str]] = None
) -> Tuple[str, Dict]:
    cookies = (
        await browser_context.cookies(urls=urls)
        if urls
        else await browser_context.cookies()
    )
    return convert_cookies(cookies)


def convert_str_cookie_to_dict(cookie_str: str) -> Dict:
    cookie_dict: Dict[str, str] = dict()
    if not cookie_str:
        return cookie_dict
    for cookie in cookie_str.split(";"):
        cookie = cookie.strip()
        if not cookie or "=" not in cookie:
            continue
        # value 里可能含 "="，只按第一个等号拆
        key, value = cookie.split("=", 1)
        key = key.strip()
        if not key:
            continue
        cookie_dict[key] = value.strip()
    return cookie_dict


def match_interact_info_count(count_str: str) -> int:
    if not count_str:
        return 0

    match = re.search(r'\d+', count_str)
    if match:
        number = match.group()
        return int(number)
    else:
        return 0


def format_proxy_info(ip_proxy_info) -> Tuple[Optional[Dict], Optional[str]]:
    """format proxy info for playwright and httpx"""
    # fix circular import issue
    from proxy.proxy_ip_pool import IpInfoModel
    ip_proxy_info = cast(IpInfoModel, ip_proxy_info)

    # Playwright proxy server should be in format "host:port" without protocol prefix
    server = f"{ip_proxy_info.ip}:{ip_proxy_info.port}"
    
    playwright_proxy = {
        "server": server,
    }
    
    # Only add username and password if they are not empty
    if ip_proxy_info.user and ip_proxy_info.password:
        playwright_proxy["username"] = ip_proxy_info.user
        playwright_proxy["password"] = ip_proxy_info.password
    
    # httpx 0.28.1 requires passing proxy URL string directly, not a dictionary
    if ip_proxy_info.user and ip_proxy_info.password:
        httpx_proxy = f"http://{ip_proxy_info.user}:{ip_proxy_info.password}@{ip_proxy_info.ip}:{ip_proxy_info.port}"
    else:
        httpx_proxy = f"http://{ip_proxy_info.ip}:{ip_proxy_info.port}"
    return playwright_proxy, httpx_proxy


def extract_text_from_html(html: str) -> str:
    """Extract text from HTML, removing all tags."""
    if not html:
        return ""

    # Remove script and style elements
    clean_html = re.sub(r'<(script|style)[^>]*>.*?</\1>', '', html, flags=re.DOTALL)
    # Remove all other tags
    clean_text = re.sub(r'<[^>]+>', '', clean_html).strip()
    return clean_text

def extract_url_params_to_dict(url: str) -> Dict:
    """Extract URL parameters to dict"""
    url_params_dict = dict()
    if not url:
        return url_params_dict
    parsed_url = urllib.parse.urlparse(url)
    url_params_dict = dict(urllib.parse.parse_qsl(parsed_url.query))
    return url_params_dict
