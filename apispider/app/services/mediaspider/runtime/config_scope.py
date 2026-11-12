from __future__ import annotations

from typing import Any

from ..models import CrawlerRunConfig
from . import crawler_config

CREATOR_FIELDS = {
    "xhs": "XHS_CREATOR_ID_LIST",
    "dy": "DY_CREATOR_ID_LIST",
    "ks": "KS_CREATOR_ID_LIST",
}
DETAIL_FIELDS = {
    "xhs": "XHS_SPECIFIED_NOTE_URL_LIST",
    "dy": "DY_SPECIFIED_ID_LIST",
    "ks": "KS_SPECIFIED_ID_LIST",
}


class CrawlerConfigScope:
    def __init__(self, run_config: CrawlerRunConfig):
        self.run_config = run_config
        self._token = None

    def __enter__(self) -> "CrawlerConfigScope":
        self._token = crawler_config.bind_task_config(self._values())
        return self

    def __exit__(self, exc_type, exc, traceback) -> bool:
        if self._token is not None:
            crawler_config.reset_task_config(self._token)
            self._token = None
        return False

    def _values(self) -> dict[str, Any]:
        cfg = self.run_config
        values = {
            "PLATFORM": cfg.platform,
            "LOGIN_TYPE": cfg.login_type,
            "CRAWLER_TYPE": cfg.crawl_type,
            "START_PAGE": cfg.start_page,
            "KEYWORDS": ",".join(cfg.keywords),
            "ENABLE_GET_COMMENTS": cfg.enable_comments,
            "ENABLE_GET_SUB_COMMENTS": cfg.enable_sub_comments,
            "HEADLESS": cfg.headless,
            "CDP_HEADLESS": cfg.headless,
            "SAVE_DATA_OPTION": "memory",
            "COOKIES": cfg.cookies,
            "CRAWLER_MAX_COMMENTS_COUNT_SINGLENOTES": cfg.max_comments_count,
            "CRAWLER_MAX_NOTES_COUNT": cfg.max_notes_count,
            "MAX_CONCURRENCY_NUM": cfg.max_concurrency,
            "CRAWLER_MAX_SLEEP_SEC": cfg.max_sleep_sec,
            "ENABLE_IP_PROXY": cfg.enable_ip_proxy,
            "ENABLE_GET_MEIDAS": False,
            "IP_PROXY_POOL_COUNT": cfg.ip_proxy_pool_count,
            "IP_PROXY_PROVIDER_NAME": cfg.ip_proxy_provider,
            "STATIC_PROXY_URL": cfg.static_proxy_url,
            "ENABLE_CDP_MODE": cfg.enable_cdp_mode,
            "CDP_CONNECT_EXISTING": cfg.cdp_connect_existing,
            "CDP_DEBUG_PORT": cfg.cdp_debug_port,
            "CUSTOM_BROWSER_PATH": cfg.custom_browser_path,
        }
        for field in CREATOR_FIELDS.values():
            values[field] = []
        for field in DETAIL_FIELDS.values():
            values[field] = []
        if cfg.crawl_type == "creator" and cfg.creator_url:
            values[CREATOR_FIELDS[cfg.platform]] = [cfg.creator_url]
        if cfg.crawl_type == "detail" and cfg.content_url:
            values[DETAIL_FIELDS[cfg.platform]] = [cfg.content_url]
        return values
