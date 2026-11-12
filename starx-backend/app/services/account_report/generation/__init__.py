"""账号报告 AI 上下文、契约与生成器。"""

from .context import build_account_report_ai_context
from .sections import REPORT_SECTION_SPECS, ReportSectionSpec

__all__ = [
    "REPORT_SECTION_SPECS",
    "ReportSectionSpec",
    "build_account_report_ai_context",
]
