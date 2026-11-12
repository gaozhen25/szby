"""Custom exceptions for Boss CLI API client."""

from __future__ import annotations



class BossApiError(Exception):
    """Base exception for Boss Zhipin API errors."""

    def __init__(self, message: str, code: int | str | None = None, response: dict | None = None):
        super().__init__(message)
        self.code = code
        self.response = response


class SessionExpiredError(BossApiError):
    """Raised when __zp_stoken__ has expired (code=37)."""

    def __init__(self):
        super().__init__(
            "环境异常 (__zp_stoken__ 已过期)。请重新登录: boss logout && boss login",
            code=37,
        )


class IdentityMismatchError(BossApiError):
    """Raised when a recruiter API is called with a job-seeker session (code=24)."""

    def __init__(self):
        super().__init__(
            "当前是求职身份。请用招聘者账号扫码后再试: uv run boss logout && uv run boss login",
            code=24,
        )


class AuthRequiredError(BossApiError):
    """Raised when user is not logged in."""

    def __init__(self):
        super().__init__("未登录，请先使用 boss login 扫码登录")


class ParamError(BossApiError):
    """Raised when API reports missing or invalid parameters."""

    def __init__(self, message: str, code: int | None = None):
        super().__init__(f"参数错误: {message}", code=code)


class RateLimitError(BossApiError):
    """Raised when too many requests are made."""

    def __init__(self):
        super().__init__("请求过于频繁，请稍后再试")


def error_code_for_exception(exc: Exception) -> str:
    """Map domain exceptions to stable error code strings."""
    if isinstance(exc, (AuthRequiredError, SessionExpiredError, IdentityMismatchError)):
        return "not_authenticated"
    if isinstance(exc, RateLimitError):
        return "rate_limited"
    if isinstance(exc, ParamError):
        return "invalid_params"
    if isinstance(exc, BossApiError):
        return "api_error"
    return "unknown_error"
