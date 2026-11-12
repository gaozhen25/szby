from typing import Any, Protocol

from app.services.online_search.models import OnlineSearchRequest


class OnlineSearchProvider(Protocol):
    async def search(self, request: OnlineSearchRequest) -> dict[str, Any]: ...
