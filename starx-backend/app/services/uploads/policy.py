from dataclasses import dataclass
from pathlib import Path

from app.core.config import settings


@dataclass(frozen=True)
class UploadPolicy:
    content_types: dict[str, frozenset[str]]
    max_size_bytes: int
    account_required: bool = True


IMAGE_TYPES = {
    "image/jpeg": frozenset({".jpg", ".jpeg"}),
    "image/png": frozenset({".png"}),
    "image/webp": frozenset({".webp"}),
}

DIGITAL_HUMAN_EDITING_ASSET_TYPES = {
    **IMAGE_TYPES,
    "video/mp4": frozenset({".mp4"}),
    "video/quicktime": frozenset({".mov"}),
    "audio/mpeg": frozenset({".mp3"}),
    "audio/mp4": frozenset({".m4a"}),
    "audio/aac": frozenset({".aac"}),
    "audio/wav": frozenset({".wav"}),
    "audio/x-wav": frozenset({".wav"}),
    "audio/ogg": frozenset({".ogg"}),
}

DIGITAL_HUMAN_BACKGROUND_MUSIC_TYPES = {
    # MP4 可作为背景音乐来源；合成前会由 FFmpeg 校验音轨并转为 WAV。
    "video/mp4": frozenset({".mp4"}),
    "audio/mpeg": frozenset({".mp3"}),
    "audio/mp4": frozenset({".m4a"}),
    "audio/aac": frozenset({".aac"}),
    "audio/wav": frozenset({".wav"}),
    "audio/x-wav": frozenset({".wav"}),
    "audio/ogg": frozenset({".ogg"}),
}


def policy_for(purpose: str) -> UploadPolicy:
    policies = {
        "publish_video": UploadPolicy(
            {"video/mp4": frozenset({".mp4"})},
            settings.max_extract_media_bytes,
        ),
        "publish_image": UploadPolicy(IMAGE_TYPES, settings.max_upload_image_bytes),
        "knowledge_base_image": UploadPolicy(
            IMAGE_TYPES,
            settings.max_upload_image_bytes,
            account_required=False,
        ),
        "generation_reference": UploadPolicy(IMAGE_TYPES, settings.max_upload_image_bytes),
        "generation_material": UploadPolicy(IMAGE_TYPES, settings.max_upload_image_bytes),
        "person_replacement_target": UploadPolicy(IMAGE_TYPES, settings.max_upload_image_bytes),
        "person_replacement_person": UploadPolicy(IMAGE_TYPES, settings.max_upload_image_bytes),
        "digital_human_source": UploadPolicy(
            {
                "video/mp4": frozenset({".mp4"}),
                "video/quicktime": frozenset({".mov"}),
            },
            settings.digital_human_max_source_video_bytes,
        ),
        "digital_human_editing_asset": UploadPolicy(
            DIGITAL_HUMAN_EDITING_ASSET_TYPES,
            settings.digital_human_max_source_video_bytes,
        ),
        "digital_human_background_music": UploadPolicy(
            DIGITAL_HUMAN_BACKGROUND_MUSIC_TYPES,
            settings.digital_human_max_source_video_bytes,
        ),
    }
    try:
        return policies[purpose]
    except KeyError as exc:
        raise ValueError(f"unsupported upload purpose: {purpose}") from exc


def validate_file_declaration(
    *,
    purpose: str,
    filename: str,
    content_type: str,
    size_bytes: int,
) -> tuple[UploadPolicy, str, str]:
    policy = policy_for(purpose)
    clean_content_type = str(content_type or "").strip().lower()
    safe_filename = Path(str(filename or "")).name
    suffix = Path(safe_filename).suffix.lower()
    if not safe_filename or suffix not in policy.content_types.get(clean_content_type, frozenset()):
        raise ValueError("file extension and content type are not allowed for this upload purpose")
    if size_bytes <= 0:
        raise ValueError("file size must be greater than zero")
    if size_bytes > policy.max_size_bytes:
        raise ValueError(f"file exceeds the {policy.max_size_bytes}-byte upload limit")
    return policy, clean_content_type, suffix
