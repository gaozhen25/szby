import logging
import random
import re
from urllib.parse import parse_qs, urlparse

import httpx

_event_logger = logging.getLogger("starx.mediaspider")
_EVENT_PREFIX = re.compile(r"^\[([A-Za-z0-9_.-]+)\]")


class SafeEventLogger:
    """兼容迁移代码的 logger 边界，只输出固定事件名，不输出传入正文。"""

    def _emit(self, level: int, message, *args, **kwargs) -> None:
        match = _EVENT_PREFIX.match(str(message or ""))
        event = match.group(1) if match else "event"
        error = next(
            (value for value in args if isinstance(value, BaseException)),
            kwargs.get("error") if isinstance(kwargs.get("error"), BaseException) else None,
        )
        if error is not None:
            _event_logger.log(
                level,
                "event=mediaspider.%s error_type=%s",
                event,
                type(error).__name__,
            )
        else:
            _event_logger.log(level, "event=mediaspider.%s", event)

    def debug(self, message, *args, **kwargs):
        self._emit(logging.DEBUG, message, *args, **kwargs)

    def info(self, message, *args, **kwargs):
        self._emit(logging.INFO, message, *args, **kwargs)

    def warning(self, message, *args, **kwargs):
        self._emit(logging.WARNING, message, *args, **kwargs)

    warn = warning

    def error(self, message, *args, **kwargs):
        self._emit(logging.ERROR, message, *args, **kwargs)

    def exception(self, message, *args, **kwargs):
        self._emit(logging.ERROR, message, *args, **kwargs)

    def critical(self, message, *args, **kwargs):
        self._emit(logging.CRITICAL, message, *args, **kwargs)


logger = SafeEventLogger()


def get_current_timestamp():
    import time
    return int(time.time() * 1000)


def get_user_agent():
    return "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120 Safari/537.36"


def format_proxy_info(proxy):
    if not proxy:
        return None, None
    auth = f"{proxy.user}:{proxy.password}@" if proxy.user and proxy.password else ""
    url = f"http://{auth}{proxy.ip}:{proxy.port}"
    return {"server": f"http://{proxy.ip}:{proxy.port}", "username": proxy.user, "password": proxy.password}, url


def convert_str_cookie_to_dict(cookie):
    return dict(
        item.strip().split("=", 1)
        for item in cookie.split(";")
        if "=" in item
    )


def convert_cookies(cookies):
    if not cookies:
        return "", {}
    cookie_dict = {item.get("name"): item.get("value") for item in cookies}
    return ";".join(f"{key}={value}" for key, value in cookie_dict.items()), cookie_dict


async def convert_browser_context_cookies(context, urls=None):
    cookies = await context.cookies(urls=urls) if urls else await context.cookies()
    return convert_cookies(cookies)


def extract_url_params_to_dict(url):
    return {key: values[0] for key, values in parse_qs(urlparse(url).query).items()}


async def find_login_qrcode(page, selector):
    try:
        element = await page.wait_for_selector(selector, timeout=10_000)
        return await element.get_attribute("src") if element else None
    except Exception:
        return None


def show_qrcode(qr_code):
    # 后端服务不打开桌面图片查看器。
    return None


def get_tracks(distance):
    position = 0
    tracks = []
    while position < distance:
        step = min(random.randint(2, 6), distance - position)
        tracks.append(step)
        position += step
    return tracks


class Slide:
    @staticmethod
    async def get_slide_distance(gap_url, bg_url):
        return 0


def make_async_client(*args, **kwargs):
    kwargs.setdefault("follow_redirects", True)
    return httpx.AsyncClient(*args, **kwargs)
