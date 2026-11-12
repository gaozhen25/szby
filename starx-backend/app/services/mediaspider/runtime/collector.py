from __future__ import annotations

import asyncio
import inspect
import re
from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote

from ..models import (
    CrawlResult,
    CrawlerProgressEvent,
    PartialResultCallback,
    ProgressCallback,
)
from ..vendor.base import AbstractStore
from ..vendor import tools as utils
from ..vendor.user_hash import anonymize_user_id, mask_nickname


_URL_PATTERN = re.compile(r"(?i)(?:https?://|www\.)\S+")
_EMAIL_PATTERN = re.compile(r"(?i)\b[\w.+-]+@[\w.-]+\.[a-z]{2,}\b")
_PHONE_PATTERN = re.compile(
    r"(?<!\d)(?:\+?86[\s-]?)?1[3-9](?:[\s-]?\d){9}(?!\d)"
)
_CONTACT_PATTERN = re.compile(
    r"(?i)(?:微信|wechat|vx|qq)\s*[:：=]?\s*[^\s,;，；。！？!?]+"
)
_CREDENTIAL_PATTERN = re.compile(
    r"(?i)\b(?:cookie|cookies|token|authorization|session|secret|password|passwd)"
    r"\s*[:=]\s*(?:bearer\s+)?[^\s,;，；]+"
)
_PROFILE_URL_TEMPLATES = {
    "xhs": "https://www.xiaohongshu.com/user/profile/{creator_id}",
    "dy": "https://www.douyin.com/user/{creator_id}",
    "ks": "https://www.kuaishou.com/profile/{creator_id}",
}


def build_public_profile_url(platform: str, raw_id: Any) -> str:
    """只用支持平台的稳定原始 ID 构造规范公开主页链接。"""

    normalized_platform = str(platform or "").strip().lower()
    normalized_raw_id = str(raw_id or "").strip()
    profile_template = _PROFILE_URL_TEMPLATES.get(normalized_platform)
    if not profile_template or not normalized_raw_id:
        return ""
    return profile_template.format(
        creator_id=quote(normalized_raw_id, safe="-._~")
    )


async def emit_progress(
    callback: ProgressCallback | None, event: CrawlerProgressEvent
) -> None:
    """调用同步或异步进度回调，并隔离所有回调异常。"""
    if callback is None:
        return
    try:
        result = callback(event)
        if inspect.isawaitable(result):
            await result
    except Exception:
        utils.logger.warning(
            f"[ProgressCallback.{event.platform}.{event.action}]"
        )


@dataclass
class _OrderedRecords:
    items: list[dict[str, Any]] = field(default_factory=list)
    indexes: dict[str, int] = field(default_factory=dict)

    def upsert(self, item: dict[str, Any], keys: tuple[str, ...]) -> bool:
        copied = _without_cookies(item)
        identity = next(
            (str(copied[key]) for key in keys if copied.get(key) not in (None, "")),
            None,
        )
        if identity is None:
            self.items.append(copied)
            return True
        elif identity in self.indexes:
            self.items[self.indexes[identity]] = copied
            return False
        else:
            self.indexes[identity] = len(self.items)
            self.items.append(copied)
            return True


def _without_cookies(value):
    if isinstance(value, dict):
        return {
            key: _without_cookies(item)
            for key, item in value.items()
            if str(key).lower().replace("-", "_") not in {"cookie", "cookies"}
        }
    if isinstance(value, list):
        return [_without_cookies(item) for item in value]
    return value


def _safe_text(value: Any, *, max_length: int = 60) -> str:
    text = "" if value is None else str(value)
    for pattern in (
        _URL_PATTERN,
        _EMAIL_PATTERN,
        _PHONE_PATTERN,
        _CONTACT_PATTERN,
        _CREDENTIAL_PATTERN,
    ):
        text = pattern.sub("", text)
    return " ".join(text.split())[:max_length]


def _safe_title(item: dict[str, Any]) -> str:
    value = next(
        (item.get(key) for key in ("title", "desc", "caption") if item.get(key)),
        "",
    )
    return _safe_text(value)


def _safe_subject(item: dict[str, Any]) -> str:
    value = next(
        (item.get(key) for key in ("nickname", "name") if item.get(key)),
        "",
    )
    return mask_nickname(_safe_text(value))


class MemoryResultCollector:
    def __init__(
        self,
        platform,
        crawl_type,
        keywords,
        creator_url,
        on_progress=None,
        on_partial_result: PartialResultCallback | None = None,
    ):
        self.platform = platform
        self.crawl_type = crawl_type
        self.keywords = list(keywords)
        self.creator_url = creator_url
        self.on_progress = on_progress
        self.on_partial_result = on_partial_result
        self._partial_result_notified = False
        self._contents = _OrderedRecords()
        self._comments = _OrderedRecords()
        self._creators = _OrderedRecords()

    def store_content(self, item):
        return self._contents.upsert(
            item, ("note_id", "aweme_id", "video_id", "content_id")
        )

    def store_comment(self, item):
        return self._comments.upsert(item, ("comment_id",))

    def store_creator(self, item):
        inserted = self._creators.upsert(item, ("creator_hash",))
        if inserted and self.on_partial_result is not None:
            try:
                asyncio.get_running_loop()
            except RuntimeError:
                partial = self.on_partial_result(self.to_result())
                if inspect.isawaitable(partial):
                    asyncio.run(partial)
                self._partial_result_notified = True
        return inserted

    async def emit_record_event(
        self, kind: str, item: dict[str, Any], inserted: bool
    ) -> None:
        if not inserted:
            return
        result = self.to_result()
        if (
            kind == "creator"
            and self.on_partial_result is not None
            and not self._partial_result_notified
        ):
            partial = self.on_partial_result(result)
            if inspect.isawaitable(partial):
                await partial
            self._partial_result_notified = True
        if self.on_progress is None:
            return
        event = CrawlerProgressEvent(
            platform=self.platform,
            crawlType=self.crawl_type,
            action={
                "content": "content_discovered",
                "creator": "creator_discovered",
                "comment": "comments_updated",
            }[kind],
            status="running",
            message={
                "content": "发现公开内容",
                "creator": "发现公开博主",
                "comment": "更新评论计数",
            }[kind],
            subject=_safe_subject(item) if kind == "creator" else "",
            contentTitle=_safe_title(item) if kind == "content" else "",
            contentCount=result.content_count,
            creatorCount=result.creator_count,
            commentCount=result.comment_count,
        )
        await emit_progress(self.on_progress, event)

    def to_result(self) -> CrawlResult:
        return CrawlResult(
            platform=self.platform,
            crawl_type=self.crawl_type,
            keywords=self.keywords,
            creator_url=self.creator_url,
            contents=self._contents.items,
            comments=self._comments.items,
            creators=self._creators.items,
            content_count=len(self._contents.items),
            comment_count=len(self._comments.items),
            creator_count=len(self._creators.items),
        )


_collector_var: ContextVar[MemoryResultCollector | None] = ContextVar(
    "mediaspider_collector", default=None
)


def bind_collector(collector: MemoryResultCollector) -> Token:
    return _collector_var.set(collector)


def reset_collector(token: Token) -> None:
    _collector_var.reset(token)


def _current_collector() -> MemoryResultCollector:
    collector = _collector_var.get()
    if collector is None:
        raise RuntimeError("MemoryStore 未绑定当前调用的 Collector")
    return collector


class MemoryStore(AbstractStore):
    async def store_content(self, content_item):
        collector = _current_collector()
        inserted = collector.store_content(content_item)
        await collector.emit_record_event("content", content_item, inserted)

    async def store_comment(self, comment_item):
        collector = _current_collector()
        inserted = collector.store_comment(comment_item)
        await collector.emit_record_event("comment", comment_item, inserted)

    async def store_creator(self, creator):
        collector = _current_collector()
        inserted = collector.store_creator(creator)
        await collector.emit_record_event("creator", creator, inserted)


def build_safe_creator(
    platform: str,
    raw_id: Any,
    raw: dict[str, Any],
    *,
    raw_data: dict[str, Any] | None = None,
):
    """构造稳定兼容字段，并保留平台返回的原始公开博主资料。"""

    profile = raw.get("profile") or {}
    owner_count = raw.get("ownerCount") or {}
    nickname = (
        raw.get("nickname")
        or raw.get("name")
        or raw.get("screen_name")
        or raw.get("user_nickname")
        or raw.get("user_name")
        or profile.get("user_name")
        or ""
    )
    existing_hash = raw.get("creator_hash")
    creator_hash = (
        str(existing_hash).strip()
        if existing_hash not in (None, "")
        else anonymize_user_id(raw_id)
    )
    if not creator_hash:
        raise ValueError("无法构造非空 creator_hash：缺少稳定创作者标识")

    def first_not_none(*values):
        return next((value for value in values if value is not None), None)

    def image_url(*values):
        value = first_not_none(*values)
        if isinstance(value, dict):
            urls = value.get("url_list") or value.get("urlList") or []
            value = first_not_none(value.get("url"), urls[0] if urls else None)
        return str(value or "").strip()

    return {
        "platform": platform,
        "creator_hash": creator_hash,
        "nickname": mask_nickname(nickname),
        "display_name": str(nickname).strip()[:100],
        "profile_url": build_public_profile_url(platform, raw_id),
        "avatar_url": image_url(
            raw.get("avatar_url"), raw.get("avatar"), raw.get("avatar_larger"),
            raw.get("avatar_medium"), raw.get("avatar_thumb"), profile.get("avatar"),
        ),
        "bio": str(
            first_not_none(
                raw.get("bio"),
                raw.get("desc"),
                raw.get("description"),
                raw.get("signature"),
                raw.get("user_text"),
                profile.get("user_text"),
                profile.get("description"),
                "",
            )
        ).strip(),
        "following_count": first_not_none(
            raw.get("following_count"), raw.get("following"), raw.get("follow_count"),
            raw.get("follows"), owner_count.get("follow"),
        ),
        "fans_count": first_not_none(
            raw.get("fans_count"),
            raw.get("follower_count"),
            raw.get("follower"),
            raw.get("followers_count"),
            raw.get("fans"),
            owner_count.get("fan"),
        ),
        "max_fans_count": first_not_none(
            raw.get("max_fans_count"),
            raw.get("max_follower_count"),
        ),
        "works_count": first_not_none(
            raw.get("works_count"), raw.get("aweme_count"), raw.get("photo_count"),
            owner_count.get("photo"),
        ),
        "liked_count": raw.get("liked_count", raw.get("total_favorited")),
        "interaction_count": raw.get("interaction_count"),
        # 旧调用方继续消费上面的稳定字段；需要平台扩展字段的新调用方
        # 可读取 raw_data。Cookie 在进入结果前会被递归移除。
        "raw_data": _without_cookies(raw if raw_data is None else raw_data),
    }
