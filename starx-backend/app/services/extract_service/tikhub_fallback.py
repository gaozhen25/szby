from __future__ import annotations

import asyncio
from collections.abc import Awaitable
from concurrent.futures import ThreadPoolExecutor
from typing import Any
from urllib.parse import urlsplit

from app.services.extract_service.platforms.base import (
    ExtractedContent,
    collect_urls,
    clean_text,
    unique_urls,
)
from app.services.tikhub_service import (
    TikHubContent,
    TikHubContentDetailRequest,
    TikHubPlatform,
    TikHubProvider,
    TikHubRuntime,
)


_PLATFORM_MAP = {
    "rednote": TikHubPlatform.XIAOHONGSHU,
}


class TikHubExtractFallback:
    def __init__(
        self,
        provider: TikHubProvider | None = None,
        runtime_factory=TikHubRuntime,
    ) -> None:
        self.provider = provider
        self.runtime_factory = runtime_factory

    def supports(self, platform: str) -> bool:
        return platform in _PLATFORM_MAP

    def extract(self, *, platform: str, url: str) -> ExtractedContent:
        tikhub_platform = _PLATFORM_MAP[platform]
        request = TikHubContentDetailRequest(
            platform=tikhub_platform,
            workUrl=url,
        )
        if self.provider is not None:
            content = _run_async(self.provider.get_content(request))
        else:
            content = _run_async(
                self._get_content_with_owned_runtime(request)
            )
        if not content.contentId and not content.title and not content.coverUrl:
            raise ValueError("TikHub did not return parseable content")
        return _content_to_extracted(content, source_url=url)

    async def _get_content_with_owned_runtime(
        self,
        request: TikHubContentDetailRequest,
    ) -> TikHubContent:
        runtime = self.runtime_factory()
        try:
            return await TikHubProvider(sdk=runtime.client).get_content(request)
        finally:
            await runtime.aclose()


def _content_to_extracted(content: TikHubContent, *, source_url: str) -> ExtractedContent:
    raw = dict(content.raw or {})
    images = _image_urls(content, raw)
    videos = _video_urls(raw)
    content_type = _content_type(content, images, videos)
    return ExtractedContent(
        platform=_extract_platform(content.platform),
        url=source_url,
        resolved_url=content.contentUrl or source_url,
        content_type=content_type,
        title=content.title or None,
        description=content.description or None,
        images=images,
        videos=videos,
        cover=(images[0] if images else content.coverUrl),
        raw={
            "source_provider": "tikhub",
            "content_id": content.contentId,
            "author_id": content.authorId,
            "author_name": content.authorName,
            "author_url": content.authorUrl,
            "like_count": content.likeCount,
            "comment_count": content.commentCount,
            "share_count": content.shareCount,
            "collect_count": content.collectCount,
            "published_at": content.publishedAt,
            "tikhub": raw,
        },
    )


def _image_urls(content: TikHubContent, raw: dict[str, Any]) -> list[str]:
    if content.platform == TikHubPlatform.XIAOHONGSHU:
        images = _xiaohongshu_note_images(raw)
        if images:
            return images

    urls = [content.coverUrl] if content.coverUrl else []
    urls.extend(collect_urls(raw, r"\.(?:jpe?g|png|webp)(?:\?|$)|xhscdn|sns-img"))
    return _unique_media_urls(urls)


def _xiaohongshu_note_images(raw: dict[str, Any]) -> list[str]:
    """Extract only note body images; ignore avatars, share thumbnails and topic icons.

    TikHub Xiaohongshu App V2 detail payloads expose body images under
    ``images_list`` in display order. Each item describes one note slide:
    ``url_size_large`` is the detail image, ``url`` and ``url_multi_level`` are
    preview variants, and ``url_trans`` is a translated render rather than the
    original note image.
    """

    image_items = _first_list(raw, "images_list", "image_list", "images")
    urls = []
    for item in _sorted_image_items(image_items):
        if isinstance(item, str):
            urls.append(item)
            continue
        if not isinstance(item, dict):
            continue
        urls.append(
            clean_text(
                item.get("url_size_large")
                or item.get("url_default")
                or item.get("urlDefault")
                or item.get("url")
                or _multi_level_url(item.get("url_multi_level"))
            )
            or ""
        )
    return _unique_media_urls(urls)


def _first_list(value: Any, *keys: str) -> list[Any]:
    if not isinstance(value, dict):
        return []
    for key in keys:
        candidate = value.get(key)
        if isinstance(candidate, list) and candidate:
            return candidate
    return []


def _sorted_image_items(items: list[Any]) -> list[Any]:
    def sort_key(item: Any) -> int:
        if not isinstance(item, dict):
            return 0
        try:
            return int(item.get("index"))
        except (TypeError, ValueError):
            return 0

    return sorted(items, key=sort_key)


def _multi_level_url(value: Any) -> str:
    if not isinstance(value, dict):
        return ""
    for key in ("origin", "large", "high", "medium", "low"):
        if url := clean_text(value.get(key)):
            return url
    return ""


def _video_urls(raw: dict[str, Any]) -> list[str]:
    return unique_urls(
        collect_urls(raw, r"\.(?:mp4|m3u8)(?:\?|$)|sns-video|video")
    )[:1]


def _content_type(
    content: TikHubContent,
    images: list[str],
    videos: list[str],
) -> str:
    explicit = str(content.contentType or "").strip().lower()
    if videos and images:
        return "mixed"
    if videos:
        return "video"
    if images:
        return "image"
    return explicit or "unknown"


def _extract_platform(platform: TikHubPlatform) -> str:
    if platform == TikHubPlatform.XIAOHONGSHU:
        return "rednote"
    return platform.value


def _https_url(url: str) -> str:
    text = str(url or "").strip()
    return f"https://{text.removeprefix('http://')}" if text.startswith("http://") else text


def _unique_media_urls(urls: list[str]) -> list[str]:
    result = []
    seen = set()
    for url in unique_urls([_https_url(url) for url in urls]):
        key = _media_identity(url)
        if key in seen:
            continue
        seen.add(key)
        result.append(url)
    return result


def _media_identity(url: str) -> str:
    parsed = urlsplit(str(url or ""))
    return f"{parsed.netloc.lower()}{parsed.path}"


def _run_async(awaitable: Awaitable[TikHubContent]) -> TikHubContent:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(awaitable)

    with ThreadPoolExecutor(max_workers=1) as executor:
        return executor.submit(asyncio.run, awaitable).result()
