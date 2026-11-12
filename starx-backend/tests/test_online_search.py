import asyncio
from typing import Any

import httpx
import pytest
from fastapi import HTTPException

from app.api.routes.online_search import online_search
from app.main import app
from app.services.online_search.models import OnlineSearchRequest
from app.services.online_search.platform.doubao import (
    DoubaoSearchProvider,
    OnlineSearchConfigError,
    OnlineSearchRequestError,
)


class FakeAsyncClient:
    response: httpx.Response
    captured: dict[str, Any] = {}

    def __init__(self, *, timeout: int) -> None:
        self.captured["timeout"] = timeout

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):  # noqa: ANN001
        return None

    async def post(self, url: str, *, json: dict[str, Any], headers: dict[str, str]):
        self.captured.update(url=url, payload=json, headers=headers)
        return self.response


def test_doubao_provider_maps_request_and_authorization(monkeypatch):
    FakeAsyncClient.captured = {}
    FakeAsyncClient.response = httpx.Response(
        200,
        json={"data": [{"title": "美妆博主", "url": "https://example.test/creator"}]},
    )
    monkeypatch.setattr(
        "app.services.online_search.platform.doubao.httpx.AsyncClient",
        FakeAsyncClient,
    )
    provider = DoubaoSearchProvider(
        api_url="https://search.example.test/web_search",
        api_key="secret-key",
        timeout_seconds=12,
    )

    result = asyncio.run(
        provider.search(
            OnlineSearchRequest(
                query="推荐美妆博主",
                count=10,
                filter={"needContent": True, "needUrl": False},
            )
        )
    )

    assert result["data"][0]["title"] == "美妆博主"
    assert FakeAsyncClient.captured == {
        "timeout": 12,
        "url": "https://search.example.test/web_search",
        "payload": {
            "Query": "推荐美妆博主",
            "SearchType": "web",
            "Count": 10,
            "Filter": {
                "NeedContent": True,
                "NeedUrl": False,
                "Sites": "",
                "BlockHosts": "",
                "AuthInfoLevel": 0,
            },
            "NeedSummary": True,
            "TimeRange": "",
            "QueryControl": {"QueryRewrite": False},
        },
        "headers": {
            "Authorization": "Bearer secret-key",
            "Content-Type": "application/json",
        },
    }


def test_doubao_provider_requires_api_key():
    provider = DoubaoSearchProvider(
        api_url="https://search.example.test/web_search",
        api_key="",
    )

    with pytest.raises(OnlineSearchConfigError, match="API key"):
        asyncio.run(provider.search(OnlineSearchRequest(query="测试")))


@pytest.mark.parametrize("status_code", [400, 401, 429, 500])
def test_doubao_provider_rejects_upstream_http_errors(monkeypatch, status_code):
    FakeAsyncClient.captured = {}
    FakeAsyncClient.response = httpx.Response(status_code, text="upstream private details")
    monkeypatch.setattr(
        "app.services.online_search.platform.doubao.httpx.AsyncClient",
        FakeAsyncClient,
    )
    provider = DoubaoSearchProvider(
        api_url="https://search.example.test/web_search",
        api_key="secret-key",
    )

    with pytest.raises(OnlineSearchRequestError, match=f"HTTP {status_code}") as exc_info:
        asyncio.run(provider.search(OnlineSearchRequest(query="测试")))

    assert "private details" not in str(exc_info.value)


def test_online_search_route_is_registered():
    paths = set(app.openapi()["paths"])

    assert "/api/v1/online-search" in paths


def test_online_search_route_maps_provider_error_to_bad_gateway():
    class FailingService:
        async def search(self, request):  # noqa: ANN001, ARG002
            raise OnlineSearchRequestError("provider unavailable")

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            online_search(
                OnlineSearchRequest(query="测试"),
                _user=None,
                service=FailingService(),
            )
        )

    assert exc_info.value.status_code == 502
    assert exc_info.value.detail == "provider unavailable"
