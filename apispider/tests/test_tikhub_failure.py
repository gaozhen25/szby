from app.services.tikhub_service.errors import (
    InvalidTikHubRequestError,
    TikHubBusinessBudgetError,
    TikHubBusinessRateLimitError,
    TikHubBusinessRequestError,
)
from app.services.tikhub_service.failure import classify_tikhub_failure


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
