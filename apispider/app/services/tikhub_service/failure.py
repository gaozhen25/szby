"""将 TikHub 业务异常映射为安全的公开采集失败。"""

from __future__ import annotations

from app.services.mediaspider.failure_catalog import public_crawler_failure
from app.services.mediaspider.models import CrawlerFailure
from app.services.tikhub_service.errors import (
    InvalidTikHubRequestError,
    TikHubBusinessBudgetError,
    TikHubBusinessConfigError,
    TikHubBusinessRateLimitError,
    TikHubBusinessRequestError,
)


def classify_tikhub_failure(error: BaseException) -> CrawlerFailure | None:
    if isinstance(error, TikHubBusinessRateLimitError):
        return public_crawler_failure("provider_rate_limited")
    if isinstance(error, TikHubBusinessBudgetError):
        return public_crawler_failure("provider_budget_exhausted")
    if isinstance(error, InvalidTikHubRequestError):
        return public_crawler_failure("provider_request_invalid")
    if isinstance(error, TikHubBusinessConfigError):
        return public_crawler_failure("credentials_expired")
    if isinstance(error, TikHubBusinessRequestError):
        return public_crawler_failure("provider_unavailable")
    return None
