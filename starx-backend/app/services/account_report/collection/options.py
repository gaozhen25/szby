"""账号报告专用的 MediaSpider 运行参数收敛。"""

from __future__ import annotations

from typing import Any

from app.services.social_retrieval import RetrievalBackend, backend_for_platform


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
    backend: RetrievalBackend | None = None,
) -> dict[str, object]:
    selected_backend = backend or backend_for_platform(runtime_settings, platform)
    if selected_backend == RetrievalBackend.TIKHUB:
        return {
            "max_notes_count": 8,
            "max_comments_count": max(
                int(runtime_settings.MEDIASPIDER_MAX_COMMENTS_COUNT), 1
            ),
            # MediaSpider HTTP 尚未覆盖评论；显式请求评论时由能力路由切到
            # TikHub，并只在该场景追加评论请求。
            "enable_comments": reference_comments,
            # 每个关键词只调用一次标准作品搜索；不为不同排序/类型重复付费。
            "reference_discovery": False,
            # 仅抖音相似账号补充主页详情；小红书和快手不追加账号请求。
            "hydrate_douyin_creator_details": platform == "dy",
            "max_creator_details": 8,
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
