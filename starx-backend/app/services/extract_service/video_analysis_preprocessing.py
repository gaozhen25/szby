from __future__ import annotations

import json
import math
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any

import requests

from app.core.config import settings
from app.services.extract_service.platforms.base import DEFAULT_HEADERS
from app.services.resource_limits import ensure_size_within_limit


class VideoAnalysisPreprocessingError(RuntimeError):
    pass


@dataclass(frozen=True)
class VideoAnalysisSegment:
    index: int
    url: str
    start_seconds: float
    duration_seconds: float


@dataclass(frozen=True)
class PreparedVideoAnalysis:
    source_url: str
    duration_seconds: float
    size_bytes: int
    segmented: bool
    segments: tuple[VideoAnalysisSegment, ...]


@dataclass(frozen=True)
class LocalVideoAnalysisSegment:
    path: Path
    start_seconds: float
    duration_seconds: float


class VideoAnalysisPreprocessor:
    """探测视频，并将过长或过大的源视频压缩切片后上传到对象存储。"""

    def __init__(
        self,
        *,
        storage: Any,
        media_session: requests.Session | None = None,
        ffmpeg_binary: str = "ffmpeg",
        ffprobe_binary: str = "ffprobe",
        connect_timeout: int = 15,
        read_timeout: int = 300,
    ) -> None:
        self.storage = storage
        self.media_session = media_session or requests.Session()
        self.ffmpeg_binary = ffmpeg_binary
        self.ffprobe_binary = ffprobe_binary
        self.timeout = (connect_timeout, read_timeout)

    def prepare(
        self,
        video_url: str,
        *,
        source_url: str = "",
        owner_id: str = "",
    ) -> PreparedVideoAnalysis:
        if not shutil.which(self.ffprobe_binary):
            raise VideoAnalysisPreprocessingError("ffprobe 未安装，无法探测长视频")
        if not shutil.which(self.ffmpeg_binary):
            raise VideoAnalysisPreprocessingError("ffmpeg 未安装，无法切分长视频")

        with tempfile.TemporaryDirectory(prefix="starx-video-analysis-") as directory:
            workspace = Path(directory)
            source_path = workspace / "source.mp4"
            size_bytes = self._download(video_url, source_path)
            duration_seconds = self._probe_duration(source_path)
            needs_segments = (
                size_bytes > settings.video_analysis_direct_max_bytes
                or duration_seconds > settings.video_analysis_direct_max_seconds
            )
            if not needs_segments:
                return PreparedVideoAnalysis(
                    source_url=video_url,
                    duration_seconds=duration_seconds,
                    size_bytes=size_bytes,
                    segmented=False,
                    segments=(
                        VideoAnalysisSegment(
                            index=0,
                            url=video_url,
                            start_seconds=0,
                            duration_seconds=duration_seconds,
                        ),
                    ),
                )

            local_segments = self._segment(source_path, workspace, duration_seconds)
            if not local_segments:
                raise VideoAnalysisPreprocessingError("ffmpeg 未生成有效的视频分片")

            identity = source_url or video_url
            digest = sha256(identity.encode("utf-8")).hexdigest()
            safe_owner = _safe_owner(owner_id)
            segments: list[VideoAnalysisSegment] = []
            for index, local_segment in enumerate(local_segments):
                key = _segment_storage_key(safe_owner, digest, index)
                uploaded_url = self.storage.put_file(key, local_segment.path, "video/mp4")
                segments.append(
                    VideoAnalysisSegment(
                        index=index,
                        url=uploaded_url,
                        start_seconds=local_segment.start_seconds,
                        duration_seconds=local_segment.duration_seconds,
                    )
                )

            return PreparedVideoAnalysis(
                source_url=video_url,
                duration_seconds=duration_seconds,
                size_bytes=size_bytes,
                segmented=True,
                segments=tuple(segments),
            )

    def _download(self, video_url: str, target: Path) -> int:
        try:
            response = self.media_session.get(
                video_url,
                timeout=self.timeout,
                headers=DEFAULT_HEADERS,
                stream=True,
            )
            response.raise_for_status()
            raw_length = response.headers.get("Content-Length")
            if raw_length and raw_length.isdigit():
                ensure_size_within_limit(
                    int(raw_length),
                    limit=settings.video_analysis_max_source_bytes,
                    label="video analysis source",
                )
            total = 0
            with target.open("wb") as output:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if not chunk:
                        continue
                    total += len(chunk)
                    ensure_size_within_limit(
                        total,
                        limit=settings.video_analysis_max_source_bytes,
                        label="video analysis source",
                    )
                    output.write(chunk)
            if total <= 0:
                raise VideoAnalysisPreprocessingError("视频内容为空")
            return total
        except VideoAnalysisPreprocessingError:
            raise
        except Exception as exc:
            message = str(exc).strip() or exc.__class__.__name__
            raise VideoAnalysisPreprocessingError(f"视频预处理下载失败：{message}") from exc

    def _probe_duration(self, source_path: Path) -> float:
        command = [
            self.ffprobe_binary,
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "json",
            str(source_path),
        ]
        completed = _run_command(command, "视频时长探测失败")
        try:
            payload = json.loads(completed.stdout)
            duration = float(payload.get("format", {}).get("duration") or 0)
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise VideoAnalysisPreprocessingError("ffprobe 未返回有效的视频时长") from exc
        if not math.isfinite(duration) or duration <= 0:
            raise VideoAnalysisPreprocessingError("无法识别视频时长")
        return duration

    def _segment(
        self,
        source_path: Path,
        workspace: Path,
        total_duration_seconds: float,
    ) -> list[LocalVideoAnalysisSegment]:
        segment_seconds = float(settings.video_analysis_segment_seconds)
        overlap_seconds = float(settings.video_analysis_segment_overlap_seconds)
        stride_seconds = segment_seconds - overlap_seconds
        segments: list[LocalVideoAnalysisSegment] = []
        index = 0
        start_seconds = 0.0
        while start_seconds < total_duration_seconds:
            if index > 0 and start_seconds >= total_duration_seconds - overlap_seconds:
                break
            duration_seconds = min(segment_seconds, total_duration_seconds - start_seconds)
            output_path = workspace / f"segment-{index:04d}.mp4"
            command = [
                self.ffmpeg_binary,
                "-hide_banner",
                "-loglevel",
                "error",
                "-i",
                str(source_path),
                "-ss",
                f"{start_seconds:.3f}",
                "-t",
                f"{duration_seconds:.3f}",
                "-map",
                "0:v:0",
                "-map",
                "0:a?",
                "-vf",
                "scale=-2:min(720\\,ih)",
                "-r",
                "15",
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-crf",
                "28",
                "-c:a",
                "aac",
                "-b:a",
                "96k",
                "-movflags",
                "+faststart",
                str(output_path),
            ]
            _run_command(command, f"视频第 {index + 1} 段压缩切片失败")
            segments.append(
                LocalVideoAnalysisSegment(
                    path=output_path,
                    start_seconds=start_seconds,
                    duration_seconds=duration_seconds,
                )
            )
            index += 1
            start_seconds = index * stride_seconds
        return segments


def _run_command(command: list[str], error_prefix: str) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            timeout=1800,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        stderr = str(getattr(exc, "stderr", "") or "").strip()
        message = stderr[-800:] if stderr else str(exc).strip() or exc.__class__.__name__
        raise VideoAnalysisPreprocessingError(f"{error_prefix}：{message}") from exc


def _safe_owner(owner_id: str) -> str:
    return "".join(char for char in owner_id if char.isalnum() or char in {"-", "_"}) or "shared"


def _segment_storage_key(owner_id: str, digest: str, index: int) -> str:
    prefix = settings.object_storage_upload_dir.strip("/")
    parts = [
        part
        for part in (
            prefix,
            "extract",
            "video-analysis",
            owner_id,
            digest,
            f"segment-{index + 1:04d}.mp4",
        )
        if part
    ]
    return "/".join(parts)
