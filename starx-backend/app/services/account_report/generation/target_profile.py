"""仅依据账号档案与知识库生成目标用户画像。"""

from __future__ import annotations

from typing import Protocol

from app.core.logging import get_logger

from ..domain.models import TargetUserProfile
from .sections import (
    build_report_section_retry_prompt,
    build_target_user_profile_prompt,
    get_report_section_spec,
    parse_report_section,
)

logger = get_logger(__name__)


class ProfileCompletion(Protocol):
    async def __call__(self, prompt: str, *, stage: str) -> str: ...


async def generate_target_user_profile(
    *,
    complete: ProfileCompletion,
    ai_context: dict[str, object],
    workflow_id: str,
) -> TargetUserProfile:
    """执行画像专项 AI 调用，并在结构校验失败时重试一次。"""

    spec = get_report_section_spec("targetUserProfile")
    prompt = build_target_user_profile_prompt(spec, ai_context)
    raw = await complete(prompt, stage="report_analysis.targetUserProfile")
    try:
        return parse_report_section(raw, spec)
    except ValueError as exc:
        logger.warning(
            "account_report section validation failed; retrying "
            "workflow_id=%s section=%s error=%s",
            workflow_id,
            spec.key,
            str(exc),
        )
        retry_raw = await complete(
            build_report_section_retry_prompt(prompt, spec),
            stage="report_analysis.targetUserProfile.retry",
        )
        return parse_report_section(retry_raw, spec)
