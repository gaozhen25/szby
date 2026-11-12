"""账号报告 workflow 的通用 AI 调用基类。"""

from __future__ import annotations

import asyncio

from app.core.logging import get_logger
from app.services.account_report.ai_service import (
    ACCOUNT_REPORT_AI_TIMEOUT_SECONDS,
    ACCOUNT_REPORT_LLM_EXTRA_BODY,
    resolve_account_report_llm_model,
)
from app.services.workflow.workflows.base import BaseWorkflow

logger = get_logger(__name__)


class BaseAccountReportWorkflow(BaseWorkflow):
    """统一账号报告 AI 调用参数、日志与空响应校验。"""

    async def _complete(self, prompt: str, *, stage: str) -> str:
        model = resolve_account_report_llm_model(stage)
        # 略大于 httpx 超时，优先让底层超时返回，再兜底取消
        timeout = max(float(ACCOUNT_REPORT_AI_TIMEOUT_SECONDS), 30.0) + 15.0
        try:
            result = await asyncio.wait_for(
                self.ai_service.chat_completion(
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.2,
                    model=model,
                    extra_body=ACCOUNT_REPORT_LLM_EXTRA_BODY,
                ),
                timeout=timeout,
            )
        except asyncio.TimeoutError as exc:
            logger.warning(
                "account_report ai_timeout workflow_id=%s stage=%s model=%s "
                "timeout_seconds=%s",
                self.workflow_id,
                stage,
                model,
                timeout,
            )
            raise TimeoutError(
                f"账号报告 AI 超时（{stage}，{int(timeout)}s），请重试"
            ) from exc
        content = str(result or "")
        logger.info(
            "account_report ai_response workflow_id=%s stage=%s model=%s "
            "response_length=%s response=%s",
            self.workflow_id,
            stage,
            model,
            len(content),
            content,
        )
        if not content.strip():
            raise ValueError("AI 服务未返回有效结果")
        return content
