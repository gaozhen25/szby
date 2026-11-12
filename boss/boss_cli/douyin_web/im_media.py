"""Resolve Douyin IM image/voice bytes for the local media proxy."""

from __future__ import annotations

import base64
import logging
from collections import OrderedDict
from typing import Any

logger = logging.getLogger(__name__)

_INLINE_CACHE: OrderedDict[str, str] = OrderedDict()
_URL_CACHE: OrderedDict[str, list[str]] = OrderedDict()
_RESOLVED_CACHE: OrderedDict[str, tuple[bytes, str]] = OrderedDict()
_CACHE_LIMIT = 400


def _trim(cache: OrderedDict) -> None:
    while len(cache) > _CACHE_LIMIT:
        cache.popitem(last=False)


def remember_image_urls(mid: str, urls: list[str]) -> None:
    mid = str(mid or "").strip()
    clean = [str(u).strip() for u in urls if str(u).strip().startswith("http")]
    if not mid or not clean:
        return
    _URL_CACHE[mid] = clean
    _URL_CACHE.move_to_end(mid)
    _trim(_URL_CACHE)


def pick_im_image_url(urls: list[str]) -> str:
    """Prefer large/medium CDN variants; the bare ``:.image`` entry often won't decrypt."""
    clean = [str(u).strip() for u in urls if str(u).strip().startswith("http")]
    if not clean:
        return ""

    def rank(url: str) -> tuple[int, int]:
        lower = url.lower()
        if "large" in lower:
            bucket = 0
        elif "medium" in lower:
            bucket = 1
        elif "origin" in lower:
            bucket = 2
        elif "thumb" in lower:
            bucket = 3
        elif "~tplv-x-get:.image" in lower or ":.image" in lower:
            bucket = 9
        else:
            bucket = 5
        return bucket, len(url)

    return sorted(clean, key=rank)[0]


def image_urls_for_mid(mid: str) -> list[str]:
    mid = str(mid or "").strip()
    if not mid:
        return []
    urls = _URL_CACHE.get(mid) or []
    if not urls:
        return []
    out: list[str] = []
    best = pick_im_image_url(urls)
    if best:
        out.append(best)
    for url in urls:
        if url not in out:
            out.append(url)
    return out


def remember_inline_pic(mid: str, inline_b64: str) -> None:
    mid = str(mid or "").strip()
    text = str(inline_b64 or "").strip()
    if not mid or not text:
        return
    _INLINE_CACHE[mid] = text
    _INLINE_CACHE.move_to_end(mid)
    _trim(_INLINE_CACHE)


def cached_bytes(mid: str) -> tuple[bytes, str] | None:
    mid = str(mid or "").strip()
    if not mid:
        return None
    hit = _RESOLVED_CACHE.get(mid)
    if hit:
        _RESOLVED_CACHE.move_to_end(mid)
    return hit


def store_bytes(mid: str, data: bytes, content_type: str) -> tuple[bytes, str]:
    mid = str(mid or "").strip()
    if mid:
        _RESOLVED_CACHE[mid] = (data, content_type)
        _RESOLVED_CACHE.move_to_end(mid)
        _trim(_RESOLVED_CACHE)
    return data, content_type


def _heif_brand(data: bytes) -> bool:
    if len(data) < 12 or data[4:8] != b"ftyp":
        return False
    brand = data[8:12]
    return brand in {b"heic", b"heix", b"hevc", b"heim", b"heis", b"mif1", b"msf1", b"heif"} or brand.startswith(b"hei")


def _is_image(data: bytes) -> bool:
    return (
        data.startswith(b"\xff\xd8\xff")
        or data.startswith(b"\x89PNG")
        or data.startswith(b"GIF8")
        or (data.startswith(b"RIFF") and b"WEBP" in data[8:16])
        or _heif_brand(data)
    )


def sniff_content_type(data: bytes, url: str = "") -> str:
    return _sniff_content_type(data, url)


def _sniff_content_type(data: bytes, url: str = "") -> str:
    if _heif_brand(data):
        return "image/heic"
    if data[4:8] == b"ftyp" or str(url).lower().endswith((".m4a", ".mpeg", ".mp4")):
        return "audio/mp4"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG"):
        return "image/png"
    if data.startswith(b"GIF8"):
        return "image/gif"
    if data.startswith(b"RIFF") and b"WEBP" in data[8:16]:
        return "image/webp"
    return "application/octet-stream"


def try_decrypt_image(data: bytes, skey: str) -> bytes | None:
    """ImageX AES-256-GCM: IV(12) || ciphertext || tag(16), skey = 64 hex chars."""
    if not data or _is_image(data):
        return data if _is_image(data) else None
    skey = str(skey or "").strip()
    if not skey or len(skey) < 64:
        return None
    if not all(c in "0123456789abcdefABCDEF" for c in skey):
        return None
    try:
        from Crypto.Cipher import AES
    except ImportError:
        logger.debug("pycryptodome missing; skip IM image decrypt")
        return None
    if len(data) < 12 + 16:
        return None
    try:
        key = bytes.fromhex(skey)
    except ValueError:
        return None
    if len(key) != 32:
        key = key[:32] if len(key) > 32 else None
    if not key or len(key) != 32:
        return None
    iv, body = data[:12], data[12:]
    ct, tag = body[:-16], body[-16:]
    try:
        plain = AES.new(key, AES.MODE_GCM, nonce=iv).decrypt_and_verify(ct, tag)
    except Exception:
        return None
    return plain if _is_image(plain) else None


def _decode_inline(inline_b64: str) -> bytes:
    text = str(inline_b64 or "").strip()
    if not text:
        return b""
    try:
        return base64.b64decode(text)
    except Exception:
        return b""


def image_meta_from_content(raw_obj: dict[str, Any], *, urls: list[str], mid: str) -> dict[str, Any] | None:
    if not isinstance(raw_obj, dict):
        return None
    ru = raw_obj.get("resource_url") if isinstance(raw_obj.get("resource_url"), dict) else {}
    skey = str(ru.get("skey") or "")
    oid = str(ru.get("oid") or "")
    inline = str(raw_obj.get("inline_pic") or "")
    url = urls[0] if urls else ""
    if inline:
        remember_inline_pic(mid, inline)
    if not url and oid:
        url = f"https://p3.douyinpic.com/obj/{oid}"
    if not url and not inline and not oid:
        return None
    return {
        "preview": url or "",
        "origin": url or "",
        "skey": skey,
        "oid": oid,
        "mid": mid,
    }


def resolve_media_bytes(
    raw: bytes,
    *,
    url: str = "",
    skey: str = "",
    oid: str = "",
    inline_b64: str = "",
    mid: str = "",
) -> tuple[bytes, str] | None:
    if not raw and not inline_b64 and not oid and not mid:
        return None
    mid = str(mid or "").strip()
    if mid:
        cached = cached_bytes(mid)
        if cached:
            return cached

    candidates: list[bytes] = []
    if raw:
        candidates.append(raw)
        plain = try_decrypt_image(raw, skey)
        if plain and plain not in candidates:
            candidates.append(plain)

    inline = inline_b64 or (_INLINE_CACHE.get(mid) if mid else "")
    inline_data = _decode_inline(inline)
    if inline_data:
        candidates.append(inline_data)

    for data in candidates:
        if _is_image(data):
            ctype = _sniff_content_type(data, url)
            return store_bytes(mid, data, ctype) if mid else (data, ctype)

    if raw:
        ctype = _sniff_content_type(raw, url)
        if ctype.startswith("audio/"):
            return store_bytes(mid, raw, ctype) if mid else (raw, ctype)

    if oid and not raw:
        return None

    if raw and _is_image(raw):
        ctype = _sniff_content_type(raw, url)
        return store_bytes(mid, raw, ctype) if mid else (raw, ctype)

    return None
