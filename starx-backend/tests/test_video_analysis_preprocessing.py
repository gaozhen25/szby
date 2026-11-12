import shutil
import subprocess
from pathlib import Path

import pytest

from app.services.extract_service.video_analysis_preprocessing import (
    LocalVideoAnalysisSegment,
    VideoAnalysisPreprocessor,
)
from app.services.extract_service.video_audio_preprocessing import (
    LocalAudioSegment,
    VideoAudioPreprocessor,
    _build_waveform_segment_ranges,
    _parse_waveform_energy_samples,
    _parse_silence_intervals,
)


class RecordingStorage:
    def __init__(self):
        self.calls = []

    def put_file(self, key, path, content_type):  # noqa: ANN001
        self.calls.append((key, Path(path), content_type))
        return f"https://oss.example.test/{key}"


def test_preprocessor_keeps_short_video_as_single_source(monkeypatch, tmp_path):
    storage = RecordingStorage()
    service = VideoAnalysisPreprocessor(storage=storage)
    monkeypatch.setattr(
        "app.services.extract_service.video_analysis_preprocessing.shutil.which",
        lambda value: f"/usr/bin/{value}",
    )
    monkeypatch.setattr(service, "_download", lambda _url, _path: 1024)
    monkeypatch.setattr(service, "_probe_duration", lambda _path: 60)

    prepared = service.prepare("https://cdn.example.test/short.mp4", owner_id="acc1")

    assert prepared.segmented is False
    assert prepared.segments[0].url == "https://cdn.example.test/short.mp4"
    assert storage.calls == []


def test_preprocessor_uploads_long_video_segments(monkeypatch):
    storage = RecordingStorage()
    service = VideoAnalysisPreprocessor(storage=storage)
    monkeypatch.setattr(
        "app.services.extract_service.video_analysis_preprocessing.shutil.which",
        lambda value: f"/usr/bin/{value}",
    )
    monkeypatch.setattr(service, "_download", lambda _url, _path: 100 * 1024 * 1024)
    monkeypatch.setattr(service, "_probe_duration", lambda _path: 150)
    monkeypatch.setattr(
        service,
        "_segment",
        lambda _source, workspace, _duration: [
            LocalVideoAnalysisSegment(workspace / "segment-0000.mp4", 0, 90),
            LocalVideoAnalysisSegment(workspace / "segment-0001.mp4", 88, 62),
        ],
    )

    prepared = service.prepare(
        "https://cdn.example.test/long.mp4",
        source_url="https://example.test/post/1",
        owner_id="acc1",
    )

    assert prepared.segmented is True
    assert [segment.start_seconds for segment in prepared.segments] == [0, 88]
    assert [segment.duration_seconds for segment in prepared.segments] == [90, 62]
    assert len(storage.calls) == 2
    assert all(call[2] == "video/mp4" for call in storage.calls)


def test_preprocessor_extracts_audio_and_builds_absolute_timeline(monkeypatch):
    storage = RecordingStorage()
    service = VideoAudioPreprocessor(storage=storage)
    persistence_calls = []

    class LocalPersistence:
        def persist_downloaded(self, video_url, local_path, **kwargs):  # noqa: ANN001
            persistence_calls.append((video_url, Path(local_path), kwargs))
            return "https://oss.example.test/persisted-video.mp4"

    monkeypatch.setattr(
        "app.services.extract_service.video_audio_preprocessing.shutil.which",
        lambda value: f"/usr/bin/{value}",
    )
    monkeypatch.setattr(service, "_download", lambda _url, _path: 4096)
    monkeypatch.setattr(service, "_probe_duration", lambda _path: 35)

    def fake_extract(_source, output):  # noqa: ANN001
        output.touch()

    monkeypatch.setattr(service, "_extract_audio", fake_extract)
    monkeypatch.setattr(
        service,
        "_segment_audio",
        lambda _source, workspace, _duration: [
            LocalAudioSegment(workspace / "audio-segment-0000.mp3", 0, 8.6),
            LocalAudioSegment(workspace / "audio-segment-0001.mp3", 8.6, 14.7),
            LocalAudioSegment(workspace / "audio-segment-0002.mp3", 23.3, 11.7),
        ],
    )

    prepared = service.prepare(
        "https://cdn.example.test/video.mp4",
        source_url="https://example.test/post/1",
        owner_id="acc1",
        source_persistence=LocalPersistence(),
    )

    assert prepared.audio_url.endswith("/source-audio.mp3")
    assert prepared.video_url == "https://oss.example.test/persisted-video.mp4"
    assert len(persistence_calls) == 1
    assert [item.start_seconds for item in prepared.segments] == [0, 8.6, 23.3]
    assert [item.duration_seconds for item in prepared.segments] == [8.6, 14.7, 11.7]
    assert len(storage.calls) == 4
    assert all(call[2] == "audio/mpeg" for call in storage.calls)


def test_waveform_ranges_cut_at_silence_midpoints():
    ranges = _build_waveform_segment_ranges(
        140,
        [(20, 21), (58, 59), (90, 91), (119, 120)],
        min_segment_seconds=5,
        target_segment_seconds=60,
        search_seconds=15,
    )

    assert ranges == [(0.0, 58.5), (58.5, 119.5), (119.5, 140.0)]


def test_waveform_ranges_keep_whole_audio_without_silence():
    assert _build_waveform_segment_ranges(
        140,
        [],
        min_segment_seconds=5,
        target_segment_seconds=60,
        search_seconds=15,
    ) == [(0.0, 140.0)]


def test_waveform_ranges_use_lowest_energy_point_when_there_is_no_silence():
    ranges = _build_waveform_segment_ranges(
        140,
        [],
        energy_samples=[(48, -18), (57, -31), (69, -22), (108, -20), (118, -35)],
        min_segment_seconds=5,
        target_segment_seconds=60,
        search_seconds=15,
    )

    assert ranges == [(0.0, 57), (57, 118), (118, 140.0)]


def test_flash_fallback_builds_roughly_ninety_second_waveform_segments():
    ranges = _build_waveform_segment_ranges(
        285,
        [],
        energy_samples=[
            (75, -20), (88, -31), (105, -22),
            (165, -18), (178, -35), (195, -24),
            (245, -19), (268, -33), (280, -21),
        ],
        min_segment_seconds=5,
        target_segment_seconds=90,
        search_seconds=30,
    )

    assert ranges == [(0.0, 88), (88, 178), (178, 268), (268, 285.0)]
    assert max(end - start for start, end in ranges) <= 120


def test_waveform_ranges_can_skip_a_target_window_without_fixed_cut():
    ranges = _build_waveform_segment_ranges(
        190,
        [(118, 120)],
        min_segment_seconds=5,
        target_segment_seconds=60,
        search_seconds=15,
    )

    assert ranges == [(0.0, 119.0), (119.0, 190.0)]


def test_waveform_ranges_ignore_silence_that_would_create_tiny_fragments():
    ranges = _build_waveform_segment_ranges(
        140,
        [(0.5, 1.5), (60, 62), (138, 139)],
        min_segment_seconds=5,
        target_segment_seconds=60,
        search_seconds=15,
    )

    assert ranges == [(0.0, 61.0), (61.0, 140.0)]


def test_parse_ffmpeg_silencedetect_output():
    output = """
[silencedetect @ 0x1] silence_start: 8.2
[silencedetect @ 0x1] silence_end: 9.0 | silence_duration: 0.8
[silencedetect @ 0x1] silence_start: 22.8
[silencedetect @ 0x1] silence_end: 23.8 | silence_duration: 1.0
"""

    assert _parse_silence_intervals(output) == [(8.2, 9.0), (22.8, 23.8)]


def test_parse_ffmpeg_waveform_energy_output():
    output = """
[Parsed_ametadata_2] frame:0 pts:0 pts_time:0
[Parsed_ametadata_2] lavfi.astats.Overall.RMS_level=-14.380483
[Parsed_ametadata_2] frame:1 pts:8000 pts_time:0.5
[Parsed_ametadata_2] lavfi.astats.Overall.RMS_level=-inf
"""

    assert _parse_waveform_energy_samples(output) == [(0.0, -14.380483), (0.5, float("-inf"))]


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg is not installed")
def test_ffmpeg_waveform_detection_finds_real_silence(tmp_path):
    audio = tmp_path / "tone-silence-tone.mp3"
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=1",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=r=16000:cl=mono:d=1",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=660:duration=1",
            "-filter_complex",
            "[0:a][1:a][2:a]concat=n=3:v=0:a=1",
            "-ac",
            "1",
            "-ar",
            "16000",
            str(audio),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    intervals = VideoAudioPreprocessor(
        storage=RecordingStorage()
    )._detect_silence_intervals(audio)

    assert len(intervals) == 1
    assert intervals[0][0] == pytest.approx(1.0, abs=0.15)
    assert intervals[0][1] == pytest.approx(2.0, abs=0.15)


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg is not installed")
def test_ffmpeg_segment_command_produces_playable_mp4(tmp_path):
    source = tmp_path / "source.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=black:s=320x240:d=1",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(source),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    segments = VideoAnalysisPreprocessor(storage=RecordingStorage())._segment(source, tmp_path, 1)

    assert len(segments) == 1
    assert segments[0].path.stat().st_size > 0
