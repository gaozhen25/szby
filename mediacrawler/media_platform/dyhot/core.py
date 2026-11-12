# -*- coding: utf-8 -*-
"""抖音热点宝爬虫：独立平台 dyhot。"""

from __future__ import annotations

import asyncio
import os
from typing import Dict, List, Optional

from playwright.async_api import async_playwright

import config
from media_platform.douyin.core import DouYinCrawler
from media_platform.douyin.exception import DataFetchError
from media_platform.douyin.field import PublishTimeType, SearchSortType
from media_platform.douyin.login import DouYinLogin
from media_platform.dyhot.client import DouHotClient
from proxy.proxy_ip_pool import IpInfoModel, create_ip_pool
from store import douyin as douyin_store
from tools import utils
from var import crawler_type_var, source_keyword_var


class DouHotCrawler(DouYinCrawler):
    """
    抖音热点宝独立平台。

    CLI: ``uv run main.py --platform dyhot --lt cookie|qrcode --save_data_option json``
    """

    dy_client: DouHotClient

    async def start(self) -> None:
        playwright_proxy_format, httpx_proxy_format = None, None
        if config.ENABLE_IP_PROXY:
            self.ip_proxy_pool = await create_ip_pool(
                config.IP_PROXY_POOL_COUNT, enable_validate_ip=True
            )
            ip_proxy_info: IpInfoModel = await self.ip_proxy_pool.get_proxy()
            playwright_proxy_format, httpx_proxy_format = utils.format_proxy_info(
                ip_proxy_info
            )

        async with async_playwright() as playwright:
            if config.ENABLE_CDP_MODE:
                utils.logger.info("[DouHotCrawler] 使用CDP模式启动浏览器")
                self.browser_context = await self.launch_browser_with_cdp(
                    playwright,
                    playwright_proxy_format,
                    None,
                    headless=config.CDP_HEADLESS,
                )
            else:
                utils.logger.info("[DouHotCrawler] 使用标准模式启动浏览器")
                chromium = playwright.chromium
                self.browser_context = await self.launch_browser(
                    chromium,
                    playwright_proxy_format,
                    user_agent=None,
                    headless=config.HEADLESS,
                )
                await self.browser_context.add_init_script(path="libs/stealth.min.js")

            self.context_page = await self.browser_context.new_page()
            # 独立平台固定 crawler_type=hotspot，便于落盘/词云路径一致
            config.CRAWLER_TYPE = "hotspot"
            crawler_type_var.set("hotspot")
            self.dy_client = await self.create_douyin_client(httpx_proxy_format)

            await self._prepare_douhot_login()
            await self.dy_client.update_cookies(
                browser_context=self.browser_context,
                urls=self.cookie_urls,
            )
            await self.crawl_search_hot_board()
            utils.logger.info("[DouHotCrawler.start] DouHot Crawler finished ...")

    async def create_douyin_client(self, httpx_proxy: Optional[str]) -> DouHotClient:
        cookie_str, cookie_dict = await utils.convert_browser_context_cookies(
            self.browser_context,
            urls=self.cookie_urls,
        )  # type: ignore
        return DouHotClient(
            proxy=httpx_proxy,
            headers={
                "User-Agent": await self.context_page.evaluate("() => navigator.userAgent"),
                "Cookie": cookie_str,
                "Host": "www.douyin.com",
                "Origin": "https://www.douyin.com/",
                "Referer": "https://www.douyin.com/",
                "Content-Type": "application/json;charset=UTF-8",
            },
            playwright_page=self.context_page,
            cookie_dict=cookie_dict,
            proxy_ip_pool=self.ip_proxy_pool,
        )

    async def _prepare_douhot_login(self) -> None:
        if config.LOGIN_TYPE == "cookie":
            if not (config.COOKIES or "").strip():
                raise DataFetchError(
                    "热点宝 cookie 模式需要提供 COOKIES：\n"
                    "  uv run python scripts/run_with_cookies.py dyhot --cookies '...'\n"
                    "  或: uv run main.py --platform dyhot --lt cookie --cookies '...'"
                )
            utils.logger.info(
                "[DouHotCrawler._prepare_douhot_login] cookie 注入后直达 douhot.douyin.com"
                "（不再先打开 www.douyin.com）"
            )
            login_obj = DouYinLogin(
                login_type="cookie",
                login_phone="",
                browser_context=self.browser_context,
                context_page=self.context_page,
                cookie_str=config.COOKIES,
            )
            await login_obj.begin()
            await self.context_page.goto(
                "https://douhot.douyin.com/",
                wait_until="domcontentloaded",
                timeout=60000,
            )
            await self.dy_client.ensure_douhot_page(wait_rounds=20)
            return

        utils.logger.info(
            "[DouHotCrawler._prepare_douhot_login] 打开 douhot.douyin.com，"
            "请在浏览器完成热点宝登录（也可用 --lt cookie --cookies '...'）"
        )
        await self.context_page.goto(
            "https://douhot.douyin.com/",
            wait_until="domcontentloaded",
            timeout=60000,
        )
        await self.dy_client.ensure_douhot_page()

    async def crawl_search_hot_board(self) -> None:
        utils.logger.info("[DouHotCrawler.crawl_search_hot_board] Begin crawl douhot search hot board")
        page_size = int(getattr(config, "DY_HOTSPOT_PAGE_SIZE", 10) or 10)
        sub_type = int(getattr(config, "DY_HOTSPOT_SUB_TYPE", 3001) or 3001)
        date_window = int(getattr(config, "DY_HOTSPOT_DATE_WINDOW", 24) or 24)
        max_count = int(getattr(config, "DY_HOTSPOT_MAX_COUNT", 100) or 100)

        collected: List[Dict] = []
        page_num = 1
        total_count = None

        while len(collected) < max_count:
            resp = await self.dy_client.get_search_hot_board(
                page_num=page_num,
                page_size=page_size,
                sub_type=sub_type,
                date_window=date_window,
            )
            data = resp.get("data") or {}
            if total_count is None:
                total_count = data.get("total_count")
            search_list = data.get("search_list") or []
            if not search_list:
                utils.logger.info(
                    f"[DouHotCrawler.crawl_search_hot_board] empty page={page_num}, stop"
                )
                break

            for item in search_list:
                if len(collected) >= max_count:
                    break
                rank = len(collected) + 1
                collected.append(
                    {
                        "rank": rank,
                        "key_word": item.get("key_word") or "",
                        "search_score": item.get("search_score"),
                        "trends": item.get("trends") or [],
                        "sub_type": sub_type,
                        "date_window": date_window,
                        "last_modify_ts": utils.get_current_timestamp(),
                    }
                )

            utils.logger.info(
                f"[DouHotCrawler.crawl_search_hot_board] page={page_num} "
                f"got={len(search_list)} total_collected={len(collected)} board_total={total_count}"
            )
            if len(collected) >= max_count:
                break
            page_num += 1
            await asyncio.sleep(config.CRAWLER_MAX_SLEEP_SEC)

        meta = {
            "sub_type": sub_type,
            "date_window": date_window,
            "page_size": page_size,
            "total_count": total_count,
            "fetched_count": len(collected),
        }
        await douyin_store.save_search_hot_board(items=collected, meta=meta)
        utils.logger.info(
            f"[DouHotCrawler.crawl_search_hot_board] done, saved {len(collected)} items"
        )

        # 临时关闭：按热点关键词跟搜抖音 + 评论词云
        # if getattr(config, "DY_HOTSPOT_FOLLOW_SEARCH", False):
        #     await self.follow_search_hot_keywords(collected, meta=meta)

    async def follow_search_hot_keywords(
        self,
        board_items: List[Dict],
        meta: Optional[Dict] = None,
    ) -> None:
        from tools.async_file_writer import AsyncFileWriter
        from tools.words import AsyncWordCloudGenerator

        top_n = int(getattr(config, "DY_HOTSPOT_SEARCH_TOP_N", 10) or 0)
        targets = board_items if top_n <= 0 else board_items[:top_n]
        notes_per_kw = int(getattr(config, "DY_HOTSPOT_SEARCH_NOTES_COUNT", 10) or 10)
        if notes_per_kw < 10:
            notes_per_kw = 10

        utils.logger.info(
            f"[DouHotCrawler.follow_search_hot_keywords] begin, keywords={len(targets)}, "
            f"notes_per_kw={notes_per_kw}"
        )

        await self.context_page.goto(
            self.index_url, wait_until="domcontentloaded", timeout=60000
        )
        if not await self.dy_client.pong(browser_context=self.browser_context):
            login_obj = DouYinLogin(
                login_type=config.LOGIN_TYPE,
                login_phone="",
                browser_context=self.browser_context,
                context_page=self.context_page,
                cookie_str=config.COOKIES,
            )
            await login_obj.begin()
            await self.dy_client.update_cookies(
                browser_context=self.browser_context,
                urls=self.cookie_urls,
            )

        prev_comments = config.ENABLE_GET_COMMENTS
        config.ENABLE_GET_COMMENTS = True
        word_gen = AsyncWordCloudGenerator()
        hotspot_dir = getattr(config, "DY_HOTSPOT_DATA_DIR", "dyhot") or "dyhot"
        if config.SAVE_DATA_PATH:
            words_base = f"{config.SAVE_DATA_PATH}/{hotspot_dir}/words"
        else:
            words_base = f"data/{hotspot_dir}/words"
        os.makedirs(words_base, exist_ok=True)

        try:
            for item in targets:
                keyword = (item.get("key_word") or "").strip()
                if not keyword:
                    continue
                utils.logger.info(
                    f"[DouHotCrawler.follow_search_hot_keywords] "
                    f"#{item.get('rank')} search keyword={keyword!r}"
                )
                try:
                    comment_texts = await self._search_keyword_collect_comments(
                        keyword=keyword,
                        max_notes=notes_per_kw,
                    )
                except Exception as exc:
                    utils.logger.error(
                        f"[DouHotCrawler.follow_search_hot_keywords] search failed "
                        f"keyword={keyword!r}: {exc}"
                    )
                    comment_texts = []

                item["comment_count"] = len(comment_texts)
                if not comment_texts:
                    utils.logger.warning(
                        f"[DouHotCrawler.follow_search_hot_keywords] "
                        f"no comments for keyword={keyword!r}"
                    )
                    continue

                safe_kw = AsyncFileWriter.sanitize_filename(keyword, default="hot_keyword")
                prefix = (
                    f"{words_base}/hotspot_{item.get('rank')}_{safe_kw}_{utils.get_current_date()}"
                )
                try:
                    png_path = await word_gen.generate_word_frequency_and_cloud(
                        [{"content": t} for t in comment_texts],
                        prefix,
                    )
                except Exception as exc:
                    utils.logger.error(
                        f"[DouHotCrawler.follow_search_hot_keywords] wordcloud failed "
                        f"keyword={keyword!r}: {exc}"
                    )
                    png_path = None

                if png_path:
                    item["wordcloud_path"] = png_path
                    utils.logger.info(
                        f"[DouHotCrawler.follow_search_hot_keywords] "
                        f"wordcloud ok keyword={keyword!r} comments={len(comment_texts)} -> {png_path}"
                    )

                await asyncio.sleep(config.CRAWLER_MAX_SLEEP_SEC)
        finally:
            config.ENABLE_GET_COMMENTS = prev_comments

        await douyin_store.save_search_hot_board(items=board_items, meta=meta or {})
        utils.logger.info(
            "[DouHotCrawler.follow_search_hot_keywords] refreshed board json/html with wordclouds"
        )

    async def _search_keyword_collect_comments(
        self,
        keyword: str,
        max_notes: int = 10,
    ) -> List[str]:
        source_keyword_var.set(keyword)
        dy_limit_count = 10
        page = 0
        dy_search_id = ""
        comment_texts: List[str] = []
        collected_awemes = 0

        async def _comment_cb(aweme_id: str, comments: List[Dict]) -> None:
            await douyin_store.batch_update_dy_aweme_comments(aweme_id, comments)
            for c in comments or []:
                text = (c.get("text") or "").strip()
                if text:
                    comment_texts.append(text)

        while collected_awemes < max_notes:
            try:
                posts_res = await self.dy_client.search_info_by_keyword(
                    keyword=keyword,
                    offset=page * dy_limit_count,
                    # 热点宝跟搜固定：最多点赞 + 一周内（不用普通 dy 的无筛选默认）
                    sort_type=SearchSortType(
                        getattr(config, "DY_HOTSPOT_SEARCH_SORT_TYPE", 1)
                    ),
                    publish_time=PublishTimeType(
                        getattr(config, "DY_HOTSPOT_SEARCH_PUBLISH_TIME", 7)
                    ),
                    search_id=dy_search_id,
                )
            except DataFetchError as exc:
                utils.logger.error(
                    f"[DouHotCrawler._search_keyword_collect_comments] keyword={keyword!r} failed: {exc}"
                )
                break

            page += 1
            if not posts_res or not posts_res.get("data"):
                break
            dy_search_id = posts_res.get("extra", {}).get("logid", "")
            page_aweme_ids: List[str] = []
            for post_item in posts_res.get("data") or []:
                if collected_awemes >= max_notes:
                    break
                try:
                    aweme_info: Dict = (
                        post_item.get("aweme_info")
                        or post_item.get("aweme_mix_info", {}).get("mix_items")[0]
                    )
                except (TypeError, IndexError):
                    continue
                aweme_id = aweme_info.get("aweme_id") or ""
                if not aweme_id:
                    continue
                page_aweme_ids.append(aweme_id)
                collected_awemes += 1
                await douyin_store.update_douyin_aweme(aweme_item=aweme_info)

            if not page_aweme_ids:
                break

            semaphore = asyncio.Semaphore(config.MAX_CONCURRENCY_NUM)
            tasks = [
                asyncio.create_task(
                    self._get_comments_with_callback(aweme_id, semaphore, _comment_cb),
                    name=aweme_id,
                )
                for aweme_id in page_aweme_ids
            ]
            if tasks:
                await asyncio.wait(tasks)

            await asyncio.sleep(config.CRAWLER_MAX_SLEEP_SEC)

        return comment_texts

    async def _get_comments_with_callback(
        self,
        aweme_id: str,
        semaphore: asyncio.Semaphore,
        callback,
    ) -> None:
        async with semaphore:
            try:
                await self.dy_client.get_aweme_all_comments(
                    aweme_id=aweme_id,
                    crawl_interval=config.CRAWLER_MAX_SLEEP_SEC,
                    is_fetch_sub_comments=config.ENABLE_GET_SUB_COMMENTS,
                    callback=callback,
                    max_count=config.CRAWLER_MAX_COMMENTS_COUNT_SINGLENOTES,
                )
                await asyncio.sleep(config.CRAWLER_MAX_SLEEP_SEC)
            except DataFetchError as e:
                utils.logger.error(
                    f"[DouHotCrawler._get_comments_with_callback] aweme_id={aweme_id} failed: {e}"
                )
