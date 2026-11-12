from __future__ import annotations

import inspect
from typing import Any


class ResourceLimitError(ValueError):
    pass


def _limit_message(label: str, limit: int) -> str:
    return f"{label} exceeds {limit} bytes"


def ensure_size_within_limit(size: int | None, *, limit: int, label: str) -> None:
    if size is not None and size > limit:
        raise ResourceLimitError(_limit_message(label, limit))


async def read_upload_file_limited_async(file: Any, *, limit: int, label: str = "image upload") -> bytes:
    reader = getattr(file, "read", None)
    if not callable(reader):
        raise ResourceLimitError(f"{label} bytes are required")

    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = reader(1024 * 1024)
        if inspect.isawaitable(chunk):
            chunk = await chunk
        if not chunk:
            break
        if not isinstance(chunk, bytes):
            raise ResourceLimitError(f"{label} bytes are required")
        total += len(chunk)
        ensure_size_within_limit(total, limit=limit, label=label)
        chunks.append(chunk)
    return b"".join(chunks)


def read_upload_file_limited(file: Any, *, limit: int, label: str = "image upload") -> bytes:
    data = getattr(file, "data", None)
    if isinstance(data, bytes):
        ensure_size_within_limit(len(data), limit=limit, label=label)
        return data

    reader = getattr(file, "read", None)
    if not callable(reader):
        raise ResourceLimitError(f"{label} bytes are required")

    chunks: list[bytes] = []
    total = 0
    while True:
        try:
            chunk = reader(1024 * 1024)
        except TypeError:
            chunk = reader()
        if not chunk:
            break
        if not isinstance(chunk, bytes):
            raise ResourceLimitError(f"{label} bytes are required")
        total += len(chunk)
        ensure_size_within_limit(total, limit=limit, label=label)
        chunks.append(chunk)
        if len(chunk) < 1024 * 1024:
            break
    return b"".join(chunks)
