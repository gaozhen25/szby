import asyncio
import logging

import pytest
from tikhub import TikHubBadRequestError

from app.services.tikhub_service.errors import (
    InvalidTikHubRequestError,
    TikHubBusinessBudgetError,
    TikHubBusinessRateLimitError,
    TikHubBusinessRequestError,
)
from app.services.tikhub_service.failure import classify_tikhub_failure
from app.services.tikhub_service.models import TikHubPlatform, TikHubSearchRequest
from app.services.tikhub_service.provider import TikHubProvider


class FailingTikHubResource:
    async def fetch_video_search_v2(self, **params):
        raise TikHubBadRequestError(
            "bad request",
            status_code=400,
            method="GET",
            url="https://api.tikhub.io/api/v1/douyin/search/fetch_video_search_v2",
            params=params,
            response_body={
                "detail": "invalid cursor",
                "code": 400,
            },
            request_id="req-log-1",
        )


class FailingTikHubSDK:
    douyin_search = FailingTikHubResource()


def test_tikhub_failures_have_stable_public_codes():
    cases = [
        (
            TikHubBusinessRateLimitError("limited"),
            "provider_rate_limited",
        ),
        (
            InvalidTikHubRequestError("invalid"),
            "provider_request_invalid",
        ),
        (
            TikHubBusinessBudgetError("budget"),
            "provider_budget_exhausted",
        ),
        (
            TikHubBusinessRequestError("upstream"),
            "provider_unavailable",
        ),
    ]

    for error, expected_code in cases:
        failure = classify_tikhub_failure(error)
        assert failure is not None
        assert failure.code == expected_code
        assert "limited" not in failure.message
        assert "invalid" not in failure.message
        assert "budget" not in failure.message
        assert "upstream" not in failure.message


def test_tikhub_http_error_logs_upstream_response_body(caplog):
    provider = TikHubProvider(sdk=FailingTikHubSDK())  # type: ignore[arg-type]

    caplog.set_level(logging.ERROR, logger="app.services.tikhub_service.provider")
    with pytest.raises(InvalidTikHubRequestError):
        asyncio.run(
            provider.search_contents(
                TikHubSearchRequest(
                    platform=TikHubPlatform.DOUYIN,
                    keyword="护肤",
                    cursor="bad-cursor",
                )
            )
        )

    message = caplog.text
    assert "TikHub interface failed" in message
    assert "status_code=400" in message
    assert "fetch_video_search_v2" in message
    assert "req-log-1" in message
    assert "invalid cursor" in message
    assert '"keyword": "护肤"' in message
