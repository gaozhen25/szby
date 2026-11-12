"""受支持平台的别名与创作者链接解析。"""

from collections.abc import Sequence
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from .models import InvalidCrawlRequestError, UnsupportedPlatformError

SUPPORTED_PLATFORMS = {"xhs", "dy", "ks"}
PLATFORM_ALIASES = {
    "xhs": "xhs",
    "xiaohongshu": "xhs",
    "小红书": "xhs",
    "dy": "dy",
    "douyin": "dy",
    "抖音": "dy",
    "ks": "ks",
    "kuaishou": "ks",
    "快手": "ks",
}
DOMAIN_SUFFIXES = {
    "xhs": ("xiaohongshu.com", "xhslink.com", "rednote.com"),
    "dy": ("douyin.com", "iesdouyin.com"),
    "ks": ("kuaishou.com", "gifshow.com"),
}


def normalize_public_url(value: str) -> str:
    """Normalize stable URL parts while preserving platform access tokens."""
    parsed = urlparse(value.strip())
    host = (parsed.hostname or "").lower()
    path = parsed.path.rstrip("/") or "/"
    query = urlencode(
        sorted(
            (key, item)
            for key, item in parse_qsl(parsed.query, keep_blank_values=True)
            if not key.lower().startswith("utm_")
        ),
        doseq=True,
    )
    return urlunparse((parsed.scheme.lower(), host, path, "", query, ""))


def extract_douyin_sec_user_id(value: str) -> str:
    """从标准抖音账号主页路径中提取 sec_user_id。"""

    parsed = urlparse(value.strip())
    host = (parsed.hostname or "").lower()
    if not _host_matches(host, DOMAIN_SUFFIXES["dy"]):
        return ""
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) < 2 or parts[0] != "user":
        return ""
    return parts[1].strip()


def extract_xiaohongshu_user_id(value: str) -> str:
    """从小红书标准账号主页路径中提取 user_id。"""

    parsed = urlparse(value.strip())
    host = (parsed.hostname or "").lower()
    if not _host_matches(host, ("xiaohongshu.com", "rednote.com")):
        return ""
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) < 3 or parts[:2] != ["user", "profile"]:
        return ""
    return parts[2].strip()


def normalize_platform(value: str) -> str:
    key = value.strip().lower()
    try:
        return PLATFORM_ALIASES[key]
    except KeyError as exc:
        raise UnsupportedPlatformError("不支持的平台") from exc


def normalize_keywords(value: str | Sequence[str]) -> list[str]:
    raw = value.split(",") if isinstance(value, str) else value
    result = [item.strip() for item in raw if isinstance(item, str) and item.strip()]
    if not result:
        raise InvalidCrawlRequestError("关键词不能为空")
    return result


def resolve_creator_platform(creator_url: str) -> str:
    parsed = urlparse(creator_url.strip())
    if parsed.scheme != "https" or not parsed.hostname:
        raise InvalidCrawlRequestError("creator_url 必须是绝对 HTTPS URL")
    host = parsed.hostname.lower()
    for platform, suffixes in DOMAIN_SUFFIXES.items():
        if any(host == suffix or host.endswith(f".{suffix}") for suffix in suffixes):
            return platform
    raise UnsupportedPlatformError("无法从博主链接识别受支持平台")


def resolve_content_platform(content_url: str) -> str:
    parsed = urlparse(content_url.strip())
    if parsed.scheme != "https" or not parsed.hostname:
        raise InvalidCrawlRequestError("content_url 必须是绝对 HTTPS URL")

    host = parsed.hostname.lower()
    path = parsed.path.rstrip("/")
    if _host_matches(host, DOMAIN_SUFFIXES["xhs"]):
        if host.endswith("xhslink.com") or path.startswith(("/explore/", "/discovery/item/")):
            return "xhs"
    elif _host_matches(host, DOMAIN_SUFFIXES["dy"]):
        if host == "v.douyin.com" or path.startswith(("/video/", "/note/")):
            return "dy"
    elif _host_matches(host, DOMAIN_SUFFIXES["ks"]):
        if host == "v.kuaishou.com" or path.startswith(("/short-video/", "/f/")):
            return "ks"
    raise UnsupportedPlatformError("无法从内容链接识别受支持平台")


def _host_matches(host: str, suffixes: tuple[str, ...]) -> bool:
    return any(host == suffix or host.endswith(f".{suffix}") for suffix in suffixes)
