import re
from typing import Any
import requests

from app.core.config import settings
from app.services.extract_service.extract_service import ExtractService
URL_PATTERN = re.compile(r"https?://[^\s，,。；;）)】]+")


class ExtractReferenceError(ValueError):
    pass


def extract_first_url(text: str) -> str:
    match = URL_PATTERN.search(str(text or ""))
    if not match:
        raise ExtractReferenceError("share text does not include a supported url")
    return match.group(0).strip()


class ExtractReferenceService:
    def __init__(
        self,
        *,
        extractor: Any | None = None,
        storage: Any = None,
        media_session: Any = None,
        timeout: int = 10,
    ) -> None:
        self.extractor = extractor or ExtractService(timeout=timeout)
        self.storage = storage
        self.media_session = media_session or requests.Session()
        self.timeout = timeout

    def extract_from_text(self, share_text: str) -> dict[str, Any]:
        url = extract_first_url(share_text)
        extracted = self.extractor.extract(url)
        platform = str(extracted.get("platform") or "unknown")
        images = _external_media_list(extracted.get("images") or [], kind="image")
        videos = _external_media_list(extracted.get("videos") or [], kind="video")
        cover = images[0]["url"] if images else None

        return {
            "url": extracted.get("url") or url,
            "resolvedUrl": extracted.get("resolved_url") or extracted.get("resolvedUrl") or url,
            "platform": platform,
            "type": extracted.get("type") or "unknown",
            "title": extracted.get("title") or "",
            "description": extracted.get("description") or "",
            "images": images,
            "videos": videos,
            "cover": cover,
            "raw": extracted.get("raw") or {},
        }


def _external_media_list(source_urls: list[str], *, kind: str) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    seen: set[str] = set()
    for source_url in source_urls:
        if len(items) >= settings.max_extract_media_items:
            break
        clean_url = str(source_url or "").strip()
        if not clean_url or clean_url in seen:
            continue
        seen.add(clean_url)
        items.append(
            {
                "sourceUrl": clean_url,
                "url": clean_url,
                "contentType": "",
                "kind": kind,
                "storageStatus": "external",
            }
        )
    return items
