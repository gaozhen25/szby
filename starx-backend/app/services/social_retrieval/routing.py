"""按平台选择社媒采集实现，避免业务服务直接判断 Provider。"""

from __future__ import annotations

from enum import Enum
from typing import Any


MEDIASPIDER_PLATFORMS = frozenset({"dy", "xhs"})


class RetrievalMode(str, Enum):
    TIKHUB = "tikhub"
    MEDIASPIDER = "mediaspider"
    HYBRID = "hybrid"


class RetrievalBackend(str, Enum):
    TIKHUB = "tikhub"
    MEDIASPIDER = "mediaspider"


def normalize_retrieval_mode(value: Any) -> RetrievalMode:
    if isinstance(value, RetrievalMode):
        return value
    normalized = str(value or "").strip().lower()
    if normalized == "legacy":
        # 旧配置原本表示内嵌 MediaSpider。新版不再让快手进入已下线的实现，
        # 因此兼容映射到混合路由。
        return RetrievalMode.HYBRID
    try:
        return RetrievalMode(normalized)
    except ValueError:
        return RetrievalMode.TIKHUB


def backend_for_platform(settings_or_mode: Any, platform: str) -> RetrievalBackend:
    """返回指定平台实际使用的采集后端。

    MediaSpider 当前只覆盖抖音和小红书；即使配置为 mediaspider，快手也保留
    TikHub，避免把已知不支持的平台送入 HTTP 采集器。
    """

    configured = getattr(
        settings_or_mode,
        "social_retrieval_provider",
        (
            settings_or_mode
            if isinstance(settings_or_mode, (str, RetrievalMode))
            else RetrievalMode.HYBRID.value
        ),
    )
    mode = normalize_retrieval_mode(configured)
    platform_code = str(platform or "").strip().lower()
    if mode != RetrievalMode.TIKHUB and platform_code in MEDIASPIDER_PLATFORMS:
        return RetrievalBackend.MEDIASPIDER
    return RetrievalBackend.TIKHUB
