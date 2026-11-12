import pytest

from app.services.uploads.policy import validate_file_declaration


@pytest.mark.parametrize(
    ("filename", "content_type"),
    [
        ("background.jpg", "image/jpeg"),
        ("background.mp4", "video/mp4"),
        ("bubble.png", "image/png"),
        ("music.mp3", "audio/mpeg"),
        ("music.m4a", "audio/mp4"),
        ("music.wav", "audio/wav"),
    ],
)
def test_digital_human_editing_asset_accepts_supported_media(filename, content_type):
    _, clean_content_type, suffix = validate_file_declaration(
        purpose="digital_human_editing_asset",
        filename=filename,
        content_type=content_type,
        size_bytes=1024,
    )

    assert clean_content_type == content_type
    assert suffix == f".{filename.rsplit('.', 1)[1]}"


def test_digital_human_editing_asset_rejects_unsupported_files():
    with pytest.raises(ValueError, match="not allowed"):
        validate_file_declaration(
            purpose="digital_human_editing_asset",
            filename="payload.html",
            content_type="text/html",
            size_bytes=1024,
        )


@pytest.mark.parametrize(
    ("filename", "content_type"),
    [
        ("music.mp3", "audio/mpeg"),
        ("music.m4a", "audio/mp4"),
        ("music.aac", "audio/aac"),
        ("music.wav", "audio/wav"),
        ("music.ogg", "audio/ogg"),
        ("music.mp4", "video/mp4"),
    ],
)
def test_digital_human_background_music_accepts_audio_and_mp4(
    filename,
    content_type,
):
    _, clean_content_type, _ = validate_file_declaration(
        purpose="digital_human_background_music",
        filename=filename,
        content_type=content_type,
        size_bytes=1024,
    )

    assert clean_content_type == content_type


def test_digital_human_background_music_rejects_unsupported_video_container():
    with pytest.raises(ValueError, match="not allowed"):
        validate_file_declaration(
            purpose="digital_human_background_music",
            filename="music.mov",
            content_type="video/quicktime",
            size_bytes=1024,
        )
