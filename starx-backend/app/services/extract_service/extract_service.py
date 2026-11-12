from urllib.parse import urlparse

from app.services.extract_service.platforms.douyin import Douyin
from app.services.extract_service.platforms.feigua import Feigua
from app.services.extract_service.platforms.kuaishou import Kuaishou
from app.services.extract_service.platforms.rednote import Rednote
from app.services.extract_service.tikhub_fallback import TikHubExtractFallback


class UnsupportedPlatformError(ValueError):
    pass


class ExtractService:
    def __init__(self, session=None, timeout=10, tikhub_fallback=None):
        self.session = session
        self.timeout = timeout
        self.tikhub_fallback = (
            tikhub_fallback if tikhub_fallback is not None else TikHubExtractFallback()
        )
        self.extractors = {
            "rednote": Rednote,
            "douyin": Douyin,
            "feigua": Feigua,
            "kuaishou": Kuaishou,
        }

    def extract(self, url: str) -> dict:
        platform = self.detect_platform(url)
        extractor_cls = self.extractors[platform]
        try:
            return (
                extractor_cls(url, session=self.session, timeout=self.timeout)
                .extract()
                .to_dict()
            )
        except Exception as exc:
            if not self._can_fallback_to_tikhub(platform):
                raise
            try:
                result = self.tikhub_fallback.extract(platform=platform, url=url).to_dict()
            except Exception:
                raise exc from None
            result.setdefault("raw", {})
            result["raw"]["fallback_reason"] = str(exc)
            return result

    def extract_profile(self, url: str, limit: int = 10) -> dict:
        # 延迟导入，避免 profile_service 与本模块的公开异常类型形成导入环。
        from app.services.extract_service.profile_service import ProfileExtractService

        return ProfileExtractService(session=self.session, timeout=self.timeout).extract(
            url, limit=limit
        )

    def detect_platform(self, url: str) -> str:
        hostname = urlparse(url).netloc.lower()

        if hostname.endswith(("xhslink.com", "xiaohongshu.com", "xhscdn.com")):
            return "rednote"
        if hostname.endswith(("douyin.com", "iesdouyin.com")):
            return "douyin"
        if hostname == "feigua.cn" or hostname.endswith(".feigua.cn"):
            return "feigua"
        if hostname.endswith(("kuaishou.com", "gifshow.com")):
            return "kuaishou"

        raise UnsupportedPlatformError(f"Unsupported share url: {url}")

    def _can_fallback_to_tikhub(self, platform: str) -> bool:
        return bool(
            self.tikhub_fallback
            and self.tikhub_fallback.supports(platform)
        )


def extract(url: str, session=None, timeout=10) -> dict:
    return ExtractService(session=session, timeout=timeout).extract(url)


def extract_profile(url: str, limit: int = 10, session=None, timeout=10) -> dict:
    return ExtractService(session=session, timeout=timeout).extract_profile(url, limit=limit)
