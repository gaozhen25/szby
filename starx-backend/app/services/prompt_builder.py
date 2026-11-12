"""
Prompt 构建层。

所有业务代码需要拼装 prompt 时都应调用本模块中的函数，而非直接拼接字符串。
模板字符串本身定义在 prompt_template 中，本模块只负责用上下文数据填充占位符。
"""

from __future__ import annotations

import json
from typing import Any

from app.services import prompt_template as pt


def build_report_section_prompt(*, section_key: str, account_context: dict[str, object]) -> str:
    """构建账号运营报告单模块分析 prompt。"""
    label = pt.REPORT_SECTION_LABELS.get(section_key, section_key)
    return pt.REPORT_SECTION_ANALYSIS.format(
        section_label=label,
        account_name=account_context.get("name", ""),
        account_type=account_context.get("type", ""),
        account_description=account_context.get("description", ""),
        account_purpose=account_context.get("purpose", ""),
    )


def build_domain_image_followup_prompt(
    *,
    domain_name: str,
    generic_summary: str,
    visible_text: str,
    current_state_summary: str,
    recent_dialogue: str,
) -> str:
    """构建领域图片二次理解 prompt。"""
    return pt.DOMAIN_IMAGE_FOLLOWUP.format(
        domain_name=domain_name or "未明确",
        generic_summary=generic_summary or "未明确",
        visible_text=visible_text or "未明确",
        current_state_summary=current_state_summary or "未明确",
        recent_dialogue=recent_dialogue or "暂无最近上下文",
    )


def build_image_analysis_prompt(
    *,
    target_platform: str,
    topic_title: str | None,
    copy_text: str,
) -> str:
    """构建参考图片分析 prompt。"""
    return pt.IMAGE_ANALYSIS.format(
        target_platform=target_platform or "",
        topic_title=topic_title or "",
        copy_text=copy_text or "",
    )


def build_prompt_generation_system() -> str:
    """图片生成提示词的 system prompt。"""
    return pt.PROMPT_GENERATION_SYSTEM


def build_prompt_generation_user(
    *,
    target_platform: str,
    topic_title: str | None,
    copy_text: str,
    analyses: list[str],
) -> str:
    """构建图片生成提示词的 user message。"""
    return pt.PROMPT_GENERATION_USER.format(
        target_platform=target_platform or "",
        topic_title=topic_title or "",
        copy_text=copy_text or "",
        analyses="\n".join(analyses),
    )


def build_reverse_image_prompt(
    *,
    target_platform: str,
    title: str,
    description: str,
) -> str:
    """构建图文反推提示词，并固定要求模型使用中文输出。"""
    return pt.REVERSE_IMAGE_PROMPT.format(
        target_platform=target_platform or "未指定",
        title=title or "无",
        description=description or "无",
    )


def build_video_analysis_system() -> str:
    """视频解析的 system prompt。"""
    return pt.VIDEO_ANALYSIS_SYSTEM


def build_script_rewrite_system() -> str:
    """爆款脚本改写的 system prompt。"""
    return pt.SCRIPT_REWRITE_SYSTEM


def build_script_rewrite_user(
    *,
    target_platform: str,
    topic_title: str | None,
    copy_text: str,
    original_script: list[str],
) -> str:
    """构建爆款脚本改写的 user message。"""
    script_text = "\n".join(original_script) if original_script else "（暂无原版脚本，请根据文案要点自行补充）"
    return pt.SCRIPT_REWRITE_USER.format(
        target_platform=target_platform or "",
        topic_title=topic_title or "",
        copy_text=copy_text or "",
        original_script=script_text,
    )


def build_video_analysis_user(record: Any) -> str:
    """构建视频解析的 user message，从 WorkflowRecord 提取字段。"""
    input_payload = record.input_payload or {}
    hashtags = ", ".join(input_payload.get("hashtags") or []) or "无"
    return pt.VIDEO_ANALYSIS_USER.format(
        platform=record.platform or "未知",
        title=record.title or "无",
        description=record.description or "无",
        source_url=record.source_url or "无",
        video_url=record.video_url or "无",
        cover_url=record.cover_url or "无",
        hashtags=hashtags,
    )


def build_video_audio_storyboard_user(
    record: Any,
    *,
    audio_url: str,
    duration: str,
    audio_timeline: list[dict[str, Any]],
) -> str:
    """构建基于真实音轨和绝对时间轴的分镜生成 prompt。"""
    input_payload = record.input_payload or {}
    hashtags = ", ".join(input_payload.get("hashtags") or []) or "无"
    return pt.VIDEO_AUDIO_STORYBOARD_USER.format(
        platform=record.platform or "未知",
        title=record.title or "无",
        description=record.description or "无",
        source_url=record.source_url or "无",
        cover_url=record.cover_url or "无",
        hashtags=hashtags,
        audio_url=audio_url,
        duration=duration,
        audio_timeline=json.dumps(audio_timeline, ensure_ascii=False),
    )
