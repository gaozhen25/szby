import asyncio
import base64
import json

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from message_adapter.platforms.douyin.images import decrypt_im_image, openable_image_url, upload_image
from message_adapter.platforms.douyin.protocol import im_uplink_content
from message_adapter.services import LocalAdapterService
from message_adapter.services.local import HttpRequest


JPEG = b"\xff\xd8\xff" + b"picture-bytes"


def _encrypted(plain: bytes, key: bytes) -> tuple[bytes, str]:
    iv = b"0123456789ab"
    return iv + AESGCM(key).encrypt(iv, plain, None), key.hex()


def test_plain_picture_url_is_left_unchanged(monkeypatch):
    def fail_download(url: str) -> bytes:
        raise AssertionError(url)

    monkeypatch.setattr("message_adapter.platforms.douyin.images._download", fail_download)
    url, size = openable_image_url({"resource_url": {"url_list": ["https://example.test/photo.jpg"]}}, "https://example.test/photo.jpg")
    assert url == "https://example.test/photo.jpg"
    assert size is None


def test_encrypted_picture_is_published_as_a_public_oss_url(monkeypatch):
    key = AESGCM.generate_key(bit_length=256)
    blob, skey = _encrypted(JPEG, key)
    published: list[bytes] = []

    def upload(data: bytes) -> str:
        published.append(data)
        return "https://oss.humanlike.life/edge/image/2026/09/22/abc.jpg"

    url, size = openable_image_url(
        {"resource_url": {"skey": skey, "url_list": ["https://p9-sign.douyinpic.com/tos/a~tplv-x-get:.image"]}},
        "https://p9-sign.douyinpic.com/tos/a~tplv-x-get:.image",
        fetch=lambda _url: blob,
        upload=upload,
    )

    assert url == "https://oss.humanlike.life/edge/image/2026/09/22/abc.jpg"
    assert "127.0.0.1" not in url
    assert size == len(JPEG)
    assert published == [JPEG]
    assert decrypt_im_image(blob, skey) == JPEG


def test_missing_key_keeps_the_cdn_url(monkeypatch):
    monkeypatch.setattr("message_adapter.platforms.douyin.images._download", lambda _url: b"\x22\x26not-an-image")
    url, size = openable_image_url({}, "https://p9-sign.douyinpic.com/tos/a~tplv-x-get:.image")
    assert url.endswith("~tplv-x-get:.image")
    assert size is None


def test_inline_preview_is_uploaded_when_decrypt_fails():
    url, size = openable_image_url(
        {"inline_pic": base64.b64encode(JPEG).decode(), "resource_url": {"skey": "ab" * 32}},
        "https://p9-sign.douyinpic.com/tos/a~tplv-x-get:.image",
        fetch=lambda _url: b"",
        upload=lambda data: "https://oss.humanlike.life/edge/image/preview.jpg" if data == JPEG else "",
    )
    assert url == "https://oss.humanlike.life/edge/image/preview.jpg"
    assert size == len(JPEG)


def test_upload_image_returns_the_public_object_url(monkeypatch):
    monkeypatch.setenv("OSS_ACCESS_KEY_ID", "test-key")
    monkeypatch.setenv("OSS_ACCESS_KEY_SECRET", "test-secret")
    monkeypatch.setenv("OSS_BUCKET", "szby")
    monkeypatch.setenv("OSS_REGION", "cn-hangzhou")
    monkeypatch.setenv("OSS_ENDPOINT", "oss.humanlike.life")
    monkeypatch.setenv("OSS_UPLOAD_DIR", "edge")
    captured: dict[str, str] = {}

    class Response:
        status_code = 200

    def fake_put(url, data, headers, timeout):
        captured["url"] = url
        captured["authorization"] = headers["Authorization"]
        assert data == JPEG
        assert timeout == 30
        return Response()

    monkeypatch.setattr("message_adapter.platforms.douyin.images.requests.put", fake_put)
    public = upload_image(JPEG)
    assert public.startswith("https://oss.humanlike.life/edge/image/")
    assert public.endswith(".jpg")
    assert captured["url"].startswith("https://szby.oss-cn-hangzhou.aliyuncs.com/edge/image/")
    assert captured["authorization"].startswith("OSS test-key:")
    assert "test-secret" not in captured["url"]
    assert "test-secret" not in public


def test_failed_oss_upload_does_not_publish_a_localhost_url():
    url, size = openable_image_url(
        {"resource_url": {"skey": "ab" * 32}},
        "https://p9-sign.douyinpic.com/tos/a~tplv-x-get:.image",
        fetch=lambda _url: JPEG,
        upload=lambda _data: "",
    )
    assert url.endswith("~tplv-x-get:.image")
    assert "127.0.0.1" not in url
    assert size is None


def test_uplink_image_uses_the_decrypted_url(monkeypatch):
    key = AESGCM.generate_key(bit_length=256)
    blob, skey = _encrypted(JPEG, key)
    monkeypatch.setattr("message_adapter.platforms.douyin.images._download", lambda _url: blob)
    monkeypatch.setattr(
        "message_adapter.platforms.douyin.images.upload_image",
        lambda data: "https://oss.humanlike.life/edge/image/2026/09/22/abc.jpg" if data == JPEG else "",
    )
    payload = im_uplink_content(
        {
            "message_type": 27,
            "content": json.dumps(
                {
                    "resource_url": {
                        "skey": skey,
                        "url_list": ["https://p9-sign.douyinpic.com/tos/a~tplv-x-get:.image"],
                        "width": 200,
                        "height": 300,
                    }
                }
            ),
        }
    )
    assert payload is not None
    picture = payload["content"]["picture"]["sourcePicture"]
    assert picture["url"] == "https://oss.humanlike.life/edge/image/2026/09/22/abc.jpg"
    assert picture["width"] == 200
    assert picture["height"] == 300
    assert picture["size"] == len(JPEG)


def test_control_page_serves_decrypted_douyin_image(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    name = "a" * 32 + ".jpg"
    media = tmp_path / "adapter_data" / "douyin_media"
    media.mkdir(parents=True)
    (media / name).write_bytes(JPEG)

    async def scenario():
        service = LocalAdapterService(dotenv=str(tmp_path / "missing.env"))
        response = await service.dispatch(HttpRequest("GET", f"/media/douyin/{name}", {}))
        missing = await service.dispatch(HttpRequest("GET", "/media/douyin/../secrets.jpg", {}))
        assert response.status == 200
        assert response.body == JPEG
        assert response.content_type == "image/jpeg"
        assert ("Access-Control-Allow-Origin", "*") in response.extra_headers
        assert missing.status == 404

        class Writer:
            def __init__(self):
                self.buffer = bytearray()

            def write(self, data):
                self.buffer.extend(data)

            async def drain(self):
                return None

        writer = Writer()
        await service._write_response(writer, response)
        assert b"Access-Control-Allow-Origin: *\r\n" in writer.buffer
        assert b"Content-Type: image/jpeg\r\n" in writer.buffer

    asyncio.run(scenario())
