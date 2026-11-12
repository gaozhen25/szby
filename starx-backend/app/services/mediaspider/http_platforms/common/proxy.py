# -*- coding: utf-8 -*-
"""HTTP 爬虫共用：快代理短时复用租赁。"""

from __future__ import annotations

import logging
import sys
from typing import Dict, Optional

logger = logging.getLogger(__name__)


def lease_requests_proxies_sync(
    *,
    enabled: bool | None = None,
) -> Optional[Dict[str, str]]:
    """若开启代理，返回 requests 风格 proxies（默认 3 分钟内复用同一 IP）。"""
    from app.core.config import settings

    if enabled is None:
        enabled = bool(settings.MEDIASPIDER_ENABLE_IP_PROXY)
    if not enabled:
        return None

    from ...vendor.proxy import get_sticky_requests_proxies_sync, sticky_kdl_status

    proxies = get_sticky_requests_proxies_sync()
    status = sticky_kdl_status()
    if status:
        kind = "新提取" if status.get("is_new") else "复用"
        print(
            f"使用代理 {status['ip']}:{status['port']}（{kind}，剩余 {status['remaining_sec']}s）",
            file=sys.stderr,
        )
    return proxies


def resolve_requests_proxies(
    proxies: Optional[Dict[str, str]] = None,
    *,
    enabled: bool | None = None,
) -> Optional[Dict[str, str]]:
    """已有 proxies 则沿用；否则在开启 IP 代理时自动租赁，避免直连。"""
    if proxies:
        return proxies
    return lease_requests_proxies_sync(enabled=enabled)

