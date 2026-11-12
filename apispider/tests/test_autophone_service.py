import json

import httpx
import pytest

from app.services.autophone_service import (
    AutophoneNotFoundError,
    AutophonePublishRequest,
    AutophoneService,
    AutophoneSubmissionRejectedError,
    AutophoneUncertainError,
    sign_autophone_request,
)


def test_sign_autophone_request_matches_external_document_sample():
    body = json.dumps(
        {
            "external_id": "order_123456",
            "platform": "douyin",
            "android_id": "10ccb305de4adcc5",
            "assert_list": ["https://bucket.oss-cn-hangzhou.aliyuncs.com/demo.mp4"],
            "description": "发布文案",
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )

    signature = sign_autophone_request(
        method="POST",
        path="/api/external/publish",
        timestamp=1700000000,
        nonce="nonce123",
        body=body,
        secret="YOUR_SECRET",
    )

    assert signature == "52bececb1d84ecd0e303e78504af6771996e5d57d2e976142bc835b6681dc647"


def test_publish_sends_assert_list_instead_of_video_url(monkeypatch):
    sent: dict[str, object] = {}

    class FakeResponse:
        status_code = 200

        def json(self):
            return {
                "success": True,
                "data": {
                    "external_id": "order_123456",
                    "platform": "douyin",
                    "status": "queued",
                    "android_id": "android-1",
                },
            }

    def fake_post(url, *, content, headers, timeout):
        sent["url"] = url
        sent["payload"] = json.loads(content.decode("utf-8"))
        sent["headers"] = headers
        sent["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr("app.services.autophone_service.httpx.post", fake_post)

    service = AutophoneService(base_url="https://auto.example.test", client_id="client", client_secret="secret", timeout_seconds=7)
    service.publish(
        AutophonePublishRequest(
            external_id="order_123456",
            platform="douyin",
            android_id="android-1",
            asset_list=["https://bucket.oss-cn-hangzhou.aliyuncs.com/demo.mp4"],
            title="夏日护肤实测",
            description="发布文案",
        )
    )

    assert sent["url"] == "https://auto.example.test/api/external/publish"
    assert sent["payload"]["assert_list"] == ["https://bucket.oss-cn-hangzhou.aliyuncs.com/demo.mp4"]
    assert sent["payload"]["title"] == "夏日护肤实测"
    assert "video_url" not in sent["payload"]


@pytest.mark.parametrize(
    "error_type",
    [httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout],
)
def test_publish_classifies_pre_submission_transport_errors_as_rejected(
    monkeypatch,
    error_type,
):
    def failing_post(url, **kwargs):  # noqa: ANN001, ARG001
        raise error_type("connection failed", request=httpx.Request("POST", url))

    monkeypatch.setattr("app.services.autophone_service.httpx.post", failing_post)
    service = AutophoneService(
        base_url="https://auto.example.test",
        client_id="client",
        client_secret="secret",
    )

    with pytest.raises(AutophoneSubmissionRejectedError, match="connection failed"):
        service.publish(
            AutophonePublishRequest(
                external_id="order_123456",
                platform="douyin",
                android_id="android-1",
                asset_list=["https://bucket.example.test/demo.mp4"],
                description="发布文案",
            )
        )


@pytest.mark.parametrize(
    "error_type",
    [
        httpx.ReadTimeout,
        httpx.WriteTimeout,
        httpx.ReadError,
        httpx.WriteError,
        httpx.RemoteProtocolError,
        httpx.RequestError,
    ],
)
def test_publish_classifies_ambiguous_transport_errors_as_uncertain(
    monkeypatch,
    error_type,
):
    def failing_post(url, **kwargs):  # noqa: ANN001, ARG001
        raise error_type("submission result unknown", request=httpx.Request("POST", url))

    monkeypatch.setattr("app.services.autophone_service.httpx.post", failing_post)
    service = AutophoneService(
        base_url="https://auto.example.test",
        client_id="client",
        client_secret="secret",
    )

    with pytest.raises(AutophoneUncertainError, match="submission result unknown"):
        service.publish(
            AutophonePublishRequest(
                external_id="order_123456",
                platform="douyin",
                android_id="android-1",
                asset_list=["https://bucket.example.test/demo.mp4"],
                description="发布文案",
            )
        )


def test_get_publish_status_wraps_http_transport_errors(monkeypatch):
    def failing_get(url, **kwargs):  # noqa: ANN001, ARG001
        raise httpx.ReadTimeout("request timed out", request=httpx.Request("GET", url))

    monkeypatch.setattr("app.services.autophone_service.httpx.get", failing_get)
    service = AutophoneService(
        base_url="https://auto.example.test",
        client_id="client",
        client_secret="secret",
    )

    with pytest.raises(AutophoneUncertainError, match="request timed out"):
        service.get_publish_status("order_123456")


@pytest.mark.parametrize(
    ("status_code", "expected_error"),
    [
        (422, AutophoneSubmissionRejectedError),
        (500, AutophoneUncertainError),
        (503, AutophoneUncertainError),
    ],
)
def test_publish_classifies_http_response_by_submission_certainty(
    monkeypatch,
    status_code,
    expected_error,
):
    class ErrorResponse:
        def __init__(self) -> None:
            self.status_code = status_code

        def json(self):
            return {"detail": f"autophone error {status_code}"}

    monkeypatch.setattr(
        "app.services.autophone_service.httpx.post",
        lambda *args, **kwargs: ErrorResponse(),
    )
    service = AutophoneService(
        base_url="https://auto.example.test",
        client_id="client",
        client_secret="secret",
    )

    with pytest.raises(expected_error, match=str(status_code)):
        service.publish(
            AutophonePublishRequest(
                external_id="order_123456",
                platform="douyin",
                android_id="android-1",
                asset_list=["https://bucket.example.test/demo.mp4"],
                description="发布文案",
            )
        )


def test_get_publish_status_maps_http_404_to_not_found(monkeypatch):
    class MissingResponse:
        status_code = 404

        def json(self):
            return {"detail": "publish job was not found"}

    monkeypatch.setattr(
        "app.services.autophone_service.httpx.get",
        lambda *args, **kwargs: MissingResponse(),
    )
    service = AutophoneService(
        base_url="https://auto.example.test",
        client_id="client",
        client_secret="secret",
    )

    with pytest.raises(AutophoneNotFoundError, match="publish job was not found"):
        service.get_publish_status("order_123456")


@pytest.mark.parametrize(
    ("data", "expected_message"),
    [
        ({"external_id": "", "status": "queued"}, "missing external_id"),
        (
            {"external_id": "another-order", "status": "queued"},
            "external_id mismatch",
        ),
        ({"external_id": "order_123456", "status": ""}, "missing status"),
    ],
)
def test_publish_rejects_incomplete_or_mismatched_success_result(
    monkeypatch,
    data,
    expected_message,
):
    class SuccessfulResponse:
        status_code = 200

        def json(self):
            return {"success": True, "data": data}

    monkeypatch.setattr(
        "app.services.autophone_service.httpx.post",
        lambda *args, **kwargs: SuccessfulResponse(),
    )
    service = AutophoneService(
        base_url="https://auto.example.test",
        client_id="client",
        client_secret="secret",
    )

    with pytest.raises(AutophoneUncertainError, match=expected_message):
        service.publish(
            AutophonePublishRequest(
                external_id="order_123456",
                platform="douyin",
                android_id="android-1",
                asset_list=["https://bucket.example.test/demo.mp4"],
                description="发布文案",
            )
        )


@pytest.mark.parametrize(
    "data",
    [
        {"external_id": "another-order", "status": "succeeded"},
        {"external_id": "order_123456", "status": ""},
    ],
)
def test_get_publish_status_rejects_mismatched_or_incomplete_success_result(
    monkeypatch,
    data,
):
    class SuccessfulResponse:
        status_code = 200

        def json(self):
            return {"success": True, "data": data}

    monkeypatch.setattr(
        "app.services.autophone_service.httpx.get",
        lambda *args, **kwargs: SuccessfulResponse(),
    )
    service = AutophoneService(
        base_url="https://auto.example.test",
        client_id="client",
        client_secret="secret",
    )

    with pytest.raises(AutophoneUncertainError):
        service.get_publish_status("order_123456")
