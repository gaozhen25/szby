from dataclasses import dataclass
from datetime import timedelta
from io import BytesIO
from pathlib import Path
from time import sleep
from typing import Any
from urllib.parse import quote

from app.core.config import settings

BUCKET_ALREADY_EXISTS_CODES = {"BucketAlreadyOwnedByYou", "BucketAlreadyExists"}
STORAGE_RETRY_DELAYS_SECONDS = (0.2, 0.5)
TRANSIENT_STORAGE_EXCEPTION_NAMES = {
    "ConnectTimeout",
    "ConnectionError",
    "MaxRetryError",
    "NewConnectionError",
    "ReadTimeout",
    "RequestError",
    "SSLError",
    "Timeout",
}


def resolve_oss_api_endpoint(
    *,
    endpoint: str,
    region: str,
    use_cname: bool,
) -> tuple[str, bool]:
    """服务端管理请求走 OSS 官方端点，CNAME 仅用于生成公开访问地址。"""
    clean_endpoint = str(endpoint or "").strip()
    clean_region = str(region or "").strip()
    if use_cname and clean_region:
        scheme = ""
        if clean_endpoint.startswith("https://"):
            scheme = "https://"
        elif clean_endpoint.startswith("http://"):
            scheme = "http://"
        return f"{scheme}oss-{clean_region}.aliyuncs.com", False
    return clean_endpoint, use_cname


class ObjectStorageUploadError(RuntimeError):
    """Raised when an object cannot be persisted after transient retries."""


@dataclass(frozen=True)
class ObjectStat:
    size_bytes: int
    content_type: str
    etag: str


class AliyunOssClient:
    # OSS buckets are provisioned outside this application. In particular,
    # get_bucket_info() is unreliable through some CNAME endpoints and is not
    # required before uploading an object.
    requires_bucket_setup = False

    def __init__(
        self,
        *,
        endpoint: str,
        access_key: str,
        secret_key: str,
        bucket: str,
        region: str,
        secure: bool,
        use_cname: bool,
    ) -> None:
        import oss2

        scheme = "https" if secure else "http"
        endpoint_url = endpoint if endpoint.startswith(("http://", "https://")) else f"{scheme}://{endpoint}"
        auth = oss2.Auth(access_key, secret_key)
        self.bucket = oss2.Bucket(
            auth,
            endpoint_url,
            bucket,
            region=region or None,
            is_cname=use_cname,
        )

    def bucket_exists(self, bucket: str) -> bool:  # noqa: ARG002
        try:
            self.bucket.get_bucket_info()
        except self._oss_error_type() as exc:
            if getattr(exc, "code", None) == "NoSuchBucket":
                return False
            raise
        return True

    def make_bucket(self, bucket: str) -> None:  # noqa: ARG002
        self.bucket.create_bucket()

    def put_object(self, bucket: str, key: str, data: BytesIO, *, length: int, content_type: str) -> None:  # noqa: ARG002
        self.bucket.put_object(key, data, headers={"Content-Type": content_type})

    def remove_object(self, bucket: str, key: str) -> None:  # noqa: ARG002
        self.bucket.delete_object(key)

    def presigned_put_object(
        self,
        bucket: str,  # noqa: ARG002
        key: str,
        *,
        expires: timedelta,
        content_type: str,
    ) -> str:
        return self.bucket.sign_url(
            "PUT",
            key,
            int(expires.total_seconds()),
            headers={"Content-Type": content_type},
            slash_safe=True,
        )

    def stat_object(self, bucket: str, key: str) -> ObjectStat:  # noqa: ARG002
        result = self.bucket.head_object(key)
        return ObjectStat(
            size_bytes=int(getattr(result, "content_length", 0) or 0),
            content_type=str(getattr(result, "content_type", "") or ""),
            etag=str(getattr(result, "etag", "") or "").strip('"'),
        )

    @staticmethod
    def _oss_error_type() -> type[Exception]:
        try:
            from oss2.exceptions import OssError
        except ModuleNotFoundError:
            return Exception

        return OssError


class ObjectStorage:
    def __init__(
        self,
        *,
        provider: str | None = None,
        endpoint: str | None = None,
        access_key: str | None = None,
        secret_key: str | None = None,
        bucket: str | None = None,
        region: str | None = None,
        secure: bool | None = None,
        use_cname: bool | None = None,
        public_base_url: str | None = None,
        client: Any | None = None,
    ) -> None:
        self.bucket = bucket or settings.object_storage_bucket
        self.use_cname = settings.object_storage_use_cname if use_cname is None else use_cname
        self.public_base_url = (
            public_base_url or settings.object_storage_public_base_url
        ).rstrip("/")
        effective_provider = provider or settings.object_storage_provider
        effective_endpoint = endpoint or settings.object_storage_endpoint
        effective_region = region or settings.object_storage_region
        client_use_cname = self.use_cname
        if effective_provider == "oss":
            effective_endpoint, client_use_cname = resolve_oss_api_endpoint(
                endpoint=effective_endpoint,
                region=effective_region,
                use_cname=self.use_cname,
            )
        self.client = client or self._create_client(
            provider=effective_provider,
            endpoint=effective_endpoint,
            access_key=access_key or settings.object_storage_access_key,
            secret_key=secret_key or settings.object_storage_secret_key,
            bucket=self.bucket,
            region=effective_region,
            secure=settings.object_storage_secure if secure is None else secure,
            use_cname=client_use_cname,
        )
        self._bucket_ready = False

    @staticmethod
    def _create_client(
        *,
        provider: str,
        endpoint: str,
        access_key: str,
        secret_key: str,
        bucket: str,
        region: str,
        secure: bool,
        use_cname: bool,
    ) -> Any:
        if provider == "oss":
            return AliyunOssClient(
                endpoint=endpoint,
                access_key=access_key,
                secret_key=secret_key,
                bucket=bucket,
                region=region,
                secure=secure,
                use_cname=use_cname,
            )

        from minio import Minio

        return Minio(
            endpoint,
            access_key=access_key,
            secret_key=secret_key,
            secure=secure,
        )

    def ensure_bucket(self) -> None:
        if self._bucket_ready:
            return
        if not getattr(self.client, "requires_bucket_setup", True):
            self._bucket_ready = True
            return
        if not self.client.bucket_exists(self.bucket):
            s3_error_type = self._s3_error_type()
            try:
                self.client.make_bucket(self.bucket)
            except s3_error_type as exc:
                if getattr(exc, "code", None) in BUCKET_ALREADY_EXISTS_CODES:
                    self._bucket_ready = True
                    return
                raise
        self._bucket_ready = True

    def put_bytes(self, key: str, data: bytes, content_type: str) -> str:
        try:
            self._with_transient_retries(self.ensure_bucket)
            self._with_transient_retries(
                lambda: self.client.put_object(
                    self.bucket,
                    key,
                    BytesIO(data),
                    length=len(data),
                    content_type=content_type,
                )
            )
        except Exception as exc:
            raise ObjectStorageUploadError(f"object upload failed: {key}") from exc
        return self.public_url(key)

    def put_file(self, key: str, path: str | Path, content_type: str) -> str:
        source = Path(path)
        length = source.stat().st_size
        try:
            self._with_transient_retries(self.ensure_bucket)

            def upload() -> None:
                with source.open("rb") as stream:
                    self.client.put_object(
                        self.bucket,
                        key,
                        stream,
                        length=length,
                        content_type=content_type,
                    )

            self._with_transient_retries(upload)
        except Exception as exc:
            raise ObjectStorageUploadError(f"object upload failed: {key}") from exc
        return self.public_url(key)

    def public_url(self, key: str) -> str:
        if self.use_cname:
            return f"{self.public_base_url}/{quote(key, safe='/')}"
        return f"{self.public_base_url}/{self.bucket}/{quote(key, safe='/')}"

    def delete_object(self, key: str) -> None:
        self.client.remove_object(self.bucket, key)

    def presign_put(self, key: str, content_type: str, expires_seconds: int) -> str:
        self.ensure_bucket()
        expires = timedelta(seconds=max(int(expires_seconds), 1))
        signer = getattr(self.client, "presigned_put_object")
        try:
            return signer(
                self.bucket,
                key,
                expires=expires,
                content_type=content_type,
            )
        except TypeError:
            # MinIO does not bind Content-Type into presigned PUT URLs.
            return signer(self.bucket, key, expires=expires)

    def stat_object(self, key: str) -> ObjectStat:
        result = self._with_transient_retries(
            lambda: self.client.stat_object(self.bucket, key)
        )
        if isinstance(result, ObjectStat):
            return result
        metadata = getattr(result, "metadata", {}) or {}
        return ObjectStat(
            size_bytes=int(getattr(result, "size", 0) or 0),
            content_type=str(
                getattr(result, "content_type", "")
                or metadata.get("content-type")
                or metadata.get("Content-Type")
                or ""
            ),
            etag=str(getattr(result, "etag", "") or "").strip('"'),
        )

    @staticmethod
    def _is_transient_error(exc: BaseException) -> bool:
        current: BaseException | None = exc
        visited: set[int] = set()
        while current is not None and id(current) not in visited:
            visited.add(id(current))
            if current.__class__.__name__ in TRANSIENT_STORAGE_EXCEPTION_NAMES:
                return True
            current = current.__cause__ or current.__context__
        return False

    @classmethod
    def _with_transient_retries(cls, action: Any) -> Any:
        for attempt in range(len(STORAGE_RETRY_DELAYS_SECONDS) + 1):
            try:
                return action()
            except Exception as exc:
                if attempt >= len(STORAGE_RETRY_DELAYS_SECONDS) or not cls._is_transient_error(exc):
                    raise
                sleep(STORAGE_RETRY_DELAYS_SECONDS[attempt])
        raise AssertionError("unreachable storage retry state")

    @staticmethod
    def _s3_error_type() -> type[Exception]:
        try:
            from minio.error import S3Error
        except ModuleNotFoundError:
            return Exception

        return S3Error


class LazyObjectStorage:
    def __init__(self) -> None:
        self._storage: ObjectStorage | None = None

    def _get_storage(self) -> ObjectStorage:
        if self._storage is None:
            self._storage = ObjectStorage()
        return self._storage

    def __getattr__(self, name: str) -> Any:
        return getattr(self._get_storage(), name)


default_object_storage = LazyObjectStorage()
