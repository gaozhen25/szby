"""Generate plausible photo parameters and embed them as EXIF metadata."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from hashlib import sha256
from io import BytesIO
from struct import pack, unpack
from typing import Any
from zoneinfo import ZoneInfo
from zlib import crc32

import piexif


@dataclass(frozen=True)
class CameraPreset:
    make: str
    model: str
    lens_make: str
    lens_model: str
    focal_length_mm: int
    aperture: float
    exposure_time: tuple[int, int]
    iso: int


@dataclass(frozen=True)
class LocationPreset:
    name: str
    city: str
    country: str
    latitude: float
    longitude: float


@dataclass(frozen=True)
class PhotoParameters:
    camera_make: str
    camera_model: str
    lens_make: str
    lens_model: str
    focal_length_mm: int
    aperture: float
    exposure_time: str
    iso: int
    captured_at: str
    location_name: str
    city: str
    country: str
    latitude: float
    longitude: float

    def to_meta(self) -> dict[str, Any]:
        """Return the camelCase representation stored with the generation asset."""

        values = asdict(self)
        return {
            "cameraMake": values["camera_make"],
            "cameraModel": values["camera_model"],
            "lensMake": values["lens_make"],
            "lensModel": values["lens_model"],
            "focalLengthMm": values["focal_length_mm"],
            "aperture": values["aperture"],
            "exposureTime": values["exposure_time"],
            "iso": values["iso"],
            "capturedAt": values["captured_at"],
            "locationName": values["location_name"],
            "city": values["city"],
            "country": values["country"],
            "latitude": values["latitude"],
            "longitude": values["longitude"],
        }


CAMERA_PRESETS = (
    CameraPreset(
        make="SONY",
        model="ILCE-7M4",
        lens_make="Sony",
        lens_model="FE 35mm F1.4 GM",
        focal_length_mm=35,
        aperture=2.8,
        exposure_time=(1, 250),
        iso=200,
    ),
    CameraPreset(
        make="Canon",
        model="Canon EOS R5",
        lens_make="Canon",
        lens_model="RF50mm F1.8 STM",
        focal_length_mm=50,
        aperture=2.8,
        exposure_time=(1, 200),
        iso=100,
    ),
    CameraPreset(
        make="NIKON CORPORATION",
        model="NIKON Z 8",
        lens_make="NIKON",
        lens_model="NIKKOR Z 24-70mm f/2.8 S",
        focal_length_mm=50,
        aperture=4.0,
        exposure_time=(1, 160),
        iso=200,
    ),
    CameraPreset(
        make="FUJIFILM",
        model="X-T5",
        lens_make="FUJIFILM",
        lens_model="XF35mmF1.4 R",
        focal_length_mm=35,
        aperture=2.0,
        exposure_time=(1, 250),
        iso=320,
    ),
)

LOCATION_PRESETS = (
    LocationPreset("外滩", "上海", "中国", 31.2400, 121.4900),
    LocationPreset("三里屯", "北京", "中国", 39.9365, 116.4559),
    LocationPreset("珠江新城", "广州", "中国", 23.1194, 113.3215),
    LocationPreset("南山", "深圳", "中国", 22.5333, 113.9304),
    LocationPreset("太古里", "成都", "中国", 30.6544, 104.0817),
    LocationPreset("西湖", "杭州", "中国", 30.2469, 120.1487),
)

LOCATION_KEYWORDS = {
    "上海": LOCATION_PRESETS[0],
    "外滩": LOCATION_PRESETS[0],
    "北京": LOCATION_PRESETS[1],
    "三里屯": LOCATION_PRESETS[1],
    "广州": LOCATION_PRESETS[2],
    "珠江新城": LOCATION_PRESETS[2],
    "深圳": LOCATION_PRESETS[3],
    "南山": LOCATION_PRESETS[3],
    "成都": LOCATION_PRESETS[4],
    "太古里": LOCATION_PRESETS[4],
    "杭州": LOCATION_PRESETS[5],
    "西湖": LOCATION_PRESETS[5],
}

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def create_photo_parameters(
    *,
    stable_key: str,
    prompt: str,
    captured_at: datetime,
) -> PhotoParameters:
    """Create a deterministic, internally consistent set of photo parameters."""

    digest = sha256(stable_key.encode("utf-8")).digest()
    camera = CAMERA_PRESETS[digest[0] % len(CAMERA_PRESETS)]
    location = _location_for_prompt(prompt, digest[1])
    local_time = captured_at.astimezone(ZoneInfo("Asia/Shanghai"))
    exposure_numerator, exposure_denominator = camera.exposure_time
    return PhotoParameters(
        camera_make=camera.make,
        camera_model=camera.model,
        lens_make=camera.lens_make,
        lens_model=camera.lens_model,
        focal_length_mm=camera.focal_length_mm,
        aperture=camera.aperture,
        exposure_time=f"{exposure_numerator}/{exposure_denominator}",
        iso=camera.iso,
        captured_at=local_time.isoformat(timespec="seconds"),
        location_name=location.name,
        city=location.city,
        country=location.country,
        latitude=location.latitude,
        longitude=location.longitude,
    )


def embed_photo_exif(
    data: bytes,
    content_type: str,
    parameters: PhotoParameters,
) -> bytes:
    """Embed EXIF without altering image pixels."""

    exif_bytes = _build_exif(parameters)
    if content_type in {"image/jpeg", "image/webp"}:
        output = BytesIO()
        piexif.insert(exif_bytes, data, output)
        return output.getvalue()
    if content_type == "image/png":
        return _insert_png_exif(data, exif_bytes)
    raise ValueError(f"unsupported EXIF image content type: {content_type}")


def _location_for_prompt(prompt: str, fallback_selector: int) -> LocationPreset:
    normalized = str(prompt or "")
    for keyword, location in LOCATION_KEYWORDS.items():
        if keyword in normalized:
            return location
    return LOCATION_PRESETS[fallback_selector % len(LOCATION_PRESETS)]


def _build_exif(parameters: PhotoParameters) -> bytes:
    captured_at = datetime.fromisoformat(parameters.captured_at)
    exif_datetime = captured_at.strftime("%Y:%m:%d %H:%M:%S")
    offset = captured_at.strftime("%z")
    offset_time = f"{offset[:3]}:{offset[3:]}" if offset else ""
    latitude_ref, latitude = _gps_coordinate(parameters.latitude, "N", "S")
    longitude_ref, longitude = _gps_coordinate(parameters.longitude, "E", "W")
    exposure_parts = parameters.exposure_time.split("/", 1)

    zeroth_ifd: dict[int, Any] = {
        piexif.ImageIFD.Make: parameters.camera_make,
        piexif.ImageIFD.Model: parameters.camera_model,
        piexif.ImageIFD.DateTime: exif_datetime,
        piexif.ImageIFD.ImageDescription: (
            f"GPS {parameters.latitude:.6f}, {parameters.longitude:.6f}"
        ),
    }
    exif_ifd: dict[int, Any] = {
        piexif.ExifIFD.DateTimeOriginal: exif_datetime,
        piexif.ExifIFD.DateTimeDigitized: exif_datetime,
        piexif.ExifIFD.ExposureTime: (int(exposure_parts[0]), int(exposure_parts[1])),
        piexif.ExifIFD.FNumber: _decimal_rational(parameters.aperture),
        piexif.ExifIFD.ISOSpeedRatings: parameters.iso,
        piexif.ExifIFD.FocalLength: (parameters.focal_length_mm, 1),
        piexif.ExifIFD.FocalLengthIn35mmFilm: parameters.focal_length_mm,
        piexif.ExifIFD.LensMake: parameters.lens_make,
        piexif.ExifIFD.LensModel: parameters.lens_model,
        piexif.ExifIFD.ExposureProgram: 3,
        piexif.ExifIFD.MeteringMode: 5,
        piexif.ExifIFD.Flash: 16,
        piexif.ExifIFD.WhiteBalance: 0,
    }
    if offset_time and hasattr(piexif.ExifIFD, "OffsetTimeOriginal"):
        exif_ifd[piexif.ExifIFD.OffsetTimeOriginal] = offset_time

    utc_time = captured_at.astimezone(UTC)
    gps_ifd: dict[int, Any] = {
        piexif.GPSIFD.GPSVersionID: (2, 3, 0, 0),
        piexif.GPSIFD.GPSLatitudeRef: latitude_ref,
        piexif.GPSIFD.GPSLatitude: latitude,
        piexif.GPSIFD.GPSLongitudeRef: longitude_ref,
        piexif.GPSIFD.GPSLongitude: longitude,
        piexif.GPSIFD.GPSDateStamp: utc_time.strftime("%Y:%m:%d"),
        piexif.GPSIFD.GPSTimeStamp: (
            (utc_time.hour, 1),
            (utc_time.minute, 1),
            (utc_time.second, 1),
        ),
    }
    return piexif.dump(
        {
            "0th": zeroth_ifd,
            "Exif": exif_ifd,
            "GPS": gps_ifd,
            "1st": {},
            "thumbnail": None,
        }
    )


def _decimal_rational(value: float) -> tuple[int, int]:
    return int(round(value * 10)), 10


def _gps_coordinate(
    value: float,
    positive_ref: str,
    negative_ref: str,
) -> tuple[str, tuple[tuple[int, int], tuple[int, int], tuple[int, int]]]:
    absolute = abs(value)
    degrees = int(absolute)
    minutes_value = (absolute - degrees) * 60
    minutes = int(minutes_value)
    seconds = round((minutes_value - minutes) * 60, 6)
    return (
        positive_ref if value >= 0 else negative_ref,
        ((degrees, 1), (minutes, 1), (int(round(seconds * 1_000_000)), 1_000_000)),
    )


def _insert_png_exif(data: bytes, exif_bytes: bytes) -> bytes:
    if not data.startswith(PNG_SIGNATURE):
        raise ValueError("generated image is not a valid PNG")

    raw_exif = exif_bytes[6:] if exif_bytes.startswith(b"Exif\x00\x00") else exif_bytes
    chunks: list[bytes] = []
    offset = len(PNG_SIGNATURE)
    inserted = False
    saw_ihdr = False
    saw_iend = False

    while offset < len(data):
        if offset + 12 > len(data):
            raise ValueError("generated PNG contains a truncated chunk")
        length = unpack(">I", data[offset : offset + 4])[0]
        chunk_end = offset + 12 + length
        if chunk_end > len(data):
            raise ValueError("generated PNG contains an invalid chunk length")
        chunk_type = data[offset + 4 : offset + 8]
        chunk = data[offset:chunk_end]
        offset = chunk_end

        if chunk_type == b"IHDR":
            saw_ihdr = True
            chunks.append(chunk)
            chunks.append(_png_chunk(b"eXIf", raw_exif))
            inserted = True
            continue
        if chunk_type == b"eXIf":
            continue
        chunks.append(chunk)
        if chunk_type == b"IEND":
            saw_iend = True
            break

    if not saw_ihdr or not saw_iend or not inserted:
        raise ValueError("generated image is not a complete PNG")
    return PNG_SIGNATURE + b"".join(chunks)


def _png_chunk(chunk_type: bytes, payload: bytes) -> bytes:
    checksum = crc32(chunk_type)
    checksum = crc32(payload, checksum) & 0xFFFFFFFF
    return pack(">I", len(payload)) + chunk_type + payload + pack(">I", checksum)
