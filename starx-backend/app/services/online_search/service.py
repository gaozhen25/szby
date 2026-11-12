from typing import Any

from app.core.config import settings
from app.services.online_search.models import OnlineSearchRequest
from app.services.online_search.platform.base import OnlineSearchProvider
from app.services.online_search.platform.doubao import DoubaoSearchProvider


class OnlineSearchService:
    def __init__(self, provider: OnlineSearchProvider | None = None) -> None:
        self.provider = provider or DoubaoSearchProvider(
            api_url=settings.doubao_search_api_url,
            api_key=settings.doubao_search_api_key,
            timeout_seconds=settings.doubao_search_timeout,
        )

    async def search(self, request: OnlineSearchRequest) -> dict[str, Any]:
        return await self.provider.search(request)


default_online_search_service = OnlineSearchService()
