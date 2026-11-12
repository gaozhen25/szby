from __future__ import annotations

from urllib.parse import urlparse

import requests

from app.services.extract_service.extract_service import UnsupportedPlatformError
from app.services.extract_service.profiles import (
    DouyinProfileExtractor,
    RednoteProfileExtractor,
)


class ProfileExtractService:
    """无登录态、无业务 Cookie 的公开博主主页解析入口。"""

    def __init__(self, session=None, timeout: int = 10, browser_renderer=None):
        self.session = session
        self.timeout = timeout
        self.browser_renderer = browser_renderer
        self.extractors = {
            "douyin": DouyinProfileExtractor,
            "rednote": RednoteProfileExtractor,
        }

    def extract(self, url: str, limit: int = 10) -> dict:
        bounded_limit = min(max(int(limit), 1), 50)
        platform = self.detect_platform(url)
        extractor = self.extractors[platform](
            url,
            limit=bounded_limit,
            session=self.session,
            timeout=self.timeout,
            browser_renderer=self.browser_renderer,
        )
        try:
            return extractor.extract().to_dict()
        except requests.RequestException as exc:
            from app.services.extract_service.platforms.base import ExtractError

            raise ExtractError("公开主页请求失败") from exc

    @staticmethod
    def detect_platform(url: str) -> str:
        parsed = urlparse(str(url or "").strip())
        hostname = (parsed.hostname or "").lower()
        parts = [part for part in parsed.path.split("/") if part]
        if (
            hostname == "douyin.com" or hostname.endswith(".douyin.com")
        ) and len(parts) >= 2 and parts[0] == "user":
            return "douyin"
        if (
            hostname == "xiaohongshu.com"
            or hostname.endswith(".xiaohongshu.com")
        ) and len(parts) >= 3 and parts[:2] == ["user", "profile"]:
            return "rednote"
        raise UnsupportedPlatformError(f"Unsupported creator profile url: {url}")


def extract_profile(
    url: str, limit: int = 10, session=None, timeout: int = 10
) -> dict:
    return ProfileExtractService(session=session, timeout=timeout).extract(url, limit=limit)
