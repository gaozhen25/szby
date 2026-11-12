from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass
from time import sleep
from typing import Any
from urllib.parse import quote

from app.core.config import settings
from app.services.digital_human.subtitles import (
    SubtitleCue,
    timed_subtitle_cues_are_complete,
)

from .base import ProviderVideoResult


@dataclass(frozen=True)
class EditingOptions:
    title: str
    script_text: str
    subtitles_enabled: bool = True
    background_url: str = ""
    bubble_url: str = ""
    background_music_url: str = ""
    background_music_gain: float = 0.1
    voice_loudness: float = -16.0
    voice_true_peak: float = -2.0
    output_width: int = 1080
    output_height: int = 1920
    subtitle_cues: tuple[SubtitleCue, ...] = ()


class NonRetryableEditingError(RuntimeError):
    """配置或授权错误，重试不会自行恢复。"""


class AliyunIceEditingProvider:
    """阿里云智能媒体服务（ICE）云剪辑适配器。"""

    def __init__(
        self,
        *,
        access_key_id: str | None = None,
        access_key_secret: str | None = None,
        region: str | None = None,
        endpoint: str | None = None,
        output_bucket: str | None = None,
        output_prefix: str | None = None,
        font_url: str | None = None,
        produce_template_id: str | None = None,
        client: Any | None = None,
    ) -> None:
        self.access_key_id = (
            access_key_id
            if access_key_id is not None
            else settings.digital_human_ice_access_key_id
            or (
                settings.object_storage_access_key
                if settings.object_storage_provider == "oss"
                else ""
            )
        )
        self.access_key_secret = (
            access_key_secret
            if access_key_secret is not None
            else settings.digital_human_ice_access_key_secret
            or (
                settings.object_storage_secret_key
                if settings.object_storage_provider == "oss"
                else ""
            )
        )
        self.region = region or settings.digital_human_ice_region
        self.endpoint = endpoint or settings.digital_human_ice_endpoint
        self.output_bucket = (
            output_bucket
            if output_bucket is not None
            else settings.digital_human_ice_output_bucket
            or (
                settings.object_storage_bucket
                if settings.object_storage_provider == "oss"
                and settings.object_storage_region == self.region
                else ""
            )
        )
        self.output_prefix = (
            output_prefix or settings.digital_human_ice_output_prefix
        ).strip("/")
        self.font_url = (
            font_url if font_url is not None else settings.digital_human_ice_font_url
        )
        self.produce_template_id = (
            produce_template_id
            if produce_template_id is not None
            else settings.digital_human_ice_produce_template_id
        ).strip()
        self._client = client

    async def submit(
        self,
        *,
        workflow_id: str,
        raw_video_url: str,
        duration_seconds: float,
        options: EditingOptions,
    ) -> tuple[str, str]:
        if not self.output_bucket:
            raise NonRetryableEditingError(
                "阿里云 ICE 输出 Bucket 未配置；输出 OSS Bucket 必须与 ICE "
                f"同区域（当前 ICE：{self.region}，主存储："
                f"{settings.object_storage_region or '未配置'}）"
            )
        output_url = self.output_url(workflow_id)
        timeline = build_timeline(
            raw_video_url=raw_video_url,
            duration_seconds=duration_seconds,
            options=options,
            font_url=self.font_url,
        )
        job_id = await asyncio.to_thread(
            self._submit_sync,
            timeline,
            output_url,
            options.output_width,
            options.output_height,
            duration_seconds,
        )
        return job_id, output_url

    async def get_result(self, job_id: str) -> ProviderVideoResult:
        return await asyncio.to_thread(self._get_result_sync, job_id)

    def output_url(self, workflow_id: str) -> str:
        key = "/".join(
            item
            for item in (self.output_prefix, f"{workflow_id}.mp4")
            if item
        )
        return (
            f"https://{self.output_bucket}.oss-{self.region}.aliyuncs.com/"
            f"{quote(key, safe='/')}"
        )

    def _client_instance(self) -> Any:
        if self._client is not None:
            return self._client
        if not self.access_key_id or not self.access_key_secret:
            raise RuntimeError("阿里云 ICE AccessKey 未配置")
        try:
            from alibabacloud_ice20201109.client import Client
            from alibabacloud_tea_openapi import models as open_api_models
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "缺少阿里云 ICE SDK，请安装项目依赖 alibabacloud-ice20201109"
            ) from exc
        config = open_api_models.Config(
            access_key_id=self.access_key_id,
            access_key_secret=self.access_key_secret,
        )
        config.region_id = self.region
        config.endpoint = self.endpoint
        self._client = Client(config)
        return self._client

    def _submit_sync(
        self,
        timeline: dict[str, Any],
        output_url: str,
        width: int,
        height: int,
        duration_seconds: float,
    ) -> str:
        from alibabacloud_ice20201109 import models as ice_models

        output_config: dict[str, Any] = {
            "MediaURL": output_url,
            "Width": width,
            "Height": height,
            "MaxDuration": max(1, int(duration_seconds + 1)),
        }
        if self.produce_template_id:
            output_config["ProduceTemplateId"] = self.produce_template_id
        request = ice_models.SubmitMediaProducingJobRequest(
            timeline=json.dumps(timeline, ensure_ascii=False, separators=(",", ":")),
            output_media_config=json.dumps(output_config, separators=(",", ":")),
        )
        try:
            response = _call_with_tls_eof_retries(
                lambda: self._client_instance().submit_media_producing_job(request)
            )
        except Exception as exc:
            if _requires_subscription(exc):
                raise NonRetryableEditingError(
                    "阿里云 ICE 服务未开通或缺少可用订阅，请先在当前 "
                    "AccessKey 所属账号开通智能媒体服务（ICE）"
                ) from exc
            if _is_forbidden(exc):
                raise NonRetryableEditingError(
                    "阿里云 ICE 权限不足：当前 RAM 用户缺少 "
                    "ice:SubmitMediaProducingJob 权限"
                ) from exc
            raise
        job_id = str(getattr(response.body, "job_id", "") or "")
        if not job_id:
            raise RuntimeError("阿里云 ICE 未返回剪辑任务 ID")
        return job_id

    def _get_result_sync(self, job_id: str) -> ProviderVideoResult:
        from alibabacloud_ice20201109 import models as ice_models

        request = ice_models.GetMediaProducingJobRequest(job_id=job_id)
        try:
            response = _call_with_tls_eof_retries(
                lambda: self._client_instance().get_media_producing_job(request)
            )
        except Exception as exc:
            if _is_forbidden(exc):
                raise NonRetryableEditingError(
                    "阿里云 ICE 权限不足：当前 RAM 用户缺少 "
                    "ice:GetMediaProducingJob 权限"
                ) from exc
            raise
        job = getattr(response.body, "media_producing_job", None)
        status = str(getattr(job, "status", "") or "")
        media_url = str(getattr(job, "media_url", "") or "")
        raw = {
            "jobId": job_id,
            "status": status,
            "mediaUrl": media_url,
            "requestId": str(getattr(response.body, "request_id", "") or ""),
        }
        if status.lower() in {"success", "completed"}:
            return ProviderVideoResult("completed", media_url=media_url, raw=raw)
        if status.lower() in {"failed", "canceled"}:
            message = str(getattr(job, "message", "") or "阿里云剪辑合成失败")
            return ProviderVideoResult("failed", error_message=message, raw=raw)
        return ProviderVideoResult("processing", raw=raw)


def build_timeline(
    *,
    raw_video_url: str,
    duration_seconds: float,
    options: EditingOptions,
    font_url: str = "",
) -> dict[str, Any]:
    duration = max(0.1, float(duration_seconds))
    width = options.output_width
    height = options.output_height
    video_tracks: list[dict[str, Any]] = []
    if options.background_url:
        video_tracks.append(
            {
                "VideoTrackClips": [
                    {
                        "MediaURL": options.background_url,
                        "Type": "GlobalImage",
                        "AdaptMode": "Cover",
                        "Width": width,
                        "Height": height,
                        "TimelineIn": 0,
                        "TimelineOut": duration,
                    }
                ]
            }
        )
    video_tracks.append(
        {
            "VideoTrackClips": [
                {
                    "MediaURL": raw_video_url,
                    "AdaptMode": "Contain" if options.background_url else "Cover",
                    "Width": width,
                    "Height": height,
                    "TimelineIn": 0,
                    "TimelineOut": duration,
                    "Effects": [
                        {
                            "Type": "ALoudNorm",
                            "Loudness": options.voice_loudness,
                            "TruePeak": options.voice_true_peak,
                        }
                    ],
                }
            ]
        }
    )
    if options.bubble_url:
        video_tracks.append(
            {
                "VideoTrackClips": [
                    {
                        "Type": "GlobalImage",
                        "MediaURL": options.bubble_url,
                        "X": 54,
                        "Y": 230,
                        "Width": 972,
                        "Height": 360,
                        "TimelineIn": 0,
                        "TimelineOut": duration,
                    }
                ]
            }
        )

    subtitle_clips: list[dict[str, Any]] = []
    if options.title.strip():
        subtitle_clips.append(
            _text_clip(
                content=options.title.strip(),
                start=0,
                end=duration,
                x=90,
                y=100,
                font_size=72,
                font_color="#FFFFFF",
                outline=8,
                font_url=font_url,
                bold=True,
            )
        )
    if options.subtitles_enabled:
        candidate_timed_cues = [
            (
                cue.content,
                max(0.0, cue.start_seconds),
                min(duration, cue.end_seconds),
            )
            for cue in options.subtitle_cues
            if cue.content.strip()
            and cue.start_seconds < duration
            and cue.end_seconds > cue.start_seconds
        ]
        timed_cues = (
            candidate_timed_cues
            if timed_subtitle_cues_are_complete(
                options.subtitle_cues,
                options.script_text,
            )
            else []
        )
        cues = timed_cues or split_subtitles(options.script_text, duration)
        for content, start, end in cues:
            subtitle_clips.append(
                _text_clip(
                    content=content,
                    start=start,
                    end=end,
                    x=90,
                    y=1510,
                    font_size=48,
                    font_color="#FFFFFF",
                    outline=6,
                    font_url=font_url,
                    bold=True,
                )
            )

    timeline: dict[str, Any] = {
        "VideoTracks": video_tracks,
        "SubtitleTracks": [{"SubtitleTrackClips": subtitle_clips}],
    }
    if options.background_music_url:
        timeline["AudioTracks"] = [
            {
                "AudioTrackClips": [
                    {
                        "MediaURL": options.background_music_url,
                        "TimelineIn": 0,
                        "TimelineOut": duration,
                        "LoopMode": True,
                        "Effects": [
                            {
                                "Type": "Volume",
                                "Gain": options.background_music_gain,
                            }
                        ],
                    }
                ]
            }
        ]
        timeline["EffectTracks"] = [
            {
                "EffectTrackItems": [
                    {
                        "Type": "AEqualize",
                        "Peak": 0.95,
                        "Gain": 1.0,
                    }
                ]
            }
        ]
    return timeline


def split_subtitles(text: str, duration_seconds: float) -> list[tuple[str, float, float]]:
    compact = re.sub(r"\s+", " ", str(text or "")).strip()
    if not compact:
        return []
    sentences = [
        item.strip()
        for item in re.split(r"(?<=[，。！？；,.!?;])", compact)
        if item.strip()
    ]
    chunks: list[str] = []
    for sentence in sentences or [compact]:
        while len(sentence) > 18:
            chunks.append(sentence[:18])
            sentence = sentence[18:]
        if sentence:
            chunks.append(sentence)
    weights = [max(1, len(re.sub(r"\W", "", item))) for item in chunks]
    total_weight = sum(weights)
    cursor = 0.0
    result: list[tuple[str, float, float]] = []
    for index, (chunk, weight) in enumerate(zip(chunks, weights, strict=True)):
        end = (
            float(duration_seconds)
            if index == len(chunks) - 1
            else cursor + float(duration_seconds) * weight / total_weight
        )
        result.append((chunk, round(cursor, 3), round(max(cursor + 0.1, end), 3)))
        cursor = end
    return result


def _text_clip(
    *,
    content: str,
    start: float,
    end: float,
    x: int,
    y: int,
    font_size: int,
    font_color: str,
    outline: int,
    font_url: str,
    bold: bool,
) -> dict[str, Any]:
    clip: dict[str, Any] = {
        "Type": "Text",
        "Content": content,
        "X": x,
        "Y": y,
        "FontSize": font_size,
        "FontColor": font_color,
        "Outline": outline,
        "OutlineColour": "#000000",
        "AdaptMode": "AutoWrap",
        "TimelineIn": start,
        "TimelineOut": end,
        "Alignment": "TopCenter",
        "FontFace": {"Bold": bold, "Italic": False, "Underline": False},
    }
    if font_url:
        clip["FontUrl"] = font_url
    return clip


def _is_forbidden(exc: Exception) -> bool:
    message = str(exc).lower()
    return (
        "forbidden" in message
        or "statuscode': 403" in message
        or "status code: 403" in message
        or "not authorized" in message
    )


def _requires_subscription(exc: Exception) -> bool:
    message = str(exc).lower()
    return (
        "forbidden.subscriptionrequired" in message
        or "purchase the appropriate subscription" in message
    )


def _call_with_tls_eof_retries(action: Any) -> Any:
    delays = (0.5, 1.5)
    for attempt in range(len(delays) + 1):
        try:
            return action()
        except Exception as exc:
            if attempt >= len(delays) or not _is_tls_eof_error(exc):
                raise
            sleep(delays[attempt])
    raise AssertionError("unreachable ICE retry state")


def _is_tls_eof_error(exc: BaseException) -> bool:
    current: BaseException | None = exc
    visited: set[int] = set()
    messages: list[str] = []
    while current is not None and id(current) not in visited:
        visited.add(id(current))
        messages.append(f"{type(current).__name__}: {current}".lower())
        current = current.__cause__ or current.__context__
    combined = " ".join(messages)
    return (
        "unexpected_eof_while_reading" in combined
        or "unexpected eof while reading" in combined
        or "ssleoferror" in combined
    )
