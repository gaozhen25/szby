"""爬虫公开失败目录；所有对外文案只能从这里生成。"""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from .models import CrawlerFailure


_FAILURE_CATALOG = {
    "credentials_missing": (
        "未配置该平台登录凭证",
        "请配置该平台登录凭证并重启服务",
    ),
    "credentials_expired": (
        "登录凭证失效或未生效",
        "请更新平台登录凭证后重试",
    ),
    "creator_url_invalid": (
        "博主主页链接无效或账号不存在",
        "请在账号档案填写真实完整主页链接",
    ),
    "platform_blocked": (
        "平台触发访问验证，暂时无法采集",
        "请稍后重试或检查运行环境",
    ),
    "browser_timeout": ("平台页面响应超时", "请稍后重试"),
    "runtime_incompatible": (
        "平台采集组件不兼容",
        "请修复或升级采集组件后重试",
    ),
    "provider_rate_limited": (
        "数据服务请求过于频繁",
        "请稍后重试",
    ),
    "provider_request_invalid": (
        "数据服务拒绝了检索参数",
        "请检查检索条件或稍后重试",
    ),
    "provider_budget_exhausted": (
        "数据服务额度不足",
        "请补充服务额度后重试",
    ),
    "provider_unavailable": (
        "数据服务暂时不可用",
        "请稍后重试",
    ),
    "crawler_failed": ("平台采集失败", "请稍后重试"),
}


def public_crawler_failure(code: Any) -> CrawlerFailure:
    """按稳定 code 返回全新公开失败；非法 code 安全降级。"""

    safe_code = str(code or "")
    if safe_code not in _FAILURE_CATALOG:
        safe_code = "crawler_failed"
    message, suggestion = _FAILURE_CATALOG[safe_code]
    return CrawlerFailure.model_validate(
        {"code": safe_code, "message": message, "suggestion": suggestion}
    )


def normalize_public_failure(failure: Any) -> CrawlerFailure:
    """只信任重新验证后的 code，忽略调用方提供的文案。"""

    value = (
        failure.model_dump()
        if isinstance(failure, CrawlerFailure)
        else {
            "code": getattr(failure, "code", None),
            "message": getattr(failure, "message", None),
            "suggestion": getattr(failure, "suggestion", None),
        }
    )
    try:
        code = CrawlerFailure.model_validate(value).code
    except ValidationError:
        code = "crawler_failed"
    return public_crawler_failure(code)
