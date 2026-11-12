"""MediaSpider 对外模型与安全异常。"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class CrawlerServiceError(Exception):
    """爬虫服务基础异常。"""


class CrawlerAuthenticationError(CrawlerServiceError):
    """平台 Cookie 已失效；不保留可能含凭证的底层详情。"""

    def __init__(self, platform: str, _unsafe_detail: str = ""):
        super().__init__(f"平台 {platform} 登录凭证失效")
        self.platform = platform


class InvalidCrawlRequestError(CrawlerServiceError):
    """爬取参数不合法。"""


class UnsupportedPlatformError(InvalidCrawlRequestError):
    """平台代码、别名或 URL 域名不受支持。"""


class PlatformCode(str, Enum):
    XHS = "xhs"
    DOUYIN = "dy"
    KUAISHOU = "ks"


class LoginType(str, Enum):
    QRCODE = "qrcode"
    PHONE = "phone"
    COOKIE = "cookie"


class ProxyProvider(str, Enum):
    KUAIDAILI = "kuaidaili"
    WANDOUHTTP = "wandouhttp"
    STATIC = "static"


class CrawlerRunConfig(BaseModel):
    """一次爬取的完整配置；Cookie 永不进入序列化或 repr。"""

    model_config = ConfigDict(use_enum_values=True, extra="forbid")

    platform: PlatformCode
    crawl_type: Literal["search", "creator", "detail"]
    keywords: list[str] = Field(default_factory=list)
    creator_url: str | None = None
    content_url: str | None = None
    login_type: LoginType = LoginType.COOKIE
    start_page: int = Field(default=1, ge=1)
    enable_comments: bool = False
    enable_sub_comments: bool = False
    headless: bool = False
    cookies: str = Field(default="", exclude=True, repr=False)
    max_comments_count: int = Field(default=10, ge=1)
    max_notes_count: int = Field(default=60, ge=1)
    max_concurrency: int = Field(default=1, ge=1)
    max_detail_count: int | None = Field(default=None, ge=0)
    detail_concurrency: int = Field(default=1, ge=1, le=5)
    max_sleep_sec: float = Field(default=5, ge=0)
    enable_ip_proxy: bool = False
    ip_proxy_pool_count: int = Field(default=2, ge=1)
    ip_proxy_provider: ProxyProvider = ProxyProvider.KUAIDAILI
    static_proxy_url: str = ""
    enable_cdp_mode: bool = True
    cdp_connect_existing: bool = False
    cdp_debug_port: int = Field(default=9222, ge=1, le=65535)
    custom_browser_path: str = ""
    output_mode: Literal["memory"] = "memory"

    @model_validator(mode="after")
    def validate_cross_fields(self) -> "CrawlerRunConfig":
        if self.enable_comments or self.enable_sub_comments:
            raise InvalidCrawlRequestError("HTTP MediaSpider 暂不支持评论采集")
        if self.login_type == "cookie" and not self.cookies.strip():
            raise InvalidCrawlRequestError("Cookie 登录必须提供非空 cookies")
        if self.crawl_type == "search" and not self.keywords:
            raise InvalidCrawlRequestError("关键词模式至少需要一个关键词")
        if self.crawl_type == "creator" and not self.creator_url:
            raise InvalidCrawlRequestError("博主模式必须提供 creator_url")
        if self.crawl_type == "detail" and not self.content_url:
            raise InvalidCrawlRequestError("指定内容模式必须提供 content_url")
        if (
            self.enable_ip_proxy
            and self.ip_proxy_provider == "static"
            and not self.static_proxy_url.strip()
        ):
            raise InvalidCrawlRequestError("静态代理必须提供 static_proxy_url")
        return self


class CrawlResult(BaseModel):
    platform: str
    crawl_type: Literal["search", "creator", "detail"]
    keywords: list[str] = Field(default_factory=list)
    creator_url: str | None = None
    content_url: str | None = None
    contents: list[dict[str, Any]] = Field(default_factory=list)
    comments: list[dict[str, Any]] = Field(default_factory=list)
    creators: list[dict[str, Any]] = Field(default_factory=list)
    content_count: int = 0
    comment_count: int = 0
    creator_count: int = 0
    source_operations: list[str] = Field(default_factory=list)
    discovery_warnings: list[str] = Field(default_factory=list)


class CrawlerFailure(BaseModel):
    """可公开给调用方的稳定失败分类。"""

    code: Literal[
        "credentials_missing",
        "credentials_expired",
        "creator_url_invalid",
        "platform_blocked",
        "browser_timeout",
        "runtime_incompatible",
        "provider_rate_limited",
        "provider_request_invalid",
        "provider_budget_exhausted",
        "provider_unavailable",
        "crawler_failed",
    ]
    message: str
    suggestion: str


class CrawlerProgressEvent(BaseModel):
    """爬虫对外进度事件；字段采用白名单，禁止附带运行配置和原始记录。"""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    platform: str
    crawl_type: Literal["search", "creator", "detail"] = Field(alias="crawlType")
    action: Literal[
        "waiting_for_slot",
        "run_started",
        "keyword_started",
        "keyword_completed",
        "keyword_failed",
        "creator_started",
        "detail_started",
        "content_discovered",
        "creator_discovered",
        "comments_updated",
        "run_completed",
        "run_failed",
    ]
    status: Literal["pending", "running", "completed", "failed", "skipped"]
    message: str
    subject: str = ""
    content_title: str = Field(default="", alias="contentTitle", max_length=60)
    content_count: int = Field(default=0, alias="contentCount", ge=0)
    creator_count: int = Field(default=0, alias="creatorCount", ge=0)
    comment_count: int = Field(default=0, alias="commentCount", ge=0)


ProgressCallback = Callable[[CrawlerProgressEvent], Awaitable[None] | None]
PartialResultCallback = Callable[[CrawlResult], Awaitable[None] | None]


class CrawlerExecutionError(CrawlerServiceError):
    __slots__ = ("_recoverable_result",)

    def __init__(
        self,
        platform: str,
        cause: BaseException,
        partial_result: CrawlResult,
        *,
        failure: CrawlerFailure | None = None,
    ):
        # 底层 HTTP/浏览器异常可能包含请求头，公开异常文本不得回显它们。
        super().__init__(f"平台 {platform} 爬取失败")
        self.platform = platform
        self.cause_type = type(cause).__name__
        self.cause_exit_status = (
            int(cause.status)
            if type(cause).__name__ == "ProcessExitedWithNonZeroStatus"
            and isinstance(getattr(cause, "status", None), int)
            else None
        )
        stderr = str(getattr(cause, "stderr", "") or "").lower()
        self.cause_diagnostic = next(
            (
                category
                for marker, category in (
                    ("heap out of memory", "node_heap_exhausted"),
                    ("reached heap limit", "node_heap_exhausted"),
                    ("pthread_create", "node_thread_create_failed"),
                    ("resource temporarily unavailable", "process_resource_exhausted"),
                    ("eagain", "process_resource_exhausted"),
                    ("syntaxerror", "javascript_syntax_error"),
                    ("referenceerror", "javascript_reference_error"),
                    ("typeerror", "javascript_type_error"),
                )
                if marker in stderr
            ),
            "empty_stderr" if not stderr else "unclassified_stderr",
        )
        from .failure_catalog import normalize_public_failure, public_crawler_failure

        self.failure = (
            normalize_public_failure(failure)
            if failure is not None
            else public_crawler_failure("crawler_failed")
        )
        # 完整记录只保存在私有 slot 中，避免进入异常 __dict__、日志或 API 响应。
        # 账号报告工作流可在严格数量门控后将其作为降级证据使用。
        self._recoverable_result = partial_result.model_copy(deep=True)
        self.partial_result = CrawlResult(
            platform=partial_result.platform,
            crawl_type=partial_result.crawl_type,
            content_count=partial_result.content_count,
            comment_count=partial_result.comment_count,
            creator_count=partial_result.creator_count,
        )

    def _recoverable_result_copy(self) -> CrawlResult:
        """仅供同进程工作流恢复已采集记录；对外摘要仍只有安全计数。"""

        return self._recoverable_result.model_copy(deep=True)
