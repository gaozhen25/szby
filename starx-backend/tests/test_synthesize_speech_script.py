import asyncio
from pathlib import Path
from typing import Any

import pytest

from scripts.synthesize_speech import (
    parse_extra_body,
    read_copy,
    resolve_format,
    synthesize_to_file,
)


class FakeSynthesizer:
    def __init__(self, audio: bytes = b"audio-bytes") -> None:
        self.audio = audio
        self.request: dict[str, Any] = {}

    async def speech_synthesis(self, **kwargs: Any) -> bytes:
        self.request = kwargs
        return self.audio


def test_read_copy_from_text_or_file(tmp_path: Path) -> None:
    copy_file = tmp_path / "copy.txt"
    copy_file.write_text("  文件文案  ", encoding="utf-8")

    assert read_copy(text="  参数文案 ", input_path=None) == "参数文案"
    assert read_copy(text=None, input_path=copy_file) == "文件文案"


def test_parse_extra_body_requires_json_object() -> None:
    assert parse_extra_body("") is None
    assert parse_extra_body('{"emotion": "happy"}') == {"emotion": "happy"}

    with pytest.raises(ValueError, match="JSON 对象"):
        parse_extra_body('["happy"]')


def test_resolve_format_prefers_explicit_value() -> None:
    assert resolve_format("wav", Path("voice.mp3")) == "wav"
    assert resolve_format(None, Path("voice.flac")) == "flac"
    assert resolve_format(None, Path("voice.bin")) == "mp3"


def test_synthesize_to_file_passes_options_and_writes_audio(tmp_path: Path) -> None:
    synthesizer = FakeSynthesizer()
    output = tmp_path / "nested" / "voice.mp3"

    byte_count = asyncio.run(
        synthesize_to_file(
            synthesizer,
            text="你好",
            output_path=output,
            voice="female-shaonv",
            model="speech-model",
            response_format="mp3",
            speed=1.2,
            base_url="https://tts.example.test",
            token="secret",
            extra_body={"emotion": "happy"},
            force=False,
        )
    )

    assert byte_count == len(b"audio-bytes")
    assert output.read_bytes() == b"audio-bytes"
    assert synthesizer.request == {
        "model": "speech-model",
        "text": "你好",
        "voice": "female-shaonv",
        "response_format": "mp3",
        "speed": 1.2,
        "base_url": "https://tts.example.test",
        "token": "secret",
        "extra_body": {"emotion": "happy"},
    }


def test_synthesize_to_file_does_not_overwrite_without_force(tmp_path: Path) -> None:
    output = tmp_path / "voice.mp3"
    output.write_bytes(b"original")
    synthesizer = FakeSynthesizer()

    with pytest.raises(FileExistsError, match="--force"):
        asyncio.run(
            synthesize_to_file(
                synthesizer,
                text="你好",
                output_path=output,
                voice="voice",
                model=None,
                response_format="mp3",
                speed=1.0,
                base_url=None,
                token=None,
                extra_body=None,
                force=False,
            )
        )

    assert synthesizer.request == {}
    assert output.read_bytes() == b"original"
