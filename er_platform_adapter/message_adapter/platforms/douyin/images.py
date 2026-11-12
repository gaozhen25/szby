"""把抖音私信加密图解成下游后台能直接访问的地址。

CDN 上 `~tplv-x-get` 图片是 ImageX AES-256-GCM（IV 12 字节 + 密文 + tag 16 字节），
密钥是消息里 `resource_url.skey` 的前 32 字节。解密后上传到 OSS，消息里写公网 URL。
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import os
import re
from datetime import datetime
from email.utils import formatdate
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo

import requests
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

logger = logging.getLogger(__name__)

_BASE_URL = "http://127.0.0.1:8765"
_MEDIA_ROOT = Path("adapter_data/douyin_media")
_NAME = re.compile(r"^[0-9a-f]{32}\.(jpg|png|webp|gif)$")
_TYPES = {
    "jpg": "image/jpeg",
    "png": "image/png",
    "webp": "image/webp",
    "gif": "image/gif",
}


def configure_media_base(base: str) -> None:
    global _BASE_URL
    text = str(base or "").strip().rstrip("/")
    if text:
        _BASE_URL = text


def configure_media_root(root: Path | str) -> None:
    global _MEDIA_ROOT
    _MEDIA_ROOT = Path(root).expanduser().resolve() / "douyin_media"


def media_dir() -> Path:
    return _MEDIA_ROOT


def openable_image_url(
    raw: dict[str, Any],
    cdn_url: str,
    *,
    fetch: Callable[[str], bytes] | None = None,
    upload: Callable[[bytes], str] | None = None,
) -> tuple[str, int | None]:
    """加密图解密后上传 OSS，返回下游能访问的 https 地址。普通图片原样返回。"""
    encrypted = "tplv-x-get" in cdn_url or bool(_skey(raw))
    if not encrypted:
        return cdn_url, None
    plain = _plaintext(raw, cdn_url, fetch or _download)
    if plain is None:
        plain = _inline_pic(raw)
    if plain is None:
        return cdn_url, None
    public = (upload or upload_image)(plain)
    if not public.startswith("https://"):
        logger.warning("douyin image was decrypted but has no public OSS url")
        return cdn_url, None
    return public, len(plain)


def upload_image(data: bytes) -> str:
    """Upload one decrypted image and return its public https URL."""
    settings = _oss_settings()
    if settings is None:
        return ""
    ext = _extension(data)
    content_type = _TYPES[ext]
    day = datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y/%m/%d")
    digest = hashlib.md5(data).hexdigest()
    key = f"{settings['upload_dir']}/image/{day}/{digest}.{ext}"
    if not _put_object(settings, key, data, content_type):
        return ""
    return f"{settings['public_base']}/{key}"


def decrypt_im_image(data: bytes, skey: str) -> bytes | None:
    if not data:
        return None
    if _is_image(data):
        return data
    key = _aes_key(skey)
    if key is None or len(data) < 28:
        return None
    try:
        plain = AESGCM(key).decrypt(data[:12], data[12:], None)
    except Exception:
        return None
    return plain if _is_image(plain) else None


def store_image(data: bytes) -> str:
    name = f"{hashlib.sha256(data).hexdigest()[:32]}.{_extension(data)}"
    root = media_dir()
    root.mkdir(parents=True, exist_ok=True)
    path = root / name
    if not path.exists():
        path.write_bytes(data)
    return name


def load_media(name: str) -> tuple[bytes, str] | None:
    if not _NAME.fullmatch(name):
        return None
    root = media_dir().resolve()
    path = (root / name).resolve()
    if path.parent != root or not path.is_file():
        return None
    return path.read_bytes(), _TYPES[name.rsplit(".", 1)[-1]]


def _plaintext(raw: dict[str, Any], cdn_url: str, fetch: Callable[[str], bytes]) -> bytes | None:
    skey = _skey(raw)
    for url in _candidate_urls(raw, cdn_url):
        try:
            blob = fetch(url)
        except Exception as exc:
            logger.warning("douyin image download failed: %s", type(exc).__name__)
            continue
        plain = decrypt_im_image(blob, skey)
        if plain is not None:
            return plain
    return None


def _candidate_urls(raw: dict[str, Any], primary: str) -> list[str]:
    urls: list[str] = []
    if primary.startswith("http"):
        urls.append(primary)
    for key in ("resource_url", "url", "cover_url"):
        block = raw.get(key)
        if not isinstance(block, dict):
            continue
        for name in ("origin_url_list", "large_url_list", "url_list"):
            for item in block.get(name) or []:
                if isinstance(item, str) and item.startswith("http") and item not in urls:
                    urls.append(item)
    resource = raw.get("resource_url")
    oid = str(resource.get("oid") or "").strip() if isinstance(resource, dict) else ""
    if oid and not oid.startswith("http"):
        fallback = f"https://p3.douyinpic.com/obj/{oid}"
        if fallback not in urls:
            urls.append(fallback)
    return urls[:3]


def _skey(raw: dict[str, Any]) -> str:
    for key in ("resource_url", "url", "cover_url"):
        block = raw.get(key)
        if isinstance(block, dict):
            value = str(block.get("skey") or "").strip()
            if value:
                return value
    return str(raw.get("skey") or "").strip()


def _inline_pic(raw: dict[str, Any]) -> bytes | None:
    text = str(raw.get("inline_pic") or "").strip()
    if "," in text and text.lower().startswith("data:"):
        text = text.split(",", 1)[1]
    if not text:
        return None
    try:
        data = base64.b64decode(text)
    except Exception:
        return None
    return data if _is_image(data) else None


def _aes_key(skey: str) -> bytes | None:
    text = skey.strip()
    if len(text) < 64 or len(text) % 2 or any(c not in "0123456789abcdefABCDEF" for c in text):
        return None
    try:
        key = bytes.fromhex(text)
    except ValueError:
        return None
    if len(key) < 32:
        return None
    return key[:32]


def _is_image(data: bytes) -> bool:
    return (
        data.startswith(b"\xff\xd8\xff")
        or data.startswith(b"\x89PNG\r\n\x1a\n")
        or data.startswith(b"GIF87a")
        or data.startswith(b"GIF89a")
        or (len(data) >= 12 and data.startswith(b"RIFF") and data[8:12] == b"WEBP")
    )


def _extension(data: bytes) -> str:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "gif"
    if len(data) >= 12 and data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "webp"
    return "jpg"


def _oss_settings() -> dict[str, str] | None:
    file_values = _dotenv_values()

    def value(name: str) -> str:
        return os.environ.get(name, file_values.get(name, "")).strip()

    access_key_id = value("OSS_ACCESS_KEY_ID")
    access_key_secret = value("OSS_ACCESS_KEY_SECRET")
    bucket = value("OSS_BUCKET")
    region = value("OSS_REGION")
    endpoint = value("OSS_ENDPOINT").removeprefix("https://").removeprefix("http://").strip("/")
    upload_dir = value("OSS_UPLOAD_DIR").strip("/") or "edge"
    public_base = value("OSS_PUBLIC_BASE_URL").rstrip("/")
    if not public_base and endpoint:
        public_base = f"https://{endpoint}"
    if not all((access_key_id, access_key_secret, bucket, region, public_base)):
        return None
    return {
        "access_key_id": access_key_id,
        "access_key_secret": access_key_secret,
        "bucket": bucket,
        "region": region,
        "upload_dir": upload_dir,
        "public_base": public_base,
    }


def _dotenv_values() -> dict[str, str]:
    path = Path(".env")
    if not path.is_file():
        return {}
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, item = line.split("=", 1)
        values[key.strip()] = item.strip().strip('"').strip("'")
    return values


def _put_object(settings: dict[str, str], key: str, data: bytes, content_type: str) -> bool:
    date = formatdate(usegmt=True)
    resource = f"/{settings['bucket']}/{key}"
    string_to_sign = f"PUT\n\n{content_type}\n{date}\n{resource}"
    signature = base64.b64encode(
        hmac.new(settings["access_key_secret"].encode(), string_to_sign.encode(), hashlib.sha1).digest()
    ).decode()
    url = f"https://{settings['bucket']}.oss-{settings['region']}.aliyuncs.com/{key}"
    try:
        response = requests.put(
            url,
            data=data,
            headers={
                "Date": date,
                "Content-Type": content_type,
                "Authorization": f"OSS {settings['access_key_id']}:{signature}",
            },
            timeout=30,
        )
    except requests.RequestException as exc:
        logger.warning("douyin image OSS upload failed: %s", type(exc).__name__)
        return False
    if response.status_code not in (200, 201):
        logger.warning("douyin image OSS upload failed: HTTP %s", response.status_code)
        return False
    return True


def _download(url: str) -> bytes:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
        ),
        "Referer": "https://www.douyin.com/",
    }
    try:
        response = requests.get(url, headers=headers, timeout=20)
    except requests.exceptions.SSLError:
        response = requests.get(url, headers=headers, timeout=20, verify=False)
    response.raise_for_status()
    return response.content
