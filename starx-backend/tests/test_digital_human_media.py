import asyncio
import subprocess
import wave
from array import array
from math import pi, sin

import pytest

from app.services.digital_human import media
from app.services.digital_human.reconciler import _editing_gain


def test_missing_ffprobe_returns_actionable_deployment_error(monkeypatch):
    monkeypatch.setattr(media.settings, "digital_human_ffprobe_path", "")
    monkeypatch.setattr(media.shutil, "which", lambda _name: None)

    with pytest.raises(RuntimeError, match="安装 ffmpeg 系统包"):
        media.resolve_media_executable("ffprobe")


def test_configured_ffmpeg_path_is_resolved(monkeypatch):
    monkeypatch.setattr(media.settings, "digital_human_ffmpeg_path", "/opt/ffmpeg")
    monkeypatch.setattr(
        media.shutil,
        "which",
        lambda name: "/opt/ffmpeg" if name == "/opt/ffmpeg" else None,
    )

    assert media.resolve_media_executable("ffmpeg") == "/opt/ffmpeg"


def test_inspect_and_prepare_background_music(tmp_path):
    source = tmp_path / "source.wav"
    prepared = tmp_path / "prepared.wav"
    with wave.open(str(source), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(24000)
        samples = array(
            "h",
            (
                int(8192 * sin(2 * pi * 440 * index / 24000))
                for index in range(24000)
            ),
        )
        audio.writeframes(samples.tobytes())

    metadata = asyncio.run(media.inspect_audio(source))
    loudness = asyncio.run(media.measure_audio_loudness(source))
    asyncio.run(
        media.prepare_background_music(
            source,
            prepared,
            max_duration_seconds=0.5,
        )
    )
    prepared_metadata = asyncio.run(media.inspect_audio(prepared))

    assert metadata["sampleRate"] == 24000
    assert metadata["channels"] == 1
    assert loudness["integratedLoudnessLufs"] < 0
    assert loudness["truePeakDbtp"] < 0
    assert prepared_metadata["sampleRate"] == 48000
    assert prepared_metadata["channels"] == 2
    assert prepared_metadata["codec"] == "pcm_s16le"
    assert prepared_metadata["durationSeconds"] == pytest.approx(0.5, abs=0.01)


def test_prepare_background_music_extracts_audio_from_mp4(tmp_path):
    source = tmp_path / "music-video.mp4"
    prepared = tmp_path / "prepared.wav"
    subprocess.run(
        [
            media.resolve_media_executable("ffmpeg"),
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=black:s=320x240:r=25",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:sample_rate=24000",
            "-t",
            "0.6",
            "-c:v",
            "mpeg4",
            "-c:a",
            "aac",
            str(source),
        ],
        check=True,
        capture_output=True,
    )

    source_metadata = asyncio.run(media.inspect_audio(source))
    asyncio.run(
        media.prepare_background_music(
            source,
            prepared,
            max_duration_seconds=0.4,
        )
    )
    prepared_metadata = asyncio.run(media.inspect_audio(prepared))

    assert source_metadata["codec"] == "aac"
    assert prepared_metadata["codec"] == "pcm_s16le"
    assert prepared_metadata["durationSeconds"] == pytest.approx(0.4, abs=0.02)


def test_editing_gain_uses_linear_values_and_converts_legacy_db_values():
    assert _editing_gain(None) == 0.1
    assert _editing_gain(0.25) == 0.25
    assert _editing_gain(-20) == pytest.approx(0.1)
    assert _editing_gain(20) == 10.0
