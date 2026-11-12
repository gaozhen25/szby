import hashlib

from app.services.extract_service.video_source_persistence import VideoSourcePersistenceService


class FakeResponse:
    headers = {"Content-Type": "video/mp4", "Content-Length": "11"}

    def raise_for_status(self):
        return None

    def iter_content(self, chunk_size):  # noqa: ANN001, ARG002
        yield b"video-bytes"


class FakeSession:
    def __init__(self):
        self.calls = []

    def get(self, url, **kwargs):  # noqa: ANN001
        self.calls.append((url, kwargs))
        return FakeResponse()


class FakeStorage:
    def __init__(self):
        self.calls = []

    def put_bytes(self, key, data, content_type):  # noqa: ANN001
        self.calls.append((key, data, content_type))
        return f"https://oss.example.test/{key}"

    def put_file(self, key, path, content_type):  # noqa: ANN001
        self.calls.append((key, path.read_bytes(), content_type))
        return f"https://oss.example.test/{key}"


def test_video_source_is_downloaded_and_persisted_with_stable_source_key(monkeypatch):
    monkeypatch.setattr(
        "app.services.extract_service.video_source_persistence.settings.object_storage_upload_dir",
        "starx",
    )
    session = FakeSession()
    storage = FakeStorage()
    service = VideoSourcePersistenceService(storage=storage, media_session=session)

    result = service.persist(
        "http://cdn.example.test/video.mp4?sign=temporary",
        source_url="https://www.xiaohongshu.com/explore/note-1",
        owner_id="acc_1",
    )

    digest = hashlib.sha256(b"https://www.xiaohongshu.com/explore/note-1").hexdigest()
    assert result == f"https://oss.example.test/starx/extract/video-analysis/acc_1/{digest}.mp4"
    assert storage.calls == [
        (f"starx/extract/video-analysis/acc_1/{digest}.mp4", b"video-bytes", "video/mp4")
    ]
    assert session.calls[0][1]["stream"] is True


def test_managed_object_storage_video_is_reused(monkeypatch):
    monkeypatch.setattr(
        "app.services.extract_service.video_source_persistence.settings.object_storage_public_base_url",
        "https://oss.example.test",
    )
    session = FakeSession()
    storage = FakeStorage()
    service = VideoSourcePersistenceService(storage=storage, media_session=session)
    url = "https://oss.example.test/extract/video.mp4"

    assert service.persist(url, owner_id="acc_1") == url
    assert session.calls == []
    assert storage.calls == []


def test_downloaded_video_is_persisted_without_another_http_request(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "app.services.extract_service.video_source_persistence.settings.object_storage_upload_dir",
        "starx",
    )
    session = FakeSession()
    storage = FakeStorage()
    service = VideoSourcePersistenceService(storage=storage, media_session=session)
    local_path = tmp_path / "source.mp4"
    local_path.write_bytes(b"video-bytes")

    result = service.persist_downloaded(
        "http://cdn.example.test/video.mp4?sign=temporary",
        local_path,
        source_url="https://www.xiaohongshu.com/explore/note-1",
        owner_id="acc_1",
    )

    digest = hashlib.sha256(b"https://www.xiaohongshu.com/explore/note-1").hexdigest()
    assert result == f"https://oss.example.test/starx/extract/video-analysis/acc_1/{digest}.mp4"
    assert storage.calls == [
        (f"starx/extract/video-analysis/acc_1/{digest}.mp4", b"video-bytes", "video/mp4")
    ]
    assert session.calls == []
