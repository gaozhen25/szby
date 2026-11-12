from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any

from app.services.extract_service.platforms.base import BaseExtractor, ExtractError


@dataclass(frozen=True)
class ExtractedProfileWork:
    id: str
    url: str
    title: str = ""
    cover: str = ""
    published_at: str = ""

    def to_dict(self) -> dict[str, str]:
        return {
            "id": self.id,
            "url": self.url,
            "title": self.title,
            "cover": self.cover,
            "publishedAt": self.published_at,
        }


@dataclass(frozen=True)
class ExtractedProfile:
    platform: str
    url: str
    resolved_url: str
    name: str = ""
    account_id: str = ""
    avatar: str = ""
    description: str = ""
    following: int | None = None
    followers: int | None = None
    liked: int | None = None
    works_count: int | None = None
    metric_labels: dict[str, str] = field(default_factory=dict)
    works: list[ExtractedProfileWork] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "platform": self.platform,
            "url": self.url,
            "resolvedUrl": self.resolved_url,
            "name": self.name,
            "accountId": self.account_id,
            "avatar": self.avatar,
            "description": self.description,
            "following": self.following,
            "followers": self.followers,
            "liked": self.liked,
            "worksCount": self.works_count,
            "metricLabels": dict(self.metric_labels),
            "works": [item.to_dict() for item in self.works],
            "raw": dict(self.raw),
        }


class BaseProfileExtractor(BaseExtractor):
    def __init__(
        self,
        url: str,
        *,
        limit: int,
        session=None,
        timeout: int = 10,
        browser_renderer=None,
    ):
        super().__init__(url, session=session, timeout=timeout)
        self.limit = limit
        self.browser_renderer = browser_renderer


def count_value(value: Any) -> int | None:
    """解析平台公开展示的计数；带“+”时返回其公开下界。"""

    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    if isinstance(value, float):
        return int(value) if value >= 0 else None
    text = str(value).strip().lower().replace(",", "").replace("+", "")
    if not text:
        return None
    multiplier = 1
    for suffix, scale in (
        ("亿", 100_000_000),
        ("万", 10_000),
        ("w", 10_000),
        ("k", 1_000),
    ):
        if text.endswith(suffix):
            multiplier = scale
            text = text[: -len(suffix)].strip()
            break
    try:
        result = int(Decimal(text) * multiplier)
    except (InvalidOperation, ValueError):
        return None
    return result if result >= 0 else None


def display_count(value: Any) -> str:
    return str(value).strip() if value is not None else ""


__all__ = [
    "BaseProfileExtractor",
    "ExtractError",
    "ExtractedProfile",
    "ExtractedProfileWork",
    "count_value",
    "display_count",
]
