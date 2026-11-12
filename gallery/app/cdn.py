"""Host allowlist shared by the CDN proxy and the material library."""

from __future__ import annotations

from urllib.parse import urlparse

ALLOWED_HOST_BITS = (
    "douyin",
    "douyinvod",
    "douyinpic",
    "byteimg",
    "bytevcloud",
    "amemv",
    "snssdk",
    "xhscdn",
    "xiaohongshu",
)


def host_allowed(url: str) -> bool:
    if not url.startswith("http"):
        return False
    host = (urlparse(url).hostname or "").lower()
    return any(bit in host for bit in ALLOWED_HOST_BITS)


def referer_for(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    if "douyin" in host or "amemv" in host or "byte" in host:
        return "https://www.douyin.com/"
    return "https://www.xiaohongshu.com/"
