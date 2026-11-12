"""账号报告可公开的非阻断采集提示。"""

from app.services.mediaspider.models import CrawlerFailure


def public_account_report_notice(code: str) -> CrawlerFailure:
    if code != "creator_url_invalid":
        raise ValueError("unsupported account report notice code")
    return CrawlerFailure(
        code="creator_url_invalid",
        message="当前账号主页链接无效，已跳过主页公开信息采集",
        suggestion="请在账号档案中填写该平台真实、完整的当前账号主页链接",
    )
