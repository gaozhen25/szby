"""将爬虫底层异常转换为安全、稳定的公开失败分类。"""

from .failure_catalog import public_crawler_failure
from .models import CrawlerAuthenticationError, CrawlerFailure


_SIGN_STATE_CONFLICT = (
    "build_payload_array got multiple values for argument 'sign_state'"
)
_XHSHOW_UNSUPPORTED_SIGNATURE = "不支持的 xhshow build_payload_array 签名"

_AUTH_MARKERS = (
    "cookie",
    "登录",
    "login",
    "未返回用户",
    "credentials",
)
_BLOCK_MARKERS = (
    "verify_check",
    "blocked",
    "风控",
    "platform_blocked",
)


def classify_crawler_error(platform: str, cause: BaseException) -> CrawlerFailure:
    """分类已知错误；返回值绝不包含原始异常文本。"""

    if isinstance(cause, CrawlerAuthenticationError):
        return public_crawler_failure("credentials_expired")

    try:
        from playwright.async_api import TimeoutError as PlaywrightTimeoutError
    except Exception:  # noqa: BLE001
        PlaywrightTimeoutError = ()  # type: ignore[misc, assignment]
    if PlaywrightTimeoutError and isinstance(cause, PlaywrightTimeoutError):
        return public_crawler_failure("browser_timeout")

    if (
        type(cause).__name__ in {"DataFetchError", "IPBlockError"}
        and ".platforms." in type(cause).__module__
    ):
        return public_crawler_failure("platform_blocked")
    if type(cause).__name__ == "ProcessExitedWithNonZeroStatus":
        return public_crawler_failure("runtime_incompatible")
    if isinstance(cause, TypeError) and _SIGN_STATE_CONFLICT in str(cause):
        return public_crawler_failure("runtime_incompatible")
    if (
        isinstance(cause, RuntimeError)
        and _XHSHOW_UNSUPPORTED_SIGNATURE in str(cause)
    ):
        return public_crawler_failure("runtime_incompatible")

    text = str(cause).lower()
    # 风控/验证页优先于笼统的 cookie/登录文案，避免 verify_check 被误报成凭证失效
    if any(marker.lower() in text for marker in _BLOCK_MARKERS):
        return public_crawler_failure("platform_blocked")
    if any(marker.lower() in text for marker in _AUTH_MARKERS):
        return public_crawler_failure("credentials_expired")
    return public_crawler_failure("crawler_failed")
