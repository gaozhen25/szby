# -*- coding: utf-8 -*-
"""抖音热点宝 API Client（继承抖音 Client，补充 douhot 接口）。"""

from __future__ import annotations

import asyncio
from typing import Dict

from media_platform.douyin.client import DouYinClient
from media_platform.douyin.exception import DataFetchError
from tools import utils

DOUHOT_HOST = "https://douhot.douyin.com"
HOT_SEARCH_QUERY_PATH = "/douhot/v1/dashboard/hot_search/query_list"


class DouHotClient(DouYinClient):
    """热点宝专用 Client：榜单接口走 douhot.douyin.com。"""

    async def ensure_douhot_page(self, wait_rounds: int = 90) -> None:
        """
        打开热点宝站点并确认仍在 douhot.douyin.com。

        Args:
            wait_rounds: 每轮 2s；Cookie 模式可传较小值以便快速失败
        """
        if not self.playwright_page:
            raise DataFetchError("playwright_page is required for douhot APIs")

        current = self.playwright_page.url or ""
        on_douhot = "douhot.douyin.com" in current
        on_oauth = "open.douyin.com" in current or "passport" in current
        if not on_douhot and not on_oauth:
            utils.logger.info("[DouHotClient.ensure_douhot_page] goto douhot.douyin.com ...")
            await self.playwright_page.goto(
                f"{DOUHOT_HOST}/",
                wait_until="domcontentloaded",
                timeout=60000,
            )
            await asyncio.sleep(2)

        final_url = self.playwright_page.url or ""
        utils.logger.info(f"[DouHotClient.ensure_douhot_page] final url: {final_url}")

        wait_rounds = max(1, int(wait_rounds))
        for i in range(wait_rounds):
            final_url = self.playwright_page.url or ""
            if "douhot.douyin.com" in final_url and "open.douyin.com" not in final_url:
                return
            if i == 0 or i % 10 == 0:
                utils.logger.warning(
                    "[DouHotClient.ensure_douhot_page] 当前不在热点宝域名 "
                    f"({final_url})。请在浏览器中完成「抖音热点宝」登录/授权，"
                    "并停留在 douhot.douyin.com 页面..."
                )
            await asyncio.sleep(2)

        raise DataFetchError(
            "无法停留在 douhot.douyin.com。"
            "热点宝通常需要单独登录或企业/机构权限；"
            "Cookie 请从已登录的 douhot.douyin.com 复制整段。"
            f" 最终页面: {self.playwright_page.url}"
        )

    async def get_search_hot_board(
        self,
        page_num: int = 1,
        page_size: int = 10,
        sub_type: int = 3001,
        date_window: int = 24,
    ) -> Dict:
        """
        搜索热点总榜

        POST https://douhot.douyin.com/douhot/v1/dashboard/hot_search/query_list
        body: {page_num, page_size, date_window, sub_type}
        """
        await self.ensure_douhot_page()
        payload = {
            "page_num": int(page_num),
            "page_size": int(page_size),
            "sub_type": int(sub_type),
            "date_window": int(date_window),
        }
        api_url = f"{DOUHOT_HOST}{HOT_SEARCH_QUERY_PATH}"
        utils.logger.info(
            f"[DouHotClient.get_search_hot_board] url={api_url} payload={payload}"
        )

        result = await self.playwright_page.evaluate(
            """async ({ url, body }) => {
                const resp = await fetch(url, {
                    method: 'POST',
                    headers: {
                        'Accept': 'application/json, text/plain, */*',
                        'Content-Type': 'application/json',
                        'Origin': 'https://douhot.douyin.com',
                        'Referer': 'https://douhot.douyin.com/',
                    },
                    credentials: 'include',
                    body: JSON.stringify(body),
                });
                const text = await resp.text();
                try {
                    return {
                        ok: resp.ok,
                        status: resp.status,
                        finalUrl: resp.url,
                        data: JSON.parse(text),
                    };
                } catch (e) {
                    const snippet = (text || '').slice(0, 200);
                    return {
                        ok: false,
                        status: resp.status,
                        finalUrl: resp.url,
                        data: { code: -1, message: snippet },
                    };
                }
            }""",
            {"url": api_url, "body": payload},
        )
        data = (result or {}).get("data") or {}
        code = data.get("code")
        message = data.get("message") or ""
        if isinstance(message, str) and ("<!doctype html>" in message.lower() or "<html" in message.lower()):
            raise DataFetchError(
                "热点宝接口返回了 HTML 页面而不是 JSON。"
                f" status={result.get('status')} finalUrl={result.get('finalUrl')} "
                "请确认浏览器地址栏在 https://douhot.douyin.com 且已登录热点宝。"
            )
        if code == 8 or data.get("data") == "用户未登录":
            raise DataFetchError("douhot 用户未登录，请先在浏览器中登录热点宝后再试")
        if code not in (0, None) and not (
            isinstance(data.get("data"), dict) and data["data"].get("search_list")
        ):
            raise DataFetchError(f"douhot hot_search failed: code={code} data={str(data)[:300]}")
        return data
