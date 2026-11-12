"""Video analysis workflow."""

import asyncio
import re
from typing import Any

from app.core.logging import get_logger
from app.schemas.extract import VideoAnalysisWorkflowSchema
from app.services.extract_service.video_source_persistence import VideoSourcePersistenceService
from app.services.prompt_builder import build_video_analysis_system, build_video_analysis_user
from .base import BaseWorkflow, WorkflowRegister, normalize_json

VIDEO_ANALYSIS_EMPTY_RESULT: dict[str, Any] = {
    "videoScript": [],
    "shotBreakdown": [],
    "rewriteReferences": [],
    "publishCopy": "",
    "replicationPrompt": "",
}

logger = get_logger(__name__)


@WorkflowRegister.register
class VideoAnalysisWorkflow(BaseWorkflow):
    type = "video_analysis"

    def __init__(self, workflow_id: str, context: dict[str, Any] | None = None) -> None:
        super().__init__(workflow_id, context)
        ctx = context or {}
        self.video_url = str(ctx.get("video_url") or "")
        self.user_id = str(ctx.get("user_id") or "")
        self.account_id = ctx.get("account_id")

    async def execute(self) -> dict[str, Any]:
        record = self.store.get_workflow(self.workflow_id)
        video_url = self.video_url or str(getattr(record, "video_url", "") or "")
        if not video_url:
            raise ValueError("Video URL is required for video analysis.")

        user_prompt = build_video_analysis_user(record) if record else ""

        # 外部平台签名 URL 对模型服务经常不可达，先转存到自有 OSS。
        self.store.update_progress(self.workflow_id, progress=10, current_stage="video_persistence")
        persistence_service = self.context.get("_video_persistence_service") or VideoSourcePersistenceService(
            storage=self.storage,
        )
        try:
            persisted_video_url = await asyncio.to_thread(
                persistence_service.persist,
                video_url,
                source_url=str(getattr(record, "source_url", "") or ""),
                owner_id=self.account_id or self.user_id or str(getattr(record, "user_id", "") or ""),
            )
        except Exception as exc:
            raise ValueError(f"视频转存 OSS 失败：{_exception_message_simple(exc)}") from exc
        if persisted_video_url != video_url:
            logger.info(
                "video source persisted workflow_id=%s source_host=%s persisted_url=%s",
                self.workflow_id,
                _url_host(video_url),
                persisted_video_url,
            )
            self.store.update_video_url(self.workflow_id, persisted_video_url)
        video_url = persisted_video_url

        # ---- create step record ----
        step_id = self.store.create_step(
            workflow_id=self.workflow_id,
            user_id=self.user_id or getattr(record, "user_id", ""),
            account_id=self.account_id or getattr(record, "account_id", None),
            step_type="video_analysis",
            input_payload={"user_prompt": user_prompt, "video_url": video_url},
            group_key="video_analysis",
        )

        # ---- update progress: starting ----
        self.store.update_progress(self.workflow_id, progress=30, current_stage="video_analysis")

        # ---- execute ----
        try:
            self.store.mark_step_running(step_id)
            result_text = await self.ai_service.video_view(
                user_prompt=user_prompt,
                system_prompt=build_video_analysis_system(),
                video_url=video_url,
                temperature=0.35,
            )
            if result_text is None:
                raise ValueError("视频解析失败，AI 服务返回空结果，请检查视频链接是否可公开访问后重试")

            parsed = normalize_json(result_text)
            if parsed is None:
                logger.warning(
                    "video analysis JSON parse failed workflow_id=%s response_length=%s response_preview=%s",
                    self.workflow_id,
                    len(str(result_text)),
                    _diagnostic_preview(result_text),
                )
                result_text = await self.ai_service.video_view(
                    user_prompt=user_prompt,
                    system_prompt=(
                        build_video_analysis_system()
                        + " 上一次响应不是合法 JSON。本次只输出一个完整、可被标准 JSON 解析器解析的对象；"
                        "不要输出思考过程、代码块或对象之外的文字，并确保所有字符串正确转义。"
                    ),
                    video_url=video_url,
                    temperature=0.1,
                )
                parsed = normalize_json(result_text)
                if parsed is None:
                    logger.warning(
                        "video analysis JSON retry failed workflow_id=%s response_length=%s response_preview=%s",
                        self.workflow_id,
                        len(str(result_text or "")),
                        _diagnostic_preview(result_text),
                    )
                    raise ValueError("视频解析结果格式异常，AI 已自动重试，请稍后再试")

            result = normalize_video_analysis_result(parsed)
            self.store.mark_step_completed(step_id, result)

        except Exception as exc:
            self.store.mark_step_failed(step_id, _exception_message_simple(exc))
            raise

        # ---- update progress: done ----
        self.store.update_progress(self.workflow_id, progress=100, current_stage="completed")

        return result


def normalize_video_analysis_result(value: Any) -> dict[str, Any]:
    source = value if isinstance(value, dict) else {}
    return {
        "videoScript": _normalize_video_script(source.get("videoScript")),
        "shotBreakdown": _normalize_shot_breakdown(source.get("shotBreakdown")),
        "rewriteReferences": _normalize_rewrite_references(source.get("rewriteReferences")),
        "publishCopy": _text(source.get("publishCopy")),
        "replicationPrompt": str(source.get("replicationPrompt") or "").strip(),
    }


def _normalize_video_script(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    items: list[dict[str, str]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        time_range = str(item.get("timeRange") or item.get("time_range") or "").strip()
        text = str(item.get("text") or "").strip()
        if time_range or text:
            items.append({"timeRange": time_range, "text": text})
    return items


def _normalize_shot_breakdown(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    items: list[dict[str, Any]] = []
    for index, item in enumerate(value, start=1):
        if not isinstance(item, dict):
            continue
        items.append({
            "shot": _safe_int(item.get("shot"), index),
            "image": _text(item.get("image")),
            "timeRange": _text(item.get("timeRange") or item.get("time_range")),
            "script": _text(item.get("script")),
            "scriptRole": _text(item.get("scriptRole") or item.get("script_role")),
            "visualContent": _text(item.get("visualContent") or item.get("visual_content")),
            "visualRole": _text(item.get("visualRole") or item.get("visual_role")),
            "shotSizeCamera": _text(item.get("shotSizeCamera") or item.get("shot_size_camera")),
            "shootingTechnique": _text(item.get("shootingTechnique") or item.get("shooting_technique")),
            "bgmSound": _text(item.get("bgmSound") or item.get("bgm_sound")),
            "moodPace": _text(item.get("moodPace") or item.get("mood_pace")),
            "optimizationSuggestion": _text(item.get("optimizationSuggestion") or item.get("optimization_suggestion")),
        })
    return items


def _normalize_rewrite_references(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    items: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        script = item.get("script")
        if isinstance(script, list):
            script_lines = [_text(line) for line in script if _text(line)]
        else:
            script_lines = [_text(script)] if _text(script) else []
        items.append({"title": _text(item.get("title")), "rhythm": _text(item.get("rhythm")), "script": script_lines})
    return items


def _safe_int(value: Any, fallback: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return fallback


def _text(value: Any) -> str:
    return str(value or "").strip()


def _diagnostic_preview(value: Any, limit: int = 500) -> str:
    """Return a bounded preview while dropping URL query credentials."""
    text = str(value or "").replace("\r", "\\r").replace("\n", "\\n")
    text = re.sub(r"(https?://[^\s?\"']+)\?[^\s\"']+", r"\1?<redacted>", text)
    if len(text) <= limit * 2:
        return text
    return f"{text[:limit]}...<truncated>...{text[-limit:]}"


def _url_host(value: Any) -> str:
    match = re.match(r"^https?://([^/]+)", str(value or "").strip(), re.IGNORECASE)
    return match.group(1) if match else ""


def _exception_message_simple(exc: BaseException) -> str:
    original = getattr(exc, "orig", None)
    if original is not None:
        msg = str(original).strip()
        if msg:
            return msg
    msg = str(exc).strip()
    return msg or exc.__class__.__name__


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
