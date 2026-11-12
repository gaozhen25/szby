import sys
from types import ModuleType

import pytest

from app.core.config import Settings
from app.services.object_storage import ObjectStorage


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
