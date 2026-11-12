"""Profile helpers shared by the Douyin protocol engine."""

from __future__ import annotations

from typing import Any


_AVATAR_KEYS = (
    "avatar_300x300",
    "avatar_168x168",
    "avatar_medium",
    "avatar_larger",
    "avatar_thumb",
)


def _http_url(value: Any) -> str:
    text = str(value or "").strip()
    if text.startswith("//"):
        return "https:" + text
    if text.startswith(("http://", "https://")):
        return text
    return ""


def _avatar_urls(user: dict[str, Any]) -> list[str]:
    urls: list[str] = []

    def add(value: Any) -> None:
        if isinstance(value, dict):
            for item in value.get("url_list") or ():
                add(item)
            add(value.get("url") or value.get("uri"))
            return
        url = _http_url(value)
        if url and url not in urls:
            urls.append(url)

    for key in _AVATAR_KEYS:
        add(user.get(key))
    add(user.get("avatar"))
    add(user.get("avatar_url"))
    return urls


def _avatar_rank(url: str) -> tuple[int, int, int]:
    lower = url.lower()
    if ".heic" in lower or ".heif" in lower:
        image_format = 9
    elif ".jpeg" in lower or ".jpg" in lower:
        image_format = 0
    elif ".webp" in lower or ".png" in lower:
        image_format = 1
    else:
        image_format = 2
    signed = 1 if "-sign." in lower or "x-signature=" in lower else 0
    size = 0 if "300x300" in lower or "168x168" in lower else 1
    return image_format, signed, size


def avatar_from_user(user: dict[str, Any]) -> str:
    """Choose the most browser-friendly avatar URL from a Douyin user object."""
    if not isinstance(user, dict):
        return ""
    urls = _avatar_urls(user)
    return sorted(urls, key=_avatar_rank)[0] if urls else ""
