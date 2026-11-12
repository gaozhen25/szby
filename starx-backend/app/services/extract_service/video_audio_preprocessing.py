"""视频参考素材的音轨提取与绝对时间轴切分。"""

from __future__ import annotations

import re
import shutil
import tempfile
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.core.logging import get_logger

from .video_analysis_preprocessing import (
    VideoAnalysisPreprocessingError,
    VideoAnalysisPreprocessor,
    _run_command,
    _safe_owner,
)

logger = get_logger(__name__)


@dataclass(frozen=True)
class VideoAudioSegment:
    index: int
    url: str
    start_seconds: float
    duration_seconds: float


@dataclass(frozen=True)
class PreparedVideoAudio:
    audio_url: str
    duration_seconds: float
    size_bytes: int
    segments: tuple[VideoAudioSegment, ...]
    video_url: str = ""


@dataclass(frozen=True)
class LocalAudioSegment:
    path: Path
    start_seconds: float
    duration_seconds: float


class VideoAudioPreprocessor(VideoAnalysisPreprocessor):
    """下载链接视频，提取单声道音轨，并生成可并行转写的时间轴片段。"""

    def prepare(
        self,
        video_url: str,
        *,
        source_url: str = "",
        owner_id: str = "",
        source_persistence: Any | None = None,
    ) -> PreparedVideoAudio:
        if not shutil.which(self.ffprobe_binary):
            raise VideoAnalysisPreprocessingError("ffprobe 未安装，无法探测视频音轨")
        if not shutil.which(self.ffmpeg_binary):
            raise VideoAnalysisPreprocessingError("ffmpeg 未安装，无法提取视频音轨")

        with tempfile.TemporaryDirectory(prefix="starx-video-audio-") as directory:
            workspace = Path(directory)
            source_path = workspace / "source.mp4"
            size_bytes = self._download(video_url, source_path)
            persisted_video_url = video_url
            if source_persistence is not None:
                try:
                    persisted_video_url = source_persistence.persist_downloaded(
                        video_url,
                        source_path,
                        source_url=source_url,
                        owner_id=owner_id,
                    )
                except Exception as exc:
                    logger.warning(
                        "video source local persistence failed; continuing with original URL "
                        "error_type=%s error=%r",
                        exc.__class__.__name__,
                        exc,
                    )
            duration_seconds = self._probe_duration(source_path)
            audio_path = workspace / "source-audio.mp3"
            self._extract_audio(source_path, audio_path)

            digest = sha256((source_url or video_url).encode("utf-8")).hexdigest()
            safe_owner = _safe_owner(owner_id)
            local_segments = self._segment_audio(audio_path, workspace, duration_seconds)
            if not local_segments:
                raise VideoAnalysisPreprocessingError("ffmpeg 未生成有效的音轨片段")

            audio_url = self.storage.put_file(
                _storage_key(safe_owner, digest, "source-audio.mp3"),
                audio_path,
                "audio/mpeg",
            )
            segments = self._upload_segments(local_segments, audio_url, safe_owner, digest)
            return PreparedVideoAudio(
                audio_url=audio_url,
                duration_seconds=duration_seconds,
                size_bytes=size_bytes,
                segments=tuple(segments),
                video_url=persisted_video_url,
            )

    def _extract_audio(self, source_path: Path, output_path: Path) -> None:
        _run_command(
            [
                self.ffmpeg_binary,
                "-hide_banner",
                "-loglevel",
                "error",
                "-i",
                str(source_path),
                "-map",
                "0:a:0",
                "-vn",
                "-ac",
                "1",
                "-ar",
                "16000",
                "-b:a",
                "64k",
                str(output_path),
            ],
            "视频音轨提取失败，源视频可能不包含音轨",
        )

    def _segment_audio(
        self,
        audio_path: Path,
        workspace: Path,
        total_duration_seconds: float,
    ) -> list[LocalAudioSegment]:
        if settings.video_analysis_use_filetrans:
            target_segment_seconds = settings.video_analysis_audio_target_segment_seconds
            search_seconds = settings.video_analysis_audio_segment_search_seconds
        else:
            target_segment_seconds = settings.video_analysis_flash_target_segment_seconds
            search_seconds = settings.video_analysis_flash_segment_search_seconds
        silence_intervals = self._detect_silence_intervals(audio_path)
        ranges = _build_waveform_segment_ranges(
            total_duration_seconds,
            silence_intervals,
            min_segment_seconds=settings.video_analysis_audio_min_segment_seconds,
            target_segment_seconds=target_segment_seconds,
            search_seconds=search_seconds,
        )
        if _ranges_need_energy_fallback(
            ranges,
            target_segment_seconds=target_segment_seconds,
            search_seconds=search_seconds,
        ):
            ranges = _build_waveform_segment_ranges(
                total_duration_seconds,
                silence_intervals,
                energy_samples=self._detect_waveform_energy_samples(audio_path),
                min_segment_seconds=settings.video_analysis_audio_min_segment_seconds,
                target_segment_seconds=target_segment_seconds,
                search_seconds=search_seconds,
            )
        if len(ranges) <= 1:
            return [LocalAudioSegment(audio_path, 0, total_duration_seconds)]

        segments: list[LocalAudioSegment] = []
        for index, (start_seconds, end_seconds) in enumerate(ranges):
            duration_seconds = end_seconds - start_seconds
            output_path = workspace / f"audio-segment-{index:04d}.mp3"
            _run_command(
                [
                    self.ffmpeg_binary,
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-ss",
                    f"{start_seconds:.3f}",
                    "-i",
                    str(audio_path),
                    "-t",
                    f"{duration_seconds:.3f}",
                    "-acodec",
                    "copy",
                    str(output_path),
                ],
                f"音轨第 {index + 1} 段切分失败",
            )
            segments.append(LocalAudioSegment(output_path, start_seconds, duration_seconds))
        return segments

    def _detect_silence_intervals(self, audio_path: Path) -> list[tuple[float, float]]:
        """通过振幅阈值检测波形中的静音区间。"""
        completed = _run_command(
            [
                self.ffmpeg_binary,
                "-hide_banner",
                "-loglevel",
                "info",
                "-i",
                str(audio_path),
                "-af",
                (
                    "silencedetect="
                    f"noise={settings.video_analysis_audio_silence_threshold_db}dB:"
                    f"d={settings.video_analysis_audio_silence_min_seconds}"
                ),
                "-f",
                "null",
                "-",
            ],
            "音轨波形静音检测失败",
        )
        return _parse_silence_intervals(completed.stderr)

    def _detect_waveform_energy_samples(self, audio_path: Path) -> list[tuple[float, float]]:
        """每 0.5 秒采样一次 RMS，供持续背景声场景选择相对低谷。"""
        completed = _run_command(
            [
                self.ffmpeg_binary,
                "-hide_banner",
                "-nostats",
                "-loglevel",
                "info",
                "-i",
                str(audio_path),
                "-af",
                (
                    "asetnsamples=n=8000:p=0,"
                    "astats=metadata=1:reset=1,"
                    "ametadata=print:key=lavfi.astats.Overall.RMS_level"
                ),
                "-f",
                "null",
                "-",
            ],
            "音轨波形能量检测失败",
        )
        return _parse_waveform_energy_samples(completed.stderr)

    def _upload_segments(
        self,
        local_segments: list[LocalAudioSegment],
        audio_url: str,
        owner_id: str,
        digest: str,
    ) -> list[VideoAudioSegment]:
        segments: list[VideoAudioSegment] = []
        for index, local_segment in enumerate(local_segments):
            segment_url = audio_url
            if len(local_segments) > 1:
                segment_url = self.storage.put_file(
                    _storage_key(owner_id, digest, f"audio-segment-{index + 1:04d}.mp3"),
                    local_segment.path,
                    "audio/mpeg",
                )
            segments.append(
                VideoAudioSegment(
                    index=index,
                    url=segment_url,
                    start_seconds=local_segment.start_seconds,
                    duration_seconds=local_segment.duration_seconds,
                )
            )
        return segments


def _storage_key(owner_id: str, digest: str, filename: str) -> str:
    prefix = settings.object_storage_upload_dir.strip("/")
    return "/".join(
        part
        for part in (
            prefix,
            "extract",
            "video-analysis",
            owner_id,
            digest,
            filename,
        )
        if part
    )


def _parse_silence_intervals(value: str) -> list[tuple[float, float]]:
    intervals: list[tuple[float, float]] = []
    current_start: float | None = None
    for line in str(value or "").splitlines():
        start_match = re.search(r"silence_start:\s*([0-9.]+)", line)
        if start_match:
            current_start = float(start_match.group(1))
        end_match = re.search(r"silence_end:\s*([0-9.]+)", line)
        if end_match and current_start is not None:
            end = float(end_match.group(1))
            if end > current_start:
                intervals.append((current_start, end))
            current_start = None
    return intervals


def _parse_waveform_energy_samples(value: str) -> list[tuple[float, float]]:
    samples: list[tuple[float, float]] = []
    current_time: float | None = None
    for line in str(value or "").splitlines():
        time_match = re.search(r"pts_time:([0-9.]+)", line)
        if time_match:
            current_time = float(time_match.group(1))
            continue
        rms_match = re.search(r"Overall\.RMS_level=(-?(?:[0-9.]+|inf))", line)
        if rms_match and current_time is not None:
            raw_level = rms_match.group(1)
            rms_level = float("-inf") if raw_level == "-inf" else float(raw_level)
            samples.append((current_time, rms_level))
            current_time = None
    return samples


def _ranges_need_energy_fallback(
    ranges: list[tuple[float, float]],
    *,
    target_segment_seconds: float,
    search_seconds: float,
) -> bool:
    max_preferred_duration = target_segment_seconds + search_seconds
    return any(end - start > max_preferred_duration for start, end in ranges)


def _build_waveform_segment_ranges(
    duration_seconds: float,
    silence_intervals: list[tuple[float, float]],
    *,
    energy_samples: list[tuple[float, float]] | None = None,
    min_segment_seconds: float,
    target_segment_seconds: float,
    search_seconds: float,
) -> list[tuple[float, float]]:
    """在约一分钟的目标点附近，优先选择静音点，否则选择波形能量低谷。"""
    duration = max(float(duration_seconds), 0.0)
    if duration <= 0:
        return []

    candidates = sorted(
        (max(start, 0.0) + min(end, duration)) / 2
        for start, end in silence_intervals
        if end > start
    )
    cuts: list[float] = []
    last_cut = 0.0
    target = target_segment_seconds
    while True:
        if target >= duration - min_segment_seconds:
            break
        window_start = max(last_cut + min_segment_seconds, target - search_seconds)
        window_end = min(duration - min_segment_seconds, target + search_seconds)
        eligible = [cut for cut in candidates if window_start <= cut <= window_end]
        if eligible:
            selected = min(eligible, key=lambda cut: abs(cut - target))
        else:
            energy_candidates = [
                (sample_time, rms_level)
                for sample_time, rms_level in energy_samples or []
                if window_start <= sample_time <= window_end
            ]
            if energy_candidates:
                selected = min(
                    energy_candidates,
                    key=lambda sample: (sample[1], abs(sample[0] - target)),
                )[0]
            else:
                # 不用固定时间硬切；跳到下一个目标窗口继续寻找真实静音点。
                target += target_segment_seconds
                continue
        cuts.append(selected)
        last_cut = selected
        target = last_cut + target_segment_seconds

    boundaries = [0.0, *cuts, duration]
    return [
        (boundaries[index], boundaries[index + 1])
        for index in range(len(boundaries) - 1)
        if boundaries[index + 1] > boundaries[index]
    ]
