"""基于视频音轨与绝对时间轴生成创作分镜的工作流。"""

from __future__ import annotations

import asyncio
import re
from dataclasses import replace
from time import perf_counter
from typing import Any

from app.core.config import settings
from app.core.logging import get_logger
from app.schemas.extract import VideoAnalysisWorkflowSchema
from app.services.extract_service.video_audio_preprocessing import (
    PreparedVideoAudio,
    VideoAudioPreprocessor,
    VideoAudioSegment,
)
from app.services.extract_service.video_source_persistence import VideoSourcePersistenceService
from app.services.prompt_builder import (
    build_video_analysis_system,
    build_video_audio_storyboard_user,
)

from .base import BaseWorkflow, WorkflowRegister, normalize_json
from .video_analysis_results import (
    format_video_timestamp,
    normalize_video_analysis_result,
    offset_video_analysis_result,
)
from .video_filetrans_results import (
    normalize_filetrans_timeline,
    normalize_flash_fallback_timeline,
)

logger = get_logger(__name__)


@WorkflowRegister.register
class VideoAnalysisWorkflow(BaseWorkflow):
    """提取真实音轨，按时间轴转写，再基于转写生成创作分镜。"""

    type = "video_analysis"

    def __init__(self, workflow_id: str, context: dict[str, Any] | None = None) -> None:
        super().__init__(workflow_id, context)
        ctx = context or {}
        self.video_url = str(ctx.get("video_url") or "")
        self.user_id = str(ctx.get("user_id") or "")
        self.account_id = ctx.get("account_id")

    async def execute(self) -> dict[str, Any]:
        workflow_started_at = perf_counter()
        record = self.store.get_workflow(self.workflow_id)
        video_url = self.video_url or str(getattr(record, "video_url", "") or "")
        if not video_url:
            raise ValueError("Video URL is required for video analysis.")

        self.store.update_progress(self.workflow_id, progress=20, current_stage="audio_extraction")
        stage_started_at = perf_counter()
        prepared = await self._prepare_audio(record, video_url)
        persisted_video_url = str(prepared.video_url or video_url)
        if persisted_video_url != video_url:
            self.store.update_video_url(self.workflow_id, persisted_video_url)
        self._log_stage_duration(
            "audio_preparation",
            stage_started_at,
            segment_count=len(prepared.segments),
        )

        self.store.update_progress(self.workflow_id, progress=35, current_stage="audio_transcription")
        stage_started_at = perf_counter()
        audio_timeline = await self._transcribe_audio(record, prepared.segments)
        self._log_stage_duration(
            "audio_transcription",
            stage_started_at,
            segment_count=len(prepared.segments),
        )

        self.store.update_progress(self.workflow_id, progress=80, current_stage="storyboard_generation")
        stage_started_at = perf_counter()
        generated = await self._generate_storyboard(record, prepared, audio_timeline)
        self._log_stage_duration("storyboard_generation", stage_started_at)
        generated["sourceAudioUrl"] = prepared.audio_url
        generated["audioTimeline"] = audio_timeline
        # 音轨转写是脚本事实源，不接受后续文本模型对台词或时间轴的改写。
        generated["videoScript"] = audio_timeline

        self.store.update_progress(self.workflow_id, progress=100, current_stage="completed")
        self._log_stage_duration("total", workflow_started_at)
        return normalize_video_analysis_result(generated)

    async def _prepare_audio(self, record: Any, video_url: str) -> PreparedVideoAudio:
        preprocessor = self.context.get("_video_preprocessor") or VideoAudioPreprocessor(
            storage=self.storage
        )
        persistence = self.context.get("_video_persistence_service") or VideoSourcePersistenceService(
            storage=self.storage
        )
        source_url = str(getattr(record, "source_url", "") or "")
        owner_id = self._owner_id(record)
        try:
            if not callable(getattr(persistence, "persist_downloaded", None)):
                # 兼容旧扩展：新版实现会在视频首次下载后直接转存本地文件。
                try:
                    video_url = await asyncio.to_thread(
                        persistence.persist,
                        video_url,
                        source_url=source_url,
                        owner_id=owner_id,
                    )
                except Exception as exc:
                    logger.warning(
                        "legacy video persistence failed; continuing with original URL "
                        "workflow_id=%s error_type=%s error=%r",
                        self.workflow_id,
                        exc.__class__.__name__,
                        exc,
                    )
                source_persistence = None
            else:
                source_persistence = persistence
            prepared = await asyncio.to_thread(
                preprocessor.prepare,
                video_url,
                source_url=source_url,
                owner_id=owner_id,
                source_persistence=source_persistence,
            )
            if not prepared.video_url:
                prepared = replace(prepared, video_url=video_url)
            return prepared
        except Exception as exc:
            raise ValueError(f"视频音轨提取失败：{_exception_message_simple(exc)}") from exc

    async def _transcribe_audio(
        self,
        record: Any,
        segments: tuple[VideoAudioSegment, ...],
    ) -> list[dict[str, Any]]:
        use_filetrans = settings.video_analysis_use_filetrans
        transcriber = getattr(
            self.ai_service,
            "speech_filetrans" if use_filetrans else "speech_discern",
            None,
        )
        if not callable(transcriber):
            model_name = "qwen3-asr-flash-filetrans" if use_filetrans else "qwen3-asr-flash"
            raise ValueError(f"当前 AI 服务不支持 {model_name}")

        semaphore = asyncio.Semaphore(settings.video_analysis_segment_concurrency)
        progress_lock = asyncio.Lock()
        completed_count = 0

        async def transcribe(segment: VideoAudioSegment) -> tuple[list[dict[str, Any]], bool]:
            nonlocal completed_count
            time_range = _segment_time_range(segment)
            step_id = self.store.create_step(
                workflow_id=self.workflow_id,
                user_id=self.user_id or getattr(record, "user_id", ""),
                account_id=self.account_id or getattr(record, "account_id", None),
                step_type="audio_transcription_segment",
                input_payload={
                    "audio_url": segment.url,
                    "time_range": time_range,
                    "segment_index": segment.index,
                },
                sort_order=segment.index,
                group_key="audio_transcription",
            )
            async with semaphore:
                self.store.mark_step_running(step_id)
                raw: Any = None
                try:
                    max_attempts = settings.video_analysis_segment_max_attempts
                    for attempt in range(1, max_attempts + 1):
                        if use_filetrans:
                            raw = await transcriber(
                                audio_url=segment.url,
                                enable_itn=False,
                                enable_words=True,
                            )
                        else:
                            raw = await transcriber(
                                audio_url=segment.url,
                                model=settings.DEFAULT_VOICE_DISCERN_MODEL,
                                enable_itn=False,
                            )
                        if raw is not None:
                            break
                        if attempt < max_attempts:
                            delay_seconds = (
                                settings.video_analysis_segment_retry_backoff_seconds
                                * (2 ** (attempt - 1))
                            )
                            logger.warning(
                                "audio transcription segment retry scheduled workflow_id=%s "
                                "segment_index=%s attempt=%s max_attempts=%s delay_seconds=%.2f",
                                self.workflow_id,
                                segment.index,
                                attempt,
                                max_attempts,
                                delay_seconds,
                            )
                            if delay_seconds > 0:
                                await asyncio.sleep(delay_seconds)
                    normalizer = (
                        normalize_filetrans_timeline
                        if use_filetrans
                        else normalize_flash_fallback_timeline
                    )
                    result = normalizer(
                        raw,
                        chunk_start_seconds=segment.start_seconds,
                        chunk_duration_seconds=segment.duration_seconds,
                    )
                    if not result:
                        raise ValueError(f"音轨第 {segment.index + 1} 段转写未返回文本")
                    self.store.mark_step_completed(step_id, {
                        "sentences": result,
                        "transcriptionMode": "filetrans" if use_filetrans else "flash_fallback",
                    })
                except Exception as exc:
                    self.store.mark_step_failed(step_id, _exception_message_simple(exc))
                    raise

                async with progress_lock:
                    completed_count += 1
                    progress = 35 + int(40 * completed_count / max(len(segments), 1))
                    self.store.update_progress(
                        self.workflow_id,
                        progress=progress,
                        current_stage="audio_transcription",
                    )
                return result, bool(result)

        tasks = [
            asyncio.create_task(
                transcribe(segment),
                name=f"video-analysis-{self.workflow_id}-audio-{segment.index}",
            )
            for segment in segments
        ]
        try:
            transcribed = list(await asyncio.gather(*tasks))
        except BaseException:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            raise
        if transcribed and not any(recognized for _, recognized in transcribed):
            raise ValueError("音轨转写失败，AI 服务未返回任何转写结果")
        timeline = [item for items, _ in transcribed for item in items]
        return sorted(timeline, key=lambda item: (item.get("beginMs", 0), item.get("endMs", 0)))

    async def _generate_storyboard(
        self,
        record: Any,
        prepared: PreparedVideoAudio,
        audio_timeline: list[dict[str, Any]],
    ) -> dict[str, Any]:
        generate = getattr(self.ai_service, "chat_completion", None)
        if not callable(generate):
            raise ValueError("当前 AI 服务不支持基于音轨生成分镜")

        prompt = build_video_audio_storyboard_user(
            record,
            audio_url=prepared.audio_url,
            duration=format_video_timestamp(prepared.duration_seconds),
            audio_timeline=audio_timeline,
        )
        step_id = self.store.create_step(
            workflow_id=self.workflow_id,
            user_id=self.user_id or getattr(record, "user_id", ""),
            account_id=self.account_id or getattr(record, "account_id", None),
            step_type="storyboard_generation",
            input_payload={
                "source_audio_url": prepared.audio_url,
                "audio_timeline": audio_timeline,
                "duration_seconds": prepared.duration_seconds,
            },
            sort_order=len(prepared.segments),
            group_key="storyboard_generation",
        )
        self.store.mark_step_running(step_id)
        try:
            raw = await generate(
                messages=[{"role": "user", "content": prompt}],
                system_prompt=build_video_analysis_system(),
                temperature=0.25,
            )
            parsed = normalize_json(raw)
            if parsed is None:
                parsed = await self._repair_result_json(str(raw or ""))
            if parsed is None:
                raise ValueError("基于音轨生成的分镜结果格式异常")
            result = normalize_video_analysis_result(parsed)
            self.store.mark_step_completed(step_id, result)
            return result
        except Exception as exc:
            self.store.mark_step_failed(step_id, _exception_message_simple(exc))
            raise

    async def _repair_result_json(self, result_text: str) -> dict[str, Any] | None:
        repair = getattr(self.ai_service, "chat_completion", None)
        if not callable(repair):
            return None
        repaired_text = await repair(
            messages=[{
                "role": "user",
                "content": (
                    "将下面的分镜响应修复为合法 JSON。只能修复格式，不得增删或改写事实；"
                    "只输出 JSON 对象，不要输出 markdown 或解释。\n\n"
                    f"{result_text}"
                ),
            }],
            system_prompt=build_video_analysis_system(),
            temperature=0.1,
        )
        return normalize_json(repaired_text)

    def _owner_id(self, record: Any) -> str:
        return self.account_id or self.user_id or str(getattr(record, "user_id", "") or "")

    def _log_stage_duration(
        self,
        stage: str,
        started_at: float,
        *,
        segment_count: int | None = None,
    ) -> None:
        logger.info(
            "video analysis stage completed workflow_id=%s stage=%s duration_ms=%s segment_count=%s",
            self.workflow_id,
            stage,
            max(int((perf_counter() - started_at) * 1000), 0),
            segment_count if segment_count is not None else "",
        )


def _segment_time_range(segment: VideoAudioSegment) -> str:
    return (
        f"{format_video_timestamp(segment.start_seconds)}-"
        f"{format_video_timestamp(segment.start_seconds + segment.duration_seconds)}"
    )


def _url_host(value: Any) -> str:
    match = re.match(r"^https?://([^/]+)", str(value or "").strip(), re.IGNORECASE)
    return match.group(1) if match else ""


def _exception_message_simple(exc: BaseException) -> str:
    original = getattr(exc, "orig", None)
    if original is not None:
        message = str(original).strip()
        if message:
            return message
    return str(exc).strip() or exc.__class__.__name__


def to_schema(record: Any) -> VideoAnalysisWorkflowSchema:
    return VideoAnalysisWorkflowSchema(
        id=record.id,
        type=record.type,
        accountId=record.account_id,
        creationId=record.creation_id,
        status=record.status,
        progress=record.progress,
        currentStage=record.current_stage,
        sourceUrl=record.source_url,
        videoUrl=record.video_url,
        coverUrl=record.cover_url,
        platform=record.platform,
        title=record.title,
        description=record.description,
        inputPayload=record.input_payload or {},
        resultPayload=normalize_video_analysis_result(record.result_payload or {}),
        error=record.error,
        createdAt=record.created_at,
        updatedAt=record.updated_at,
    )
