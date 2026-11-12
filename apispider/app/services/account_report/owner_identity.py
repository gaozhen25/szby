"""从已配置主页 URL 解析稳定 owner ID；不加载任何平台爬虫运行时。"""

from __future__ import annotations

import re
from urllib.parse import unquote, urlparse


_PROFILE_RULES = {
    "xhs": (("xiaohongshu.com", "rednote.com"), re.compile(r"^/user/profile/([^/]+?)/?$")),
    "dy": (("douyin.com", "iesdouyin.com"), re.compile(r"^/user/([^/]+?)/?$")),
    "ks": (("kuaishou.com", "gifshow.com"), re.compile(r"^/profile/([^/]+?)/?$")),
}
_OWNER_ID_PATTERN = re.compile(r"^[A-Za-z0-9._~-]+$")


def _host_matches(host: str, suffixes: tuple[str, ...]) -> bool:
    return any(host == suffix or host.endswith(f".{suffix}") for suffix in suffixes)


def parse_planned_owner_id(platform: str, creator_url: str) -> str | None:
    """仅接受平台正式主页路径；短链和内容页返回未知。"""

    rule = _PROFILE_RULES.get(str(platform or "").strip().lower())
    if rule is None:
        return None
    parsed = urlparse(str(creator_url or "").strip())
    suffixes, path_pattern = rule
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return None
    if not _host_matches(parsed.hostname.lower(), suffixes):
        return None
    match = path_pattern.fullmatch(parsed.path)
    if match is None:
        return None
    owner_id = unquote(match.group(1)).strip()
    if not owner_id or _OWNER_ID_PATTERN.fullmatch(owner_id) is None:
        return None
    return owner_id
