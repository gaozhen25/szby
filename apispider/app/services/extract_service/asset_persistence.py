from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
from typing import Any
from urllib.parse import urlparse

import requests

from app.core.config import settings
from app.services.extract_service.extract_service import ExtractService
from app.services.extract_service.platforms.base import DEFAULT_HEADERS
from app.services.object_storage import default_object_storage
from app.services.resource_limits import ensure_size_within_limit

IMAGE_CONTENT_TYPES = {"image/jpeg", "image/png", "image/webp"}
VIDEO_CONTENT_TYPES = {"video/mp4", "application/vnd.apple.mpegurl"}


class AssetPersistenceError(RuntimeError):
    pass


@dataclass(frozen=True)
class ExtractHistorySnapshot:
    id: str
    account_id: str
    source_url: str
    platform: str
    images: list[dict[str, str]]
    videos: list[dict[str, str]]
    existing_url_map: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class AssetPersistenceResult:
    status: str
    assets: list[dict[str, str]]
    url_map: dict[str, str]
    retry_count: int
    error: str = ""


@dataclass(frozen=True)
class _MediaCandidate:
    original_url: str
    download_url: str
    kind: str


class _RoundFailure(AssetPersistenceError):
    def __init__(self, cause: Exception, uploaded_keys: list[str]) -> None:
        super().__init__(str(cause) or cause.__class__.__name__)
        self.cause = cause
        self.uploaded_keys = uploaded_keys


class ExtractAssetPersistenceService:
    def __init__(
        self,
        *,
        storage: Any = default_object_storage,
        media_session: requests.Session | None = None,
        extractor: Any | None = None,
        timeout: int = 10,
    ) -> None:
        self.storage = storage
        self.media_session = media_session or requests.Session()
        self.extractor = extractor or ExtractService(timeout=timeout)
        self.timeout = timeout

    def persist(self, history: ExtractHistorySnapshot) -> AssetPersistenceResult:
        original_candidates = _original_candidates(history)
        original_urls = [candidate.original_url for candidate in original_candidates]
        if original_urls and all(history.existing_url_map.get(url) for url in original_urls):
            url_map = {url: history.existing_url_map[url] for url in original_urls}
            return AssetPersistenceResult(
                status="completed",
                assets=_assets_from_map(original_candidates, url_map, persisted=True),
                url_map=url_map,
                retry_count=0,
            )

        first_error: Exception
        try:
            return self._persist_round(history, original_candidates, retry_count=0)
        except _RoundFailure as exc:
            self._cleanup(exc.uploaded_keys)
            first_error = exc.cause

        try:
            refreshed = self.extractor.extract(history.source_url)
            refreshed_candidates = _refreshed_candidates(history, refreshed)
            return self._persist_round(history, refreshed_candidates, retry_count=1)
        except _RoundFailure as exc:
            self._cleanup(exc.uploaded_keys)
            second_error: Exception = exc.cause
        except Exception as exc:  # platform extraction failures are a normal fallback path
            second_error = exc

        fallback_map = {url: url for url in original_urls}
        return AssetPersistenceResult(
            status="fallback",
            assets=_assets_from_map(original_candidates, fallback_map, persisted=False),
            url_map=fallback_map,
            retry_count=1,
            error=_combined_error(first_error, second_error),
        )

    def _persist_round(
        self,
        history: ExtractHistorySnapshot,
        candidates: list[_MediaCandidate],
        *,
        retry_count: int,
    ) -> AssetPersistenceResult:
        uploaded_keys: list[str] = []
        url_map: dict[str, str] = {}
        assets: list[dict[str, str]] = []
        try:
            for candidate in candidates:
                data, content_type = self._download(candidate.download_url, candidate.kind)
                key = _storage_key(history, candidate, content_type)
                persisted_url = self.storage.put_bytes(key, data, content_type)
                uploaded_keys.append(key)
                url_map[candidate.original_url] = persisted_url
                url_map[candidate.download_url] = persisted_url
                assets.append(
                    {
                        "sourceUrl": candidate.original_url,
                        "url": persisted_url,
                        "contentType": content_type,
                        "kind": candidate.kind,
                        "storageStatus": "persisted",
                    }
                )
        except Exception as exc:
            raise _RoundFailure(exc, uploaded_keys) from exc

        return AssetPersistenceResult(
            status="completed",
            assets=assets,
            url_map=url_map,
            retry_count=retry_count,
        )

    def _download(self, url: str, kind: str) -> tuple[bytes, str]:
        _ensure_http_url(url)
        response = self.media_session.get(
            url,
            timeout=self.timeout,
            headers=DEFAULT_HEADERS,
            stream=True,
        )
        response.raise_for_status()
        content_type = _clean_content_type(response.headers.get("Content-Type") or "")
        allowed_types = IMAGE_CONTENT_TYPES if kind == "image" else VIDEO_CONTENT_TYPES
        if content_type not in allowed_types:
            raise AssetPersistenceError(f"unsupported {kind} content type: {content_type}")
        raw_length = response.headers.get("Content-Length")
        if raw_length and raw_length.isdigit():
            ensure_size_within_limit(
                int(raw_length),
                limit=settings.max_extract_media_bytes,
                label=f"{kind} media download",
            )
        return (
            _read_response_limited(
                response,
                limit=settings.max_extract_media_bytes,
                label=f"{kind} media download",
            ),
            content_type,
        )

    def _cleanup(self, keys: list[str]) -> None:
        for key in reversed(keys):
            try:
                self.storage.delete_object(key)
            except Exception:
                continue


def _original_candidates(history: ExtractHistorySnapshot) -> list[_MediaCandidate]:
    return [
        _MediaCandidate(original_url=url, download_url=url, kind=kind)
        for kind, items in (("image", history.images), ("video", history.videos))
        for item in items
        if (url := _media_url(item))
    ]


def _refreshed_candidates(history: ExtractHistorySnapshot, extracted: dict[str, Any]) -> list[_MediaCandidate]:
    candidates: list[_MediaCandidate] = []
    for kind, original_items, refreshed_urls in (
        ("image", history.images, extracted.get("images") or []),
        ("video", history.videos, extracted.get("videos") or []),
    ):
        clean_refreshed = [str(url or "").strip() for url in refreshed_urls if str(url or "").strip()]
        if len(clean_refreshed) < len(original_items):
            raise AssetPersistenceError(f"refreshed {kind} media count is smaller than original")
        for index, download_url in enumerate(clean_refreshed[: settings.max_extract_media_items]):
            original_url = _media_url(original_items[index]) if index < len(original_items) else download_url
            candidates.append(
                _MediaCandidate(
                    original_url=original_url or download_url,
                    download_url=download_url,
                    kind=kind,
                )
            )
    return candidates


def _assets_from_map(
    candidates: list[_MediaCandidate],
    url_map: dict[str, str],
    *,
    persisted: bool,
) -> list[dict[str, str]]:
    return [
        {
            "sourceUrl": candidate.original_url,
            "url": url_map.get(candidate.original_url, candidate.original_url),
            "contentType": "",
            "kind": candidate.kind,
            "storageStatus": "persisted" if persisted else "external",
        }
        for candidate in candidates
    ]


def _media_url(item: dict[str, Any]) -> str:
    return str(item.get("sourceUrl") or item.get("url") or "").strip()


def _ensure_http_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise AssetPersistenceError("media URL must use HTTP or HTTPS")


def _clean_content_type(value: str) -> str:
    return value.split(";", 1)[0].strip().lower()


def _read_response_limited(response: Any, *, limit: int, label: str) -> bytes:
    chunks: list[bytes] = []
    total = 0
    for chunk in response.iter_content(chunk_size=1024 * 1024):
        if not chunk:
            continue
        total += len(chunk)
        ensure_size_within_limit(total, limit=limit, label=label)
        chunks.append(chunk)
    return b"".join(chunks)


def _storage_key(
    history: ExtractHistorySnapshot,
    candidate: _MediaCandidate,
    content_type: str,
) -> str:
    digest = sha256(candidate.original_url.encode("utf-8")).hexdigest()
    extension = {
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
        "video/mp4": ".mp4",
        "application/vnd.apple.mpegurl": ".m3u8",
    }[content_type]
    return f"extract/{history.account_id}/{history.id}/{candidate.kind}/{digest}{extension}"


def _combined_error(first_error: Exception, second_error: Exception) -> str:
    first = str(first_error).strip() or first_error.__class__.__name__
    second = str(second_error).strip() or second_error.__class__.__name__
    return f"first round failed: {first}; second round failed: {second}"[:1000]
