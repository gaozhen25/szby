"""账号报告专用的 MediaSpider 运行参数收敛。"""

from __future__ import annotations

from typing import Any


_CDP_PORT_OFFSETS = {
    "xhs": 0,
    "dy": 1,
    "ks": 2,
}


def _isolate_cdp_debug_port(options: dict[str, object], platform: str) -> None:
    """为账号报告的平台并发任务分配稳定且互不冲突的 CDP 端口。"""
    if not options.get("enable_cdp_mode") or options.get("cdp_connect_existing"):
        return

    offset = _CDP_PORT_OFFSETS.get(platform)
    if offset is None:
        return
    base_port = int(options.get("cdp_debug_port") or 9222)
    # 预留三个连续端口；当配置靠近端口上限时整体向前平移。
    port_range_start = min(base_port, 65535 - max(_CDP_PORT_OFFSETS.values()))
    options["cdp_debug_port"] = port_range_start + offset


def account_report_runtime_options(
    runtime_settings: Any,
    platform: str,
    *,
    reference_comments: bool = False,
) -> dict[str, object]:
    if getattr(runtime_settings, "social_retrieval_provider", "legacy") == "tikhub":
        return {
            "max_notes_count": max(
                int(runtime_settings.ACCOUNT_REPORT_MAX_NOTES_PER_KEYWORD), 1
            ),
            "max_comments_count": max(
                int(runtime_settings.MEDIASPIDER_MAX_COMMENTS_COUNT), 1
            ),
            "enable_comments": reference_comments,
            "reference_discovery": True,
        }
    options = dict(runtime_settings.mediaspider_runtime_options(platform))
    global_limit = max(int(options.get("max_notes_count") or 1), 1)
    report_limit = max(
        int(runtime_settings.ACCOUNT_REPORT_MAX_NOTES_PER_KEYWORD),
        1,
    )
    options["max_notes_count"] = min(global_limit, report_limit)
    options["enable_comments"] = reference_comments
    options["enable_sub_comments"] = (
        reference_comments and bool(options.get("enable_sub_comments"))
    )
    _isolate_cdp_debug_port(options, platform)
    return options
