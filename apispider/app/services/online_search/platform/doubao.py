from typing import Any

import httpx

from app.services.online_search.models import OnlineSearchRequest


class OnlineSearchError(RuntimeError):
    """Base error raised by online search providers."""


class OnlineSearchConfigError(OnlineSearchError):
    """Raised when a provider is not configured."""


class OnlineSearchRequestError(OnlineSearchError):
    """Raised when a provider request fails or returns an invalid response."""


class DoubaoSearchProvider:
    def __init__(self, *, api_url: str, api_key: str, timeout_seconds: int = 30) -> None:
        self.api_url = api_url.strip()
        self.api_key = api_key.strip()
        self.timeout_seconds = max(int(timeout_seconds), 1)

    def _validate_config(self) -> None:
        if not self.api_url:
            raise OnlineSearchConfigError("doubao search API URL is not configured")
        if not self.api_key:
            raise OnlineSearchConfigError("doubao search API key is not configured")

    async def search(self, request: OnlineSearchRequest) -> dict[str, Any]:
        self._validate_config()
        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                response = await client.post(
                    self.api_url,
                    json=request.to_provider_payload(),
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                )
        except httpx.RequestError as exc:
            raise OnlineSearchRequestError(f"doubao search request failed: {exc}") from exc

        if not 200 <= response.status_code < 300:
            raise OnlineSearchRequestError(
                f"doubao search returned HTTP {response.status_code}"
            )

        try:
            payload = response.json()
        except ValueError as exc:
            raise OnlineSearchRequestError("doubao search returned a non-JSON response") from exc
        if not isinstance(payload, dict):
            raise OnlineSearchRequestError("doubao search returned an invalid JSON response")
        return payload
