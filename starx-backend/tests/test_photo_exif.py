import base64
import asyncio
from datetime import UTC, datetime
from struct import pack, unpack
from types import SimpleNamespace
from zlib import crc32, compress

import piexif

from app.services.workflow.workflows.photo_exif import (
    PNG_SIGNATURE,
    create_photo_parameters,
    embed_photo_exif,
)
from app.services.workflow.workflows.generated_image_persistence import (
    persist_generated_image_result,
)


JPEG_1X1 = base64.b64decode(
    "/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAP//////////////////////////////////////////////"
    "////////////////////////////////////////"
    "2wBDAf//////////////////////////////////////////////////////////////////////////////////////"
    "wAARCAABAAEDASIAAhEBAxEB/8QAFQABAQAAAAAAAAAAAAAAAAAAAAf/xAAUEAEAAAAAAAAAAAAAAAAAAAAA/"
    "9oADAMBAAIQAxAAAAF//8QAFBABAAAAAAAAAAAAAAAAAAAAAP/aAAgBAQABBQJ//8QAFBEBAAAAAAAAAAAAAAAAAAAAAP/"
    "aAAgBAwEBPwF//8QAFBEBAAAAAAAAAAAAAAAAAAAAAP/aAAgBAgEBPwF//8QAFBABAAAAAAAAAAAAAAAAAAAAAP/"
    "aAAgBAQAGPwJ//8QAFBABAAAAAAAAAAAAAAAAAAAAAP/aAAgBAQABPyF//9oADAMBAAIAAwAAABD/"
    "xAAUEQEAAAAAAAAAAAAAAAAAAAAA/9oACAEDAQE/EB//xAAUEQEAAAAAAAAAAAAAAAAAAAAA/9oACAECAQE/EB/"
    "/xAAUEAEAAAAAAAAAAAAAAAAAAAAA/9oACAEBAAE/EB//2Q=="
)

WEBP_1X1 = base64.b64decode(
    "UklGRhoAAABXRUJQVlA4TA0AAAAvAAAAEAcQERGIiP4HAA=="
)


def _png_chunk(chunk_type: bytes, payload: bytes) -> bytes:
    checksum = crc32(payload, crc32(chunk_type)) & 0xFFFFFFFF
    return pack(">I", len(payload)) + chunk_type + payload + pack(">I", checksum)


def _png_1x1() -> bytes:
    ihdr = pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    return (
        PNG_SIGNATURE
        + _png_chunk(b"IHDR", ihdr)
        + _png_chunk(b"IDAT", compress(b"\x00\xff\xff\xff"))
        + _png_chunk(b"IEND", b"")
    )


def _png_exif_bytes(data: bytes) -> bytes:
    offset = len(PNG_SIGNATURE)
    while offset < len(data):
        length = unpack(">I", data[offset : offset + 4])[0]
        chunk_type = data[offset + 4 : offset + 8]
        payload = data[offset + 8 : offset + 8 + length]
        if chunk_type == b"eXIf":
            return b"Exif\x00\x00" + payload
        offset += 12 + length
    raise AssertionError("PNG did not contain an eXIf chunk")


def _parameters():
    return create_photo_parameters(
        stable_key="wf_test:0",
        prompt="上海外滩夜景人像",
        captured_at=datetime(2026, 7, 29, 8, 30, tzinfo=UTC),
    )


def _assert_expected_exif(
    exif_bytes: bytes,
    expected_time: bytes | None = b"2026:07:29 16:30:00",
) -> None:
    metadata = piexif.load(exif_bytes)
    assert metadata["0th"][piexif.ImageIFD.Make]
    assert metadata["0th"][piexif.ImageIFD.Model]
    if expected_time is not None:
        assert metadata["Exif"][piexif.ExifIFD.DateTimeOriginal] == expected_time
    else:
        assert metadata["Exif"][piexif.ExifIFD.DateTimeOriginal]
    assert metadata["Exif"][piexif.ExifIFD.LensModel]
    assert metadata["Exif"][piexif.ExifIFD.FocalLength]
    assert metadata["Exif"][piexif.ExifIFD.FNumber]
    assert metadata["Exif"][piexif.ExifIFD.ExposureTime]
    assert metadata["Exif"][piexif.ExifIFD.ISOSpeedRatings]
    assert metadata["GPS"][piexif.GPSIFD.GPSLatitudeRef] == b"N"
    assert metadata["GPS"][piexif.GPSIFD.GPSLongitudeRef] == b"E"


def test_photo_parameters_are_stable_and_prompt_location_aware():
    first = _parameters()
    second = _parameters()

    assert first == second
    assert first.city == "上海"
    assert first.location_name == "外滩"
    assert first.latitude == 31.24
    assert first.longitude == 121.49


def test_embed_photo_exif_in_png_without_changing_pixel_chunks():
    original = _png_1x1()

    embedded = embed_photo_exif(original, "image/png", _parameters())

    assert embedded.startswith(PNG_SIGNATURE)
    assert b"eXIf" in embedded
    _assert_expected_exif(_png_exif_bytes(embedded))


def test_embed_photo_exif_in_jpeg():
    embedded = embed_photo_exif(JPEG_1X1, "image/jpeg", _parameters())

    assert embedded.startswith(b"\xff\xd8")
    _assert_expected_exif(embedded)


def test_embed_photo_exif_in_webp():
    embedded = embed_photo_exif(WEBP_1X1, "image/webp", _parameters())

    assert embedded.startswith(b"RIFF")
    assert b"EXIF" in embedded
    _assert_expected_exif(embedded)


def test_persist_generated_image_uploads_exif_bytes_and_records_parameters():
    png_bytes = _png_1x1()
    encoded = base64.b64encode(png_bytes).decode("ascii")

    class Storage:
        uploaded: tuple[str, bytes, str] | None = None

        def put_bytes(self, key: str, data: bytes, content_type: str) -> str:
            self.uploaded = (key, data, content_type)
            return f"https://oss.example.test/{key}"

    storage = Storage()
    record = SimpleNamespace(
        id="wf_test",
        account_id="acc_test",
        prompt="上海外滩夜景人像",
    )

    asset, payload = asyncio.run(
        persist_generated_image_result(
            record,
            {"b64_json": encoded},
            0,
            storage,
        )
    )

    assert storage.uploaded is not None
    key, uploaded_bytes, content_type = storage.uploaded
    assert key.endswith(".png")
    assert content_type == "image/png"
    _assert_expected_exif(_png_exif_bytes(uploaded_bytes), expected_time=None)
    assert asset.meta["photoParameters"]["city"] == "上海"
    assert asset.meta["photoParameters"]["cameraModel"]
    assert payload["url"].startswith("https://oss.example.test/")
