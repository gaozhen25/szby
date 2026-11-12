from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.services.extract_service.platforms.base import ExtractError


@dataclass(frozen=True)
class RenderedPublicPage:
    html: str
    url: str
    payloads: tuple[dict[str, Any], ...] = ()


class PublicBrowserRenderer:
    """使用全新临时浏览器上下文渲染公开页面，不注入或持久化登录状态。"""

    def render(self, url: str, *, timeout: int = 10) -> RenderedPublicPage:
        from playwright.sync_api import (
            Error as PlaywrightError,
            TimeoutError as PlaywrightTimeoutError,
            sync_playwright,
        )

        timeout_ms = max(int(timeout * 1000), 20_000)
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                try:
                    context = browser.new_context(
                        locale="zh-CN",
                        viewport={"width": 1440, "height": 1000},
                    )
                    try:
                        page = context.new_page()
                        payloads: list[dict[str, Any]] = []

                        def collect_public_payload(response) -> None:
                            if not any(
                                marker in response.url
                                for marker in (
                                    "/user/profile/other/",
                                    "/aweme/post/",
                                    "/aweme/v1/web/aweme/post",
                                    "/aweme/v1/web/user/profile/other",
                                )
                            ):
                                return
                            try:
                                payload = response.json()
                            except Exception:
                                # 部分风控响应状态为 200 但正文为空或非 JSON；
                                # 响应监听器只能忽略该响应，不能影响主页 DOM 解析。
                                return
                            if isinstance(payload, dict):
                                payloads.append(payload)

                        page.on("response", collect_public_payload)
                        try:
                            page.goto(url, wait_until="commit", timeout=timeout_ms)
                        except PlaywrightTimeoutError:
                            # 抖音匿名风控脚本会设置临时签名并自动重载；首次导航超时
                            # 不代表失败，继续等待公开资料节点即可。
                            pass
                        page.wait_for_selector(
                            '[data-e2e="user-info"]', timeout=timeout_ms
                        )
                        try:
                            page.wait_for_selector(
                                'img[alt*="头像"], img[src*="aweme-avatar"]',
                                timeout=3_000,
                            )
                        except PlaywrightTimeoutError:
                            pass
                        # 展开截断简介（「更多」），便于无 Cookie DOM 路径拿到完整签名。
                        try:
                            more = page.locator(
                                '[data-e2e="user-info"] >> text=更多'
                            ).first
                            if more.count():
                                more.click(timeout=1_500)
                                page.wait_for_timeout(400)
                        except PlaywrightTimeoutError:
                            pass
                        # 轻量滚动，尽量触发作品流请求（仍可能被匿名风控拦截）。
                        for _ in range(3):
                            page.mouse.wheel(0, 1800)
                            page.wait_for_timeout(800)
                        page.wait_for_timeout(1_500)
                        return RenderedPublicPage(
                            html=page.content(),
                            url=page.url,
                            payloads=tuple(payloads),
                        )
                    finally:
                        context.close()
                finally:
                    browser.close()
        except PlaywrightError as exc:
            raise ExtractError("公开主页浏览器渲染失败") from exc


__all__ = ["PublicBrowserRenderer", "RenderedPublicPage"]
