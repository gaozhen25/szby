from io import BytesIO
from typing import Any
from urllib.parse import quote

from app.core.config import settings

BUCKET_ALREADY_EXISTS_CODES = {"BucketAlreadyOwnedByYou", "BucketAlreadyExists"}


class AliyunOssClient:
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
        self.bucket.put_object(key, data.read(length), headers={"Content-Type": content_type})

    def remove_object(self, bucket: str, key: str) -> None:  # noqa: ARG002
        self.bucket.delete_object(key)

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
        self.client = client or self._create_client(
            provider=provider or settings.object_storage_provider,
            endpoint=endpoint or settings.object_storage_endpoint,
            access_key=access_key or settings.object_storage_access_key,
            secret_key=secret_key or settings.object_storage_secret_key,
            bucket=self.bucket,
            region=region or settings.object_storage_region,
            secure=settings.object_storage_secure if secure is None else secure,
            use_cname=self.use_cname,
        )

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
        if not self.client.bucket_exists(self.bucket):
            s3_error_type = self._s3_error_type()
            try:
                self.client.make_bucket(self.bucket)
            except s3_error_type as exc:
                if getattr(exc, "code", None) in BUCKET_ALREADY_EXISTS_CODES:
                    return
                raise

    def put_bytes(self, key: str, data: bytes, content_type: str) -> str:
        self.ensure_bucket()
        self.client.put_object(
            self.bucket,
            key,
            BytesIO(data),
            length=len(data),
            content_type=content_type,
        )
        return self.public_url(key)

    def public_url(self, key: str) -> str:
        if self.use_cname:
            return f"{self.public_base_url}/{quote(key, safe='/')}"
        return f"{self.public_base_url}/{self.bucket}/{quote(key, safe='/')}"

    def delete_object(self, key: str) -> None:
        self.client.remove_object(self.bucket, key)

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
