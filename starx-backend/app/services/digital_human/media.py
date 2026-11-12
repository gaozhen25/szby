from __future__ import annotations

import asyncio
import json
import re
import shutil
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from app.core.config import settings


def resolve_media_executable(tool: str) -> str:
    configured = (
        settings.digital_human_ffprobe_path
        if tool == "ffprobe"
        else settings.digital_human_ffmpeg_path
    ).strip()
    executable = shutil.which(configured or tool)
    if executable:
        return executable
    display_name = "FFprobe" if tool == "ffprobe" else "FFmpeg"
    env_name = (
        "STARX_DIGITAL_HUMAN_FFPROBE_PATH"
        if tool == "ffprobe"
        else "STARX_DIGITAL_HUMAN_FFMPEG_PATH"
    )
    raise RuntimeError(
        f"服务器缺少 {display_name}。请安装 ffmpeg 系统包，"
        f"或通过 {env_name} 指定可执行文件路径"
    )


async def download_media(url: str, target: Path, *, max_bytes: int) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("媒体地址必须使用 HTTP 或 HTTPS")
    size = 0
    timeout = httpx.Timeout(120, connect=10)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        async with client.stream("GET", url) as response:
            response.raise_for_status()
            with target.open("wb") as output:
                async for chunk in response.aiter_bytes():
                    size += len(chunk)
                    if size > max_bytes:
                        raise ValueError("媒体文件超过允许大小")
                    output.write(chunk)
    if size == 0:
        raise ValueError("媒体文件为空")


async def _probe_media(path: Path, *, label: str) -> dict[str, Any]:
    process = await asyncio.create_subprocess_exec(
        resolve_media_executable("ffprobe"),
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_streams",
        "-show_format",
        str(path),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate()
    if process.returncode != 0:
        raise ValueError(f"{label}无法解析：{stderr.decode(errors='ignore')[:200]}")
    return json.loads(stdout.decode())


async def inspect_video(path: Path) -> dict[str, Any]:
    payload = await _probe_media(path, label="视频")
    video_stream = next(
        (item for item in payload.get("streams", []) if item.get("codec_type") == "video"),
        None,
    )
    audio_stream = next(
        (item for item in payload.get("streams", []) if item.get("codec_type") == "audio"),
        None,
    )
    if video_stream is None:
        raise ValueError("上传文件中未检测到视频画面")
    if audio_stream is None:
        raise ValueError("上传视频中未检测到音轨")
    duration = float((payload.get("format") or {}).get("duration") or 0)
    return {
        "durationSeconds": duration,
        "width": int(video_stream.get("width") or 0),
        "height": int(video_stream.get("height") or 0),
        "videoCodec": str(video_stream.get("codec_name") or ""),
        "audioCodec": str(audio_stream.get("codec_name") or ""),
        "audioSampleRate": int(audio_stream.get("sample_rate") or 0),
        "audioChannels": int(audio_stream.get("channels") or 0),
        "audioBitRate": int(audio_stream.get("bit_rate") or 0),
    }


async def inspect_audio(path: Path) -> dict[str, Any]:
    payload = await _probe_media(path, label="背景音乐")
    audio_stream = next(
        (item for item in payload.get("streams", []) if item.get("codec_type") == "audio"),
        None,
    )
    if audio_stream is None:
        raise ValueError("背景音乐中未检测到音轨")
    format_info = payload.get("format") or {}
    duration = float(format_info.get("duration") or audio_stream.get("duration") or 0)
    if duration <= 0:
        raise ValueError("背景音乐时长无效")
    return {
        "durationSeconds": duration,
        "codec": str(audio_stream.get("codec_name") or ""),
        "sampleRate": int(audio_stream.get("sample_rate") or 0),
        "channels": int(audio_stream.get("channels") or 0),
        "bitRate": int(
            audio_stream.get("bit_rate") or format_info.get("bit_rate") or 0
        ),
    }


async def prepare_background_music(
    source_path: Path,
    output_path: Path,
    *,
    max_duration_seconds: float,
) -> None:
    """解码并裁切为 ICE 稳定支持的无损 PCM，避免再次使用低码率中间文件。"""
    process = await asyncio.create_subprocess_exec(
        resolve_media_executable("ffmpeg"),
        "-y",
        "-i",
        str(source_path),
        "-t",
        str(max(0.1, float(max_duration_seconds))),
        "-vn",
        "-ac",
        "2",
        "-ar",
        "48000",
        "-c:a",
        "pcm_s16le",
        str(output_path),
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await process.communicate()
    if process.returncode != 0 or not output_path.exists():
        raise ValueError(
            f"背景音乐预处理失败：{stderr.decode(errors='ignore')[-200:]}"
        )


async def measure_audio_loudness(path: Path) -> dict[str, float]:
    process = await asyncio.create_subprocess_exec(
        resolve_media_executable("ffmpeg"),
        "-hide_banner",
        "-nostats",
        "-i",
        str(path),
        "-map",
        "0:a:0",
        "-filter:a",
        "ebur128=peak=true",
        "-f",
        "null",
        "-",
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await process.communicate()
    output = stderr.decode(errors="ignore")
    if process.returncode != 0:
        raise ValueError(f"音频响度检测失败：{output[-200:]}")
    loudness_values = re.findall(
        r"^\s*I:\s*(-?\d+(?:\.\d+)?)\s+LUFS",
        output,
        re.MULTILINE,
    )
    peak_values = re.findall(
        r"^\s*Peak:\s*(-?\d+(?:\.\d+)?)\s+dBFS",
        output,
        re.MULTILINE,
    )
    if not loudness_values or not peak_values:
        raise ValueError("音频响度检测未返回有效结果")
    return {
        "integratedLoudnessLufs": float(loudness_values[-1]),
        "truePeakDbtp": float(peak_values[-1]),
    }


async def extract_audio(video_path: Path, audio_path: Path) -> None:
    process = await asyncio.create_subprocess_exec(
        resolve_media_executable("ffmpeg"),
        "-y",
        "-i",
        str(video_path),
        "-vn",
        "-ac",
        "1",
        "-ar",
        "24000",
        "-b:a",
        "96k",
        str(audio_path),
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await process.communicate()
    if process.returncode != 0 or not audio_path.exists():
        raise ValueError(f"视频音轨提取失败：{stderr.decode(errors='ignore')[-200:]}")


async def extract_cover(video_path: Path, cover_path: Path) -> None:
    process = await asyncio.create_subprocess_exec(
        resolve_media_executable("ffmpeg"),
        "-y",
        "-ss",
        "1",
        "-i",
        str(video_path),
        "-frames:v",
        "1",
        "-vf",
        "scale='min(720,iw)':-2",
        str(cover_path),
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await process.communicate()
    if process.returncode != 0 or not cover_path.exists():
        raise ValueError(f"视频封面提取失败：{stderr.decode(errors='ignore')[-200:]}")
