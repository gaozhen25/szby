"""Persist image-generation responses to managed object storage."""

from __future__ import annotations

import base64
import binascii
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4

import httpx

from app.core.config import settings
from app.db.models import GenerationAssetRecord
from app.services.resource_limits import ensure_size_within_limit

from .photo_exif import create_photo_parameters, embed_photo_exif
from .steps import IMAGE_EXTENSION_BY_CONTENT_TYPE

GENERATED_IMAGE_DOWNLOAD_TIMEOUT = httpx.Timeout(180, connect=15)


async def persist_generated_image_result(
    record: Any,
    item: dict[str, Any],
    index: int,
    storage: Any,
) -> tuple[GenerationAssetRecord, dict[str, str]]:
    """Normalize URL/Base64 provider responses and always upload managed bytes."""

    asset_id = f"ga_{uuid4().hex}"
    revised_prompt = _revised_prompt(item)
    source_url = str(item.get("url") or "").strip()
    if source_url:
        data, content_type = await _download_generated_image(source_url)
        source = "url_persisted"
    else:
        raw_b64 = str(item.get("b64_json") or "")
        if not raw_b64:
            raise ValueError("image generation result did not include url or b64_json")
        data, content_type = _decode_generated_image(raw_b64)
        source = "b64_json"

    captured_at = datetime.now().astimezone()
    prompt = " ".join(
        part
        for part in (
            str(getattr(record, "prompt", "") or ""),
            revised_prompt,
        )
        if part
    )
    photo_parameters = create_photo_parameters(
        stable_key=f"{record.id}:{index}",
        prompt=prompt,
        captured_at=captured_at,
    )
    data = embed_photo_exif(data, content_type, photo_parameters)
    ensure_size_within_limit(
        len(data),
        limit=settings.max_generated_image_bytes,
        label="generated image with EXIF",
    )

    extension = IMAGE_EXTENSION_BY_CONTENT_TYPE[content_type]
    key = _storage_key(f"generation/{record.account_id}/{record.id}/results/{asset_id}{extension}")
    persisted_url = storage.put_bytes(key, data, content_type)
    asset = GenerationAssetRecord(
        id=asset_id,
        job_id=record.id,
        account_id=record.account_id,
        asset_type="result",
        file_name=f"{asset_id}{extension}",
        mime_type=content_type,
        storage_key=key,
        url=persisted_url,
        status="completed",
        analysis="",
        error="",
        meta={
            "source": source,
            "sourceHost": urlparse(source_url).netloc.lower() if source_url else "",
            "index": index,
            "revisedPrompt": revised_prompt,
            "photoParameters": photo_parameters.to_meta(),
        },
        created_at=datetime.now(UTC),
    )
    return asset, {"url": persisted_url, "revisedPrompt": revised_prompt}


async def _download_generated_image(url: str) -> tuple[bytes, str]:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("image generation returned an invalid image URL")

    async with httpx.AsyncClient(
        timeout=GENERATED_IMAGE_DOWNLOAD_TIMEOUT,
        follow_redirects=True,
    ) as client:
        async with client.stream("GET", url) as response:
            response.raise_for_status()
            content_type = _content_type(response.headers.get("Content-Type"))
            if content_type not in IMAGE_EXTENSION_BY_CONTENT_TYPE:
                raise ValueError(
                    f"image generation returned unsupported content type: {content_type or 'unknown'}"
                )
            raw_length = response.headers.get("Content-Length")
            if raw_length and raw_length.isdigit():
                ensure_size_within_limit(
                    int(raw_length),
                    limit=settings.max_generated_image_bytes,
                    label="generated image",
                )
            chunks: list[bytes] = []
            total = 0
            async for chunk in response.aiter_bytes():
                if not chunk:
                    continue
                total += len(chunk)
                ensure_size_within_limit(
                    total,
                    limit=settings.max_generated_image_bytes,
                    label="generated image",
                )
                chunks.append(chunk)

    data = b"".join(chunks)
    if not data:
        raise ValueError("image generation returned an empty image")
    return data, content_type


async def download_generated_image(url: str) -> tuple[bytes, str]:
    """Download and validate a generated image for an authenticated API response."""

    return await _download_generated_image(url)


def _decode_generated_image(raw_b64: str) -> tuple[bytes, str]:
    encoded = raw_b64.strip()
    content_type = "image/png"
    if encoded.startswith("data:") and "," in encoded:
        header, encoded = encoded.split(",", 1)
        parsed_content_type = header[5:].split(";", 1)[0].strip().lower()
        if parsed_content_type:
            content_type = parsed_content_type
    if content_type not in IMAGE_EXTENSION_BY_CONTENT_TYPE:
        raise ValueError(f"image generation returned unsupported content type: {content_type}")
    try:
        data = base64.b64decode(encoded, validate=True)
    except binascii.Error as exc:
        raise ValueError("image generation returned invalid b64_json") from exc
    if not data:
        raise ValueError("image generation returned empty b64_json")
    ensure_size_within_limit(
        len(data),
        limit=settings.max_generated_image_bytes,
        label="generated image",
    )
    return data, content_type


def _content_type(value: Any) -> str:
    return str(value or "").split(";", 1)[0].strip().lower()


def _storage_key(key: str) -> str:
    upload_dir = settings.object_storage_upload_dir.strip("/")
    return "/".join(part for part in (upload_dir, key.lstrip("/")) if part)


def _revised_prompt(item: dict[str, Any]) -> str:
    return str(item.get("revisedPrompt") or item.get("revised_prompt") or "").strip()
