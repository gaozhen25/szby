class TikHubBusinessError(RuntimeError):
    """TikHub 业务适配层异常基类。"""


class TikHubBusinessConfigError(TikHubBusinessError):
    """TikHub 凭证或配置不可用。"""


class TikHubBusinessRequestError(TikHubBusinessError):
    """TikHub 请求或响应处理失败。"""

    def __init__(self, message: str, *, request_id: str | None = None) -> None:
        super().__init__(message)
        self.request_id = request_id


class TikHubBusinessRateLimitError(TikHubBusinessRequestError):
    def __init__(
        self,
        message: str,
        *,
        retry_after: float | None = None,
        request_id: str | None = None,
    ) -> None:
        super().__init__(message, request_id=request_id)
        self.retry_after = retry_after


class TikHubBusinessBudgetError(TikHubBusinessRequestError):
    """TikHub 余额或预算不足。"""


class UnsupportedTikHubOperationError(TikHubBusinessError):
    """当前业务适配尚未实现该能力。"""


class InvalidTikHubRequestError(TikHubBusinessRequestError):
    """业务请求缺少必要标识或参数。"""
