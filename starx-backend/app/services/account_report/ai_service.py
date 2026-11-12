"""账号报告专用 AI 服务。"""

from app.services.ai_service import AIService

# 画像 / 违禁词等质量优先分块
ACCOUNT_REPORT_LLM_MODEL = "qwen3.6-plus"
# 相似博主 / 爆款 / 选题等调用量大、可接受更快模型的分块
ACCOUNT_REPORT_FAST_LLM_MODEL = "qwen-flash"
# 关闭 thinking（兼容 qwen 类模板）；其它模型忽略未知字段通常无害
ACCOUNT_REPORT_LLM_EXTRA_BODY = {
    "enable_thinking": False,
    "chat_template_kwargs": {"enable_thinking": False},
}
# 单次分块调用上限：避免沿用全局 DEFAULT_TIMEOUT 过长导致分块“假死”
ACCOUNT_REPORT_AI_TIMEOUT_SECONDS = 180.0

account_report_ai_service = AIService(
    llm_model=ACCOUNT_REPORT_LLM_MODEL,
    timeout_seconds=ACCOUNT_REPORT_AI_TIMEOUT_SECONDS,
)


def resolve_account_report_llm_model(stage: str | None = None) -> str:
    """按调用阶段选择账号报告模型。

    - 用户画像、违禁词：质量模型
    - 相似博主、爆款：快速模型
    - 其余（如关键词规划）默认走质量模型
    """

    text = str(stage or "").strip()
    if text.startswith("report_analysis.hotContents"):
        return ACCOUNT_REPORT_FAST_LLM_MODEL
    if text.startswith("benchmark_"):
        return ACCOUNT_REPORT_FAST_LLM_MODEL
    return ACCOUNT_REPORT_LLM_MODEL
