import hashlib

import requests

from app.core.config import settings
from app.services.extract_service.asset_persistence import (
    ExtractAssetPersistenceService,
    ExtractHistorySnapshot,
)

SOURCE_IMAGE = "https://source.example.test/cover.webp"
SOURCE_VIDEO = "https://source.example.test/video.mp4"
REFRESHED_IMAGE = "https://refresh.example.test/cover.webp"
REFRESHED_VIDEO = "https://refresh.example.test/video.mp4"


class FakeResponse:
    def __init__(self, body: bytes, content_type: str):
        self.body = body
        self.headers = {
            "Content-Type": content_type,
            "Content-Length": str(len(body)),
        }

    def raise_for_status(self):
        return None

    def iter_content(self, chunk_size=1024 * 1024):  # noqa: ARG002
        yield self.body


class FakeMediaSession:
    def __init__(self, responses=None):
        self.responses = dict(responses or {})
        self.requests = []

    def get(self, url, **kwargs):
        self.requests.append((url, kwargs))
        response = self.responses.get(url)
        if isinstance(response, Exception):
            raise response
        if response is None:
            raise requests.ReadTimeout(f"missing fake response for {url}")
        return response


class FakeStorage:
    def __init__(self, fail_on_put_number=None):
        self.fail_on_put_number = fail_on_put_number
        self.put_calls = []
        self.delete_calls = []

    def put_bytes(self, key, data, content_type):
        self.put_calls.append((key, data, content_type))
        if self.fail_on_put_number == len(self.put_calls):
            raise RuntimeError("storage unavailable")
        return f"https://oss.example.test/{key}"

    def delete_object(self, key):
        self.delete_calls.append(key)


class FakeExtractor:
    def __init__(self, payload=None, error=None):
        self.payload = payload
        self.error = error
        self.urls = []

    def extract(self, url):
        self.urls.append(url)
        if self.error:
            raise self.error
        return self.payload


def media(source_url, kind):
    return {
        "sourceUrl": source_url,
        "url": source_url,
        "contentType": "",
        "kind": kind,
        "storageStatus": "external",
    }


def history_snapshot(*, existing_url_map=None):
    return ExtractHistorySnapshot(
        id="eh_1",
        account_id="acc1",
        source_url="https://v.douyin.com/source/",
        platform="douyin",
        images=[media(SOURCE_IMAGE, "image")],
        videos=[media(SOURCE_VIDEO, "video")],
        existing_url_map=dict(existing_url_map or {}),
    )


def success_responses(image_url=SOURCE_IMAGE, video_url=SOURCE_VIDEO):
    return {
        image_url: FakeResponse(b"image-bytes", "image/webp"),
        video_url: FakeResponse(b"video-bytes", "video/mp4"),
    }


def test_persist_uploads_all_media_with_stable_keys():
    storage = FakeStorage()
    media_session = FakeMediaSession(success_responses())
    service = ExtractAssetPersistenceService(
        storage=storage,
        media_session=media_session,
        extractor=FakeExtractor(),
    )

    result = service.persist(history_snapshot())

    assert result.status == "completed"
    assert result.retry_count == 0
    assert result.error == ""
    assert result.url_map[SOURCE_IMAGE].endswith(
        f"/extract/acc1/eh_1/image/{hashlib.sha256(SOURCE_IMAGE.encode()).hexdigest()}.webp"
    )
    assert result.url_map[SOURCE_VIDEO].endswith(
        f"/extract/acc1/eh_1/video/{hashlib.sha256(SOURCE_VIDEO.encode()).hexdigest()}.mp4"
    )
    assert [item["storageStatus"] for item in result.assets] == ["persisted", "persisted"]
    assert [request[0] for request in media_session.requests] == [SOURCE_IMAGE, SOURCE_VIDEO]


def test_persist_reextracts_original_link_then_succeeds():
    storage = FakeStorage()
    media_session = FakeMediaSession(
        {
            SOURCE_IMAGE: requests.ReadTimeout("expired image"),
            REFRESHED_IMAGE: FakeResponse(b"new-image", "image/webp"),
            REFRESHED_VIDEO: FakeResponse(b"new-video", "video/mp4"),
        }
    )
    extractor = FakeExtractor(
        payload={
            "platform": "douyin",
            "images": [REFRESHED_IMAGE],
            "videos": [REFRESHED_VIDEO],
        }
    )
    service = ExtractAssetPersistenceService(storage=storage, media_session=media_session, extractor=extractor)

    result = service.persist(history_snapshot())

    assert result.status == "completed"
    assert result.retry_count == 1
    assert extractor.urls == ["https://v.douyin.com/source/"]
    assert result.url_map[SOURCE_IMAGE] == result.url_map[REFRESHED_IMAGE]
    assert result.url_map[SOURCE_VIDEO] == result.url_map[REFRESHED_VIDEO]


def test_persist_falls_back_to_original_urls_after_second_failure():
    media_session = FakeMediaSession({SOURCE_IMAGE: requests.ReadTimeout("expired")})
    extractor = FakeExtractor(error=requests.ReadTimeout("share link unavailable"))
    service = ExtractAssetPersistenceService(
        storage=FakeStorage(),
        media_session=media_session,
        extractor=extractor,
    )

    result = service.persist(history_snapshot())

    assert result.status == "fallback"
    assert result.retry_count == 1
    assert result.url_map == {SOURCE_IMAGE: SOURCE_IMAGE, SOURCE_VIDEO: SOURCE_VIDEO}
    assert [item["url"] for item in result.assets] == [SOURCE_IMAGE, SOURCE_VIDEO]
    assert all(item["storageStatus"] == "external" for item in result.assets)
    assert "share link unavailable" in result.error


def test_persist_deletes_objects_uploaded_before_round_failure():
    storage = FakeStorage(fail_on_put_number=2)
    media_session = FakeMediaSession(success_responses())
    service = ExtractAssetPersistenceService(
        storage=storage,
        media_session=media_session,
        extractor=FakeExtractor(error=requests.ReadTimeout("refresh failed")),
    )

    result = service.persist(history_snapshot())

    assert result.status == "fallback"
    first_uploaded_key = storage.put_calls[0][0]
    assert storage.delete_calls == [first_uploaded_key]


def test_persist_reuses_complete_existing_map_without_media_requests():
    existing = {
        SOURCE_IMAGE: "https://oss.example.test/extract/image.webp",
        SOURCE_VIDEO: "https://oss.example.test/extract/video.mp4",
    }
    media_session = FakeMediaSession()
    storage = FakeStorage()
    service = ExtractAssetPersistenceService(
        storage=storage,
        media_session=media_session,
        extractor=FakeExtractor(),
    )

    result = service.persist(history_snapshot(existing_url_map=existing))

    assert result.status == "completed"
    assert result.url_map == existing
    assert media_session.requests == []
    assert storage.put_calls == []


def test_persist_rejects_non_http_media_urls():
    invalid_url = "file:///tmp/private.png"
    snapshot = ExtractHistorySnapshot(
        id="eh_invalid",
        account_id="acc1",
        source_url="https://example.test/post",
        platform="unknown",
        images=[media(invalid_url, "image")],
        videos=[],
    )
    service = ExtractAssetPersistenceService(
        storage=FakeStorage(),
        media_session=FakeMediaSession(),
        extractor=FakeExtractor(error=requests.ReadTimeout("refresh failed")),
    )

    result = service.persist(snapshot)

    assert result.status == "fallback"
    assert result.url_map == {invalid_url: invalid_url}
    assert "HTTP or HTTPS" in result.error


def test_persist_rejects_oversized_media_from_stream(monkeypatch):
    monkeypatch.setattr(settings, "max_extract_media_bytes", 4)
    media_session = FakeMediaSession({SOURCE_IMAGE: FakeResponse(b"12345", "image/webp")})
    extractor = FakeExtractor(payload={"platform": "douyin", "images": [SOURCE_IMAGE], "videos": []})
    snapshot = ExtractHistorySnapshot(
        id="eh_large",
        account_id="acc1",
        source_url="https://example.test/post",
        platform="douyin",
        images=[media(SOURCE_IMAGE, "image")],
        videos=[],
    )
    storage = FakeStorage()
    service = ExtractAssetPersistenceService(storage=storage, media_session=media_session, extractor=extractor)

    result = service.persist(snapshot)

    assert result.status == "fallback"
    assert "exceeds" in result.error
    assert storage.put_calls == []
