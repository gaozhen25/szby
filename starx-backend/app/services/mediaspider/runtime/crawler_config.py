"""平台运行配置默认值与 asyncio 任务级隔离。

平台代码继续通过模块属性读取配置；``CrawlerConfigScope`` 绑定后，当前任务及其
子任务读取和修改的是独立配置，不会与其他平台的并发任务串线。
"""

from __future__ import annotations

import sys
from contextvars import ContextVar, Token
from types import ModuleType
from typing import Any

PLATFORM = "xhs"
LOGIN_TYPE = "cookie"
CRAWLER_TYPE = "search"
START_PAGE = 1
KEYWORDS = ""
ENABLE_GET_COMMENTS = True
ENABLE_GET_SUB_COMMENTS = False
HEADLESS = True
CDP_HEADLESS = True
SAVE_DATA_OPTION = "memory"
COOKIES = ""
CRAWLER_MAX_COMMENTS_COUNT_SINGLENOTES = 10
CRAWLER_MAX_NOTES_COUNT = 30
MAX_CONCURRENCY_NUM = 1
ENABLE_IP_PROXY = False
ENABLE_GET_MEIDAS = False
IP_PROXY_POOL_COUNT = 2
IP_PROXY_PROVIDER_NAME = "kuaidaili"
STATIC_PROXY_URL = ""
ENABLE_CDP_MODE = False
CDP_CONNECT_EXISTING = False
CDP_DEBUG_PORT = 9222
CUSTOM_BROWSER_PATH = ""
XHS_CREATOR_ID_LIST = []
DY_CREATOR_ID_LIST = []
KS_CREATOR_ID_LIST = []

# 三个平台原运行时直接读取的扩展配置。
CRAWLER_MAX_SLEEP_SEC = 5
PLAYWRIGHT_PROXY = None
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120 Safari/537.36"
ENABLE_GET_IMAGES = False
ENABLE_GET_VIDEOS = False
ENABLE_GET_CREATOR = True
ENABLE_GET_NOTE_DETAIL = True
DY_SPECIFIED_ID_LIST = []
KS_SPECIFIED_ID_LIST = []
XHS_SPECIFIED_NOTE_URL_LIST = []
XHS_SPECIFIED_ID_LIST = []
PUBLISH_TIME_TYPE = 0
CRAWLER_TYPE_SEARCH = "search"
SAVE_LOGIN_STATE = False
USER_DATA_DIR = "%s_user_data_dir"
CACHE_TYPE_MEMORY = "memory"
XHS_INTERNATIONAL = False
SORT_TYPE = "popularity_descending"
BROWSER_LAUNCH_TIMEOUT = 30
AUTO_CLOSE_BROWSER = True


_TASK_CONFIG: ContextVar[dict[str, Any] | None] = ContextVar(
    "mediaspider_task_config",
    default=None,
)


def bind_task_config(values: dict[str, Any]) -> Token:
    return _TASK_CONFIG.set(dict(values))


def reset_task_config(token: Token) -> None:
    _TASK_CONFIG.reset(token)


class _TaskConfigModule(ModuleType):
    """让现有 ``config.FIELD`` 调用透明读取当前任务的配置。"""

    def __getattribute__(self, name: str) -> Any:
        if name.isupper():
            task_values = _TASK_CONFIG.get()
            if task_values is not None and name in task_values:
                return task_values[name]
        return super().__getattribute__(name)

    def __setattr__(self, name: str, value: Any) -> None:
        if name.isupper():
            task_values = _TASK_CONFIG.get()
            if task_values is not None:
                task_values[name] = value
                return
        super().__setattr__(name, value)


sys.modules[__name__].__class__ = _TaskConfigModule
