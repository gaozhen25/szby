from __future__ import annotations

from hashlib import sha256
from typing import Any
from urllib.parse import urlparse

import requests

from app.core.config import settings
from app.services.extract_service.platforms.base import DEFAULT_HEADERS
from app.services.object_storage import default_object_storage
from app.services.resource_limits import ensure_size_within_limit

VIDEO_CONTENT_TYPES = {"video/mp4", "application/octet-stream"}


class VideoSourcePersistenceError(RuntimeError):
    pass


class VideoSourcePersistenceService:
    """将外部视频转存到自有对象存储，向视频模型提供稳定 URL。"""

    def __init__(
        self,
        *,
        storage: Any = default_object_storage,
        media_session: requests.Session | None = None,
        connect_timeout: int = 15,
        read_timeout: int = 180,
    ) -> None:
        self.storage = storage
        self.media_session = media_session or requests.Session()
        self.timeout = (connect_timeout, read_timeout)

    def persist(
        self,
        video_url: str,
        *,
        source_url: str = "",
        owner_id: str = "",
    ) -> str:
        source = str(video_url or "").strip()
        if not source:
            raise VideoSourcePersistenceError("视频地址为空")
        if is_managed_video_url(source):
            return source

        parsed = urlparse(source)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise VideoSourcePersistenceError("视频地址必须使用 HTTP 或 HTTPS")

        try:
            response = self.media_session.get(
                source,
                timeout=self.timeout,
                headers=DEFAULT_HEADERS,
                stream=True,
            )
            response.raise_for_status()
            content_type = _content_type(response.headers.get("Content-Type"))
            if content_type not in VIDEO_CONTENT_TYPES:
                raise VideoSourcePersistenceError(f"不支持的视频类型：{content_type or 'unknown'}")
            raw_length = response.headers.get("Content-Length")
            if raw_length and raw_length.isdigit():
                ensure_size_within_limit(
                    int(raw_length),
                    limit=settings.max_extract_media_bytes,
                    label="video source",
                )
            data = _read_limited(response)
            if not data:
                raise VideoSourcePersistenceError("视频内容为空")
            key = _storage_key(source_url or source, owner_id)
            return self.storage.put_bytes(key, data, "video/mp4")
        except VideoSourcePersistenceError:
            raise
        except Exception as exc:
            message = str(exc).strip() or exc.__class__.__name__
            raise VideoSourcePersistenceError(f"视频下载或上传失败：{message}") from exc


def is_managed_video_url(value: str) -> bool:
    candidate = urlparse(str(value or "").strip())
    public_base = urlparse(settings.object_storage_public_base_url)
    return bool(
        candidate.scheme in {"http", "https"}
        and candidate.netloc
        and public_base.netloc
        and candidate.netloc.lower() == public_base.netloc.lower()
    )


def _read_limited(response: Any) -> bytes:
    chunks: list[bytes] = []
    total = 0
    for chunk in response.iter_content(chunk_size=1024 * 1024):
        if not chunk:
            continue
        total += len(chunk)
        ensure_size_within_limit(
            total,
            limit=settings.max_extract_media_bytes,
            label="video source",
        )
        chunks.append(chunk)
    return b"".join(chunks)


def _storage_key(identity: str, owner_id: str) -> str:
    digest = sha256(identity.encode("utf-8")).hexdigest()
    safe_owner = "".join(char for char in owner_id if char.isalnum() or char in {"-", "_"}) or "shared"
    prefix = settings.object_storage_upload_dir.strip("/")
    parts = [part for part in (prefix, "extract", "video-analysis", safe_owner, f"{digest}.mp4") if part]
    return "/".join(parts)


def _content_type(value: Any) -> str:
    return str(value or "").split(";", 1)[0].strip().lower()
