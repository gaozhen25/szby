import sys
from types import ModuleType, SimpleNamespace

import pytest

from app.core.config import Settings
from app.services.object_storage import (
    ObjectStat,
    ObjectStorage,
    ObjectStorageUploadError,
    resolve_oss_api_endpoint,
)


def test_object_storage_settings_have_local_minio_defaults(monkeypatch):
    monkeypatch.delenv("OSS_ACCESS_KEY_ID", raising=False)
    monkeypatch.delenv("OSS_ACCESS_KEY_SECRET", raising=False)
    monkeypatch.delenv("OSS_BUCKET", raising=False)
    monkeypatch.delenv("OSS_REGION", raising=False)
    monkeypatch.delenv("OSS_ENDPOINT", raising=False)
    monkeypatch.delenv("OSS_UPLOAD_DIR", raising=False)
    monkeypatch.delenv("OSS_USE_CNAME", raising=False)
    settings = Settings(_env_file=None)

    assert settings.object_storage_endpoint == "localhost:9000"
    assert settings.object_storage_public_base_url == "http://localhost:9000"
    assert settings.object_storage_access_key == "starx"
    assert settings.object_storage_secret_key == "starx123"
    assert settings.object_storage_bucket == "starx-assets"
    assert settings.object_storage_secure is False
    assert settings.object_storage_upload_dir == ""
    assert settings.object_storage_use_cname is False


def test_object_storage_settings_accept_aliyun_oss_env_aliases(monkeypatch):
    monkeypatch.setenv("OSS_ACCESS_KEY_ID", "oss-access-key")
    monkeypatch.setenv("OSS_ACCESS_KEY_SECRET", "oss-secret-key")
    monkeypatch.setenv("OSS_BUCKET", "zycx-oss-dj")
    monkeypatch.setenv("OSS_REGION", "ap-northeast-1")
    monkeypatch.setenv("OSS_ENDPOINT", "oss.zycx.info")
    monkeypatch.setenv("OSS_UPLOAD_DIR", "starx")
    monkeypatch.setenv("OSS_USE_CNAME", "true")

    settings = Settings()

    assert settings.object_storage_provider == "oss"
    assert settings.object_storage_endpoint == "oss.zycx.info"
    assert settings.object_storage_public_base_url == "https://oss.zycx.info"
    assert settings.object_storage_access_key == "oss-access-key"
    assert settings.object_storage_secret_key == "oss-secret-key"
    assert settings.object_storage_bucket == "zycx-oss-dj"
    assert settings.object_storage_region == "ap-northeast-1"
    assert settings.object_storage_upload_dir == "starx"
    assert settings.object_storage_use_cname is True
    assert settings.object_storage_secure is True


def test_object_storage_public_url_preserves_nested_paths_and_quotes_spaces():
    storage = ObjectStorage(
        client=object(),
        bucket="starx-assets",
        public_base_url="http://localhost:9000",
        endpoint="unused",
        access_key="x",
        secret_key="y",
        use_cname=False,
    )

    assert (
        storage.public_url("users/1/uploads/a b.png")
        == "http://localhost:9000/starx-assets/users/1/uploads/a%20b.png"
    )


def test_object_storage_public_url_omits_bucket_for_cname_public_base_url():
    storage = ObjectStorage(
        client=object(),
        bucket="zycx-oss-dj",
        public_base_url="https://oss.zycx.info",
        endpoint="unused",
        access_key="x",
        secret_key="y",
        use_cname=True,
    )

    assert (
        storage.public_url("starx/users/1/uploads/a b.png")
        == "https://oss.zycx.info/starx/users/1/uploads/a%20b.png"
    )


def test_oss_cname_uses_official_region_endpoint_for_server_side_operations():
    endpoint, use_cname = resolve_oss_api_endpoint(
        endpoint="https://oss.humanlike.life",
        region="cn-hangzhou",
        use_cname=True,
    )

    assert endpoint == "https://oss-cn-hangzhou.aliyuncs.com"
    assert use_cname is False


def test_oss_endpoint_is_unchanged_when_cname_is_disabled():
    endpoint, use_cname = resolve_oss_api_endpoint(
        endpoint="oss-cn-hangzhou.aliyuncs.com",
        region="cn-hangzhou",
        use_cname=False,
    )

    assert endpoint == "oss-cn-hangzhou.aliyuncs.com"
    assert use_cname is False


def test_object_storage_put_file_streams_file_to_client(tmp_path):
    source = tmp_path / "segment.mp4"
    source.write_bytes(b"video-segment")

    class FakeClient:
        def __init__(self):
            self.upload = None

        def bucket_exists(self, bucket):
            return True

        def put_object(self, bucket, key, stream, *, length, content_type):
            self.upload = (bucket, key, stream.read(), length, content_type)

    client = FakeClient()
    storage = ObjectStorage(
        client=client,
        bucket="starx-assets",
        public_base_url="http://localhost:9000",
        endpoint="unused",
        access_key="x",
        secret_key="y",
        use_cname=False,
    )

    url = storage.put_file("segments/one.mp4", source, "video/mp4")

    assert url == "http://localhost:9000/starx-assets/segments/one.mp4"
    assert client.upload == (
        "starx-assets",
        "segments/one.mp4",
        b"video-segment",
        len(b"video-segment"),
        "video/mp4",
    )


def test_object_storage_skips_bucket_probe_for_preprovisioned_oss_client():
    class FakeOssClient:
        requires_bucket_setup = False

        def __init__(self):
            self.bucket_probes = 0
            self.uploads = 0

        def bucket_exists(self, bucket):  # noqa: ARG002
            self.bucket_probes += 1
            return True

        def put_object(self, bucket, key, stream, *, length, content_type):  # noqa: ARG002
            self.uploads += 1

    client = FakeOssClient()
    storage = ObjectStorage(
        client=client,
        bucket="starx-assets",
        public_base_url="https://oss.example.test",
        endpoint="unused",
        access_key="x",
        secret_key="y",
        use_cname=True,
    )

    storage.put_bytes("uploads/a.png", b"image", "image/png")
    storage.put_bytes("uploads/b.png", b"image", "image/png")

    assert client.bucket_probes == 0
    assert client.uploads == 2


def test_object_storage_retries_transient_upload_errors(monkeypatch):
    class SSLError(Exception):
        pass

    class FakeOssClient:
        requires_bucket_setup = False

        def __init__(self):
            self.uploads = 0

        def put_object(self, bucket, key, stream, *, length, content_type):  # noqa: ARG002
            self.uploads += 1
            if self.uploads < 3:
                raise SSLError("temporary TLS failure")

    monkeypatch.setattr("app.services.object_storage.sleep", lambda _seconds: None)
    client = FakeOssClient()
    storage = ObjectStorage(
        client=client,
        bucket="starx-assets",
        public_base_url="https://oss.example.test",
        endpoint="unused",
        access_key="x",
        secret_key="y",
        use_cname=True,
    )

    assert storage.put_bytes("uploads/a.png", b"image", "image/png").endswith("/uploads/a.png")
    assert client.uploads == 3


def test_object_storage_retries_transient_stat_errors(monkeypatch):
    class RequestError(Exception):
        pass

    class FakeOssClient:
        requires_bucket_setup = False

        def __init__(self):
            self.attempts = 0

        def stat_object(self, bucket, key):  # noqa: ARG002
            self.attempts += 1
            if self.attempts < 3:
                raise RequestError("temporary TLS failure")
            return SimpleNamespace(
                size=12,
                content_type="video/mp4",
                etag="etag",
            )

    monkeypatch.setattr("app.services.object_storage.sleep", lambda _seconds: None)
    client = FakeOssClient()
    storage = ObjectStorage(
        client=client,
        bucket="starx-assets",
        public_base_url="https://oss.example.test",
        endpoint="unused",
        access_key="x",
        secret_key="y",
        use_cname=True,
    )

    result = storage.stat_object("uploads/music.mp4")

    assert client.attempts == 3
    assert result == ObjectStat(12, "video/mp4", "etag")


def test_object_storage_wraps_non_transient_upload_errors():
    class FakeOssClient:
        requires_bucket_setup = False

        def put_object(self, bucket, key, stream, *, length, content_type):  # noqa: ARG002
            raise RuntimeError("access denied")

    storage = ObjectStorage(
        client=FakeOssClient(),
        bucket="starx-assets",
        public_base_url="https://oss.example.test",
        endpoint="unused",
        access_key="x",
        secret_key="y",
        use_cname=True,
    )

    with pytest.raises(ObjectStorageUploadError):
        storage.put_bytes("uploads/a.png", b"image", "image/png")


def test_ensure_bucket_ignores_concurrent_bucket_creation(monkeypatch):
    class FakeS3Error(Exception):
        def __init__(self, code):
            self.code = code

    minio_module = ModuleType("minio")
    minio_error_module = ModuleType("minio.error")
    minio_error_module.S3Error = FakeS3Error
    monkeypatch.setitem(sys.modules, "minio", minio_module)
    monkeypatch.setitem(sys.modules, "minio.error", minio_error_module)

    class FakeClient:
        def bucket_exists(self, bucket):
            return False

        def make_bucket(self, bucket):
            raise FakeS3Error("BucketAlreadyOwnedByYou")

    storage = ObjectStorage(
        client=FakeClient(),
        bucket="starx-assets",
        public_base_url="http://localhost:9000",
        endpoint="unused",
        access_key="x",
        secret_key="y",
    )

    storage.ensure_bucket()


def test_ensure_bucket_reraises_unexpected_s3_errors(monkeypatch):
    class FakeS3Error(Exception):
        def __init__(self, code):
            self.code = code

    minio_module = ModuleType("minio")
    minio_error_module = ModuleType("minio.error")
    minio_error_module.S3Error = FakeS3Error
    monkeypatch.setitem(sys.modules, "minio", minio_module)
    monkeypatch.setitem(sys.modules, "minio.error", minio_error_module)

    class FakeClient:
        def bucket_exists(self, bucket):
            return False

        def make_bucket(self, bucket):
            raise FakeS3Error("AccessDenied")

    storage = ObjectStorage(
        client=FakeClient(),
        bucket="starx-assets",
        public_base_url="http://localhost:9000",
        endpoint="unused",
        access_key="x",
        secret_key="y",
    )

    with pytest.raises(FakeS3Error):
        storage.ensure_bucket()
