"""Aliyun OSS storage.

Uploads, deletes, and reads use the regional endpoint. Gallery streams the bytes;
callers never receive an expiring signed URL.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Callable, Protocol

CONTENT_TYPES = {
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "webp": "image/webp",
    "mp4": "video/mp4",
    "mov": "video/quicktime",
}

REQUIRED_ENV = (
    "OSS_ACCESS_KEY_ID",
    "OSS_ACCESS_KEY_SECRET",
    "OSS_BUCKET",
    "OSS_REGION",
    "OSS_ENDPOINT",
)


class StoreError(Exception):
    pass


def plain_store_error(detail: str) -> str:
    folded = detail.lower()
    if "accessdenied" in folded or "bucket acl" in folded or "does not belong" in folded:
        return "OSS 拒绝写入：AccessKey 不是这个桶的主人"
    if "peer closed connection" in folded or "incomplete message body" in folded or "下载中途被对方断开" in detail:
        return "视频下载中途被对方断开，已收到一部分但没传完，请再解析一次"
    if "file too large" in folded:
        return "文件超过当前允许的大小上限"
    return " ".join(detail.split())[:300]


def content_type(ext: str) -> str:
    return CONTENT_TYPES.get(ext.lower().lstrip("."), "application/octet-stream")


def resolve_oss_api_endpoint(*, endpoint: str, region: str, use_cname: bool) -> tuple[str, bool]:
    """Server calls use the official regional endpoint. A CNAME is only a public name."""
    clean_endpoint = str(endpoint or "").strip()
    name = str(region or "").strip().lower()
    if name.startswith("oss-"):
        name = name[4:]
    if use_cname and name:
        scheme = "https://"
        if clean_endpoint.startswith("http://"):
            scheme = "http://"
        return f"{scheme}oss-{name}.aliyuncs.com", False
    return clean_endpoint, use_cname


_TRANSIENT = {"ConnectTimeout", "ConnectionError", "MaxRetryError", "ReadTimeout", "RequestError", "SSLError", "Timeout"}
_RETRY_DELAYS = (0.2, 0.5)


class ObjectStore(Protocol):
    configured: bool

    def object_key(self, item_id: str, index: int, ext: str) -> str: ...

    def put_file(self, key: str, path: Path, mime: str) -> None: ...

    def put_remote(self, key: str, url: str, *, want_mp4: bool, max_bytes: int) -> int: ...

    def delete(self, key: str) -> None: ...

    def read(self, key: str): ...

    def status(self) -> dict[str, Any]: ...


class MemoryStore:
    """In-memory stand-in used by tests."""

    configured = True

    def __init__(self, prefix: str = "gallery", receive: Callable[..., bytes] | None = None):
        self.prefix = prefix.strip("/") or "gallery"
        self.objects: dict[str, bytes] = {}
        self.receive = receive

    def object_key(self, item_id: str, index: int, ext: str) -> str:
        return f"{self.prefix}/{item_id}/{index}.{ext}"

    def put_file(self, key: str, path: Path, mime: str) -> None:
        self.objects[key] = path.read_bytes()

    def put_remote(self, key: str, url: str, *, want_mp4: bool, max_bytes: int) -> int:
        if self.receive is not None:
            data = self.receive(url, want_mp4=want_mp4, max_bytes=max_bytes)
        else:
            data = b"\x00\x00\x00\x18ftypmp42" if want_mp4 else b"jpeg-bytes"
        self.objects[key] = data
        return len(data)

    def delete(self, key: str) -> None:
        self.objects.pop(key, None)

    def read(self, key: str):
        if key not in self.objects:
            raise StoreError("missing")
        data = self.objects[key]

        def chunks():
            yield data

        return chunks()

    def status(self) -> dict[str, Any]:
        return {
            "configured": True,
            "provider": "memory",
            "bucket": "memory",
            "endpoint": "https://oss.example",
            "prefix": self.prefix,
            "public_base": "https://oss.example",
            "signed": False,
            "missing": [],
        }


class UnconfiguredStore:
    configured = False

    def object_key(self, item_id: str, index: int, ext: str) -> str:
        return f"gallery/{item_id}/{index}.{ext}"

    def put_file(self, key: str, path: Path, mime: str) -> None:
        missing = [name for name in REQUIRED_ENV if not os.environ.get(name, "").strip()]
        names = "、".join(missing or list(REQUIRED_ENV))
        raise StoreError(f"OSS 未配置。请设置 {names}")

    def put_remote(self, key: str, url: str, *, want_mp4: bool, max_bytes: int) -> int:
        self.put_file(key, Path(key), "")
        return 0

    def delete(self, key: str) -> None:
        return None

    def read(self, key: str):
        raise StoreError("OSS 未配置")

    def status(self) -> dict[str, Any]:
        missing = [name for name in REQUIRED_ENV if not os.environ.get(name, "").strip()]
        return {"configured": False, "provider": "aliyun-oss", "missing": missing}


def _flag(value: str, default: bool) -> bool:
    if not value.strip():
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


class OssStore:
    """Private bucket: write through the regional host, read with a signed URL."""

    configured = True

    def __init__(
        self,
        access_key_id: str,
        access_key_secret: str,
        endpoint: str,
        bucket: str,
        region: str,
        prefix: str,
        use_cname: bool,
    ):
        self.access_key_id = access_key_id
        self.access_key_secret = access_key_secret
        self.endpoint = endpoint.rstrip("/")
        self.bucket_name = bucket
        self.region = region
        self.prefix = prefix.strip("/") or "gallery"
        self.use_cname = use_cname
        self.api_endpoint, self.client_cname = resolve_oss_api_endpoint(
            endpoint=self.endpoint,
            region=region,
            use_cname=use_cname,
        )
        self.api_host = f"{bucket}.{self.api_endpoint.split('://', 1)[-1]}"
        self._bucket = None

    @classmethod
    def from_env(cls) -> OssStore | None:
        values = {name: os.environ.get(name, "").strip() for name in REQUIRED_ENV}
        if not all(values.values()):
            return None
        endpoint = values["OSS_ENDPOINT"]
        if not endpoint.startswith("http"):
            endpoint = "https://" + endpoint
        upload_dir = os.environ.get("OSS_UPLOAD_DIR", "").strip() or os.environ.get("OSS_PREFIX", "").strip() or "gallery"
        return cls(
            values["OSS_ACCESS_KEY_ID"],
            values["OSS_ACCESS_KEY_SECRET"],
            endpoint,
            values["OSS_BUCKET"],
            values["OSS_REGION"],
            upload_dir,
            _flag(os.environ.get("OSS_USE_CNAME", ""), True),
        )

    @staticmethod
    def _region_host(region: str) -> str:
        name = region.strip().lower()
        if name.startswith("oss-"):
            name = name[4:]
        return f"oss-{name}.aliyuncs.com"

    def object_key(self, item_id: str, index: int, ext: str) -> str:
        return f"{self.prefix}/{item_id}/{index}.{ext}"

    def _client(self):
        if self._bucket is not None:
            return self._bucket
        try:
            import oss2
        except ImportError as exc:
            raise StoreError("需要先安装 oss2，上传才会走官方 OSS 客户端") from exc

        auth = oss2.Auth(self.access_key_id, self.access_key_secret)
        self._bucket = oss2.Bucket(
            auth,
            self.api_endpoint,
            self.bucket_name,
            region=self.region or None,
            is_cname=self.client_cname,
        )
        return self._bucket

    def _call(self, action):
        from time import sleep

        for attempt in range(len(_RETRY_DELAYS) + 1):
            try:
                return action()
            except Exception as exc:
                transient = exc.__class__.__name__ in _TRANSIENT
                if attempt >= len(_RETRY_DELAYS) or not transient:
                    detail = getattr(exc, "details", None) or str(exc)
                    raise StoreError(plain_store_error(str(detail))) from exc
                sleep(_RETRY_DELAYS[attempt])
        raise AssertionError("unreachable storage retry")

    def put_file(self, key: str, path: Path, mime: str) -> None:
        def upload() -> None:
            with path.open("rb") as handle:
                self._client().put_object(key, handle, headers={"Content-Type": mime})

        self._call(upload)

    def put_remote(self, key: str, url: str, *, want_mp4: bool, max_bytes: int) -> int:
        """Stream CDN bytes straight into OSS. Nothing is kept on the gallery disk."""
        from time import sleep

        from app.fetch import SaveError, open_remote

        ext = Path(key).suffix.lstrip(".") or ("mp4" if want_mp4 else "bin")
        mime = content_type(ext)
        last: Exception | None = None
        for attempt in range(3):
            try:
                with open_remote(url, want_mp4=want_mp4, max_bytes=max_bytes) as body:
                    # put_object reads the stream in chunks, so download and upload overlap.
                    self._client().put_object(key, body, headers={"Content-Type": mime})
                    return body.written
            except SaveError as exc:
                last = exc
                detail = str(exc).lower()
                if attempt < 2 and ("断开" in str(exc) or "peer closed" in detail or "incomplete" in detail):
                    sleep(0.4 * (attempt + 1))
                    continue
                raise StoreError(plain_store_error(str(exc))) from exc
            except Exception as exc:
                last = exc
                detail = str(getattr(exc, "details", None) or exc).lower()
                if attempt < 2 and ("peer closed" in detail or "incomplete" in detail):
                    sleep(0.4 * (attempt + 1))
                    continue
                raise StoreError(plain_store_error(str(getattr(exc, "details", None) or exc))) from exc
        raise StoreError(plain_store_error(str(last or "upload failed")))

    def delete(self, key: str) -> None:
        if key:
            self._call(lambda: self._client().delete_object(key))

    def read(self, key: str):
        result = self._call(lambda: self._client().get_object(key))

        def chunks():
            try:
                while True:
                    piece = result.read(1024 * 1024)
                    if not piece:
                        break
                    yield piece
            finally:
                close = getattr(result, "close", None)
                if close:
                    close()

        return chunks()

    def status(self) -> dict[str, Any]:
        return {
            "configured": True,
            "provider": "aliyun-oss",
            "bucket": self.bucket_name,
            "region": self.region,
            "endpoint": f"https://{self.api_host}",
            "prefix": self.prefix,
            "use_cname": self.use_cname,
            "public_base": "",
            "signed": False,
            "permanent": True,
            "missing": [],
        }


def build_store() -> ObjectStore:
    found = OssStore.from_env()
    if found is not None:
        return found
    return UnconfiguredStore()
