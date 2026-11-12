import asyncio
import logging

import httpx
import pytest

from app.services.ai_service import AIService


class TimeoutAsyncClient:
    def __init__(self, timeout):  # noqa: ANN001
        self.timeout = timeout

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):  # noqa: ANN001
        return False

    async def post(self, *args, **kwargs):  # noqa: ANN002, ANN003
        raise httpx.ReadTimeout("")


class ConnectErrorAsyncClient:
    def __init__(self, timeout):  # noqa: ANN001
        self.timeout = timeout

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):  # noqa: ANN001
        return False

    async def post(self, *args, **kwargs):  # noqa: ANN002, ANN003
        raise httpx.ConnectError("")


class SuccessfulAsyncClient:
    timeouts: list[float] = []

    def __init__(self, timeout):  # noqa: ANN001
        self.timeouts.append(timeout)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):  # noqa: ANN001
        return False

    async def post(self, *args, **kwargs):  # noqa: ANN002, ANN003
        return httpx.Response(
            200,
            json={"data": [{"url": "https://example.test/generated.png"}]},
            request=httpx.Request("POST", "https://lingyao.world/v1/images/generations"),
        )


class SuccessfulChatAsyncClient:
    def __init__(self, timeout):  # noqa: ANN001
        self.timeout = timeout

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):  # noqa: ANN001
        return False

    async def post(self, *args, **kwargs):  # noqa: ANN002, ANN003
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-diagnostic",
                "choices": [{"message": {"content": "完整账号报告返回"}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 6, "total_tokens": 16},
            },
            request=httpx.Request("POST", "https://lingyao.world/v1/chat/completions"),
        )


class InvalidJsonChatAsyncClient:
    def __init__(self, timeout):  # noqa: ANN001
        self.timeout = timeout

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):  # noqa: ANN001
        return False

    async def post(self, *args, **kwargs):  # noqa: ANN002, ANN003
        return httpx.Response(
            200,
            text="upstream returned malformed body 完整保留",
            request=httpx.Request("POST", "https://lingyao.world/v1/chat/completions"),
        )


class CapturingAsyncClient:
    bodies: list[dict] = []

    def __init__(self, timeout):  # noqa: ANN001
        self.timeout = timeout

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):  # noqa: ANN001
        return False

    async def post(self, *args, **kwargs):  # noqa: ANN002, ANN003
        self.bodies.append(kwargs["json"])
        return httpx.Response(
            200,
            json={"data": [{"url": "https://example.test/generated.png"}]},
            request=httpx.Request("POST", "https://lingyao.world/v1/images/generations"),
        )


class CapturingEditAsyncClient:
    posts: list[dict] = []
    timeouts: list[float] = []

    def __init__(self, timeout):  # noqa: ANN001
        self.timeouts.append(timeout)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):  # noqa: ANN001
        return False

    async def post(self, url, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        self.posts.append({"url": str(url), "json": kwargs.get("json")})
        return httpx.Response(
            200,
            json={"data": [{"url": "https://example.test/edited.png"}]},
            request=httpx.Request("POST", str(url)),
        )


class SuccessfulVideoAsyncClient:
    bodies: list[dict] = []

    def __init__(self, timeout):  # noqa: ANN001
        self.timeout = timeout

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):  # noqa: ANN001
        return False

    async def post(self, url, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        self.bodies.append(kwargs["json"])
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": '{"ok":true}'}, "finish_reason": "stop"}],
                "usage": {"completion_tokens": 5, "total_tokens": 20},
            },
            request=httpx.Request("POST", str(url)),
        )


def test_image_view_logs_exception_type_when_error_message_is_empty(monkeypatch, caplog):
    monkeypatch.setattr(httpx, "AsyncClient", TimeoutAsyncClient)
    service = AIService(base_url="https://lingyao.world", token="test-token", timeout_seconds=1)

    with caplog.at_level(logging.WARNING, logger="app.services.ai_service"):
        with pytest.raises(httpx.ReadTimeout):
            asyncio.run(service.image_view("describe", "https://example.test/image.png"))

    messages = [record.getMessage() for record in caplog.records]
    assert any("image_view failed" in message and "error=ReadTimeout" in message for message in messages)
    assert not any(message.endswith("error=") for message in messages)


def test_chat_completion_logs_complete_success_payload(monkeypatch, caplog):
    monkeypatch.setattr(httpx, "AsyncClient", SuccessfulChatAsyncClient)
    service = AIService(base_url="https://lingyao.world", token="test-token", timeout_seconds=360)

    with caplog.at_level(logging.INFO, logger="app.services.ai_service"):
        result = asyncio.run(service.chat_completion(messages=[{"role": "user", "content": "生成报告"}]))

    assert result == "完整账号报告返回"
    assert "chat_completion response" in caplog.text
    assert "status=200" in caplog.text
    assert "response_length=" in caplog.text
    assert "chatcmpl-diagnostic" in caplog.text
    assert "完整账号报告返回" in caplog.text


def test_chat_completion_timeout_logs_that_no_response_was_received(monkeypatch, caplog):
    monkeypatch.setattr(httpx, "AsyncClient", TimeoutAsyncClient)
    service = AIService(base_url="https://lingyao.world", token="test-token", timeout_seconds=360)

    with caplog.at_level(logging.WARNING, logger="app.services.ai_service"):
        result = asyncio.run(service.chat_completion(messages=[{"role": "user", "content": "生成报告"}]))

    assert result is None
    assert "error_type=ReadTimeout" in caplog.text
    assert "timeout_seconds=360" in caplog.text
    assert "response_received=false" in caplog.text


def test_chat_completion_invalid_json_logs_complete_raw_response(monkeypatch, caplog):
    monkeypatch.setattr(httpx, "AsyncClient", InvalidJsonChatAsyncClient)
    service = AIService(base_url="https://lingyao.world", token="test-token", timeout_seconds=360)

    with caplog.at_level(logging.WARNING, logger="app.services.ai_service"):
        result = asyncio.run(service.chat_completion(messages=[{"role": "user", "content": "生成报告"}]))

    assert result is None
    assert "response_received=true" in caplog.text
    assert "response_status=200" in caplog.text
    assert "raw_response=upstream returned malformed body 完整保留" in caplog.text


def test_default_chat_completion_timeout_is_360_seconds():
    service = AIService(base_url="https://lingyao.world", token="test-token")

    assert service.timeout_seconds == 360


def test_default_image_generation_timeout_is_360_seconds():
    service = AIService(base_url="https://lingyao.world", token="test-token")

    assert service.image_generation_timeout_seconds == 360


def test_video_view_sends_system_message_first_and_logs_completion_metadata(monkeypatch, caplog):
    SuccessfulVideoAsyncClient.bodies = []
    monkeypatch.setattr(httpx, "AsyncClient", SuccessfulVideoAsyncClient)
    service = AIService(base_url="https://lingyao.world", token="test-token")

    with caplog.at_level(logging.INFO, logger="app.services.ai_service"):
        result = asyncio.run(
            service.video_view(
                user_prompt="分析视频",
                system_prompt="只返回 JSON",
                video_url="https://example.test/video.mp4",
            )
        )

    assert result == '{"ok":true}'
    assert [message["role"] for message in SuccessfulVideoAsyncClient.bodies[0]["messages"]] == ["system", "user"]
    assert "finish_reason=stop" in caplog.text
    assert "completion_tokens=5" in caplog.text
    assert "total_tokens=20" in caplog.text


def test_image_generation_uses_generation_specific_timeout(monkeypatch):
    SuccessfulAsyncClient.timeouts = []
    monkeypatch.setattr(httpx, "AsyncClient", SuccessfulAsyncClient)
    service = AIService(
        base_url="https://lingyao.world",
        token="test-token",
        timeout_seconds=60,
        image_generation_timeout_seconds=180,
    )

    result = asyncio.run(service.image_generation(prompt="make an image"))

    assert result == [{"url": "https://example.test/generated.png"}]
    assert SuccessfulAsyncClient.timeouts == [180]


def test_image_generation_logs_exception_type_when_error_message_is_empty(monkeypatch, caplog):
    monkeypatch.setattr(httpx, "AsyncClient", ConnectErrorAsyncClient)
    service = AIService(base_url="https://lingyao.world", token="test-token", timeout_seconds=1)

    with caplog.at_level(logging.WARNING, logger="app.services.ai_service"):
        with pytest.raises(httpx.ConnectError):
            asyncio.run(service.image_generation(prompt="make an image"))

    messages = [record.getMessage() for record in caplog.records]
    assert any("image_generation failed" in message and "error=ConnectError" in message for message in messages)
    assert not any(message.endswith("error=") for message in messages)


def test_image_generation_sends_multiple_image_inputs_only_in_input_reference(monkeypatch):
    CapturingAsyncClient.bodies = []
    monkeypatch.setattr(httpx, "AsyncClient", CapturingAsyncClient)
    service = AIService(base_url="https://lingyao.world", token="test-token", timeout_seconds=1)

    asyncio.run(
        service.image_generation(
            prompt="make an image",
            input_reference=[
                {"type": "image_url", "image_url": {"url": "https://example.test/ref.png"}},
                {"type": "image_url", "image_url": {"url": "https://example.test/material.png"}},
            ],
        )
    )

    body = CapturingAsyncClient.bodies[0]
    assert "input_references" not in body
    assert body["input_reference"] == [
        {"type": "image_url", "image_url": {"url": "https://example.test/ref.png"}},
        {"type": "image_url", "image_url": {"url": "https://example.test/material.png"}},
    ]


def test_image_generation_upgrades_http_reference_urls_to_https(monkeypatch):
    CapturingAsyncClient.bodies = []
    monkeypatch.setattr(httpx, "AsyncClient", CapturingAsyncClient)
    service = AIService(base_url="https://lingyao.world", token="test-token", timeout_seconds=1)

    asyncio.run(
        service.image_generation(
            prompt="make an image",
            input_reference=[
                "http://example.test/string.png?size=large#preview",
                {"url": "http://example.test/dict.png"},
                {"type": "image_url", "image_url": {"url": "http://example.test/openai.png"}},
                {"type": "image_url", "image_url": {"url": "https://example.test/secure.png"}},
                {"type": "image_url", "image_url": {"url": "data:image/png;base64,abc"}},
            ],
        )
    )

    assert CapturingAsyncClient.bodies[0]["input_reference"] == [
        {"type": "image_url", "image_url": {"url": "https://example.test/string.png?size=large#preview"}},
        {"type": "image_url", "image_url": {"url": "https://example.test/dict.png"}},
        {"type": "image_url", "image_url": {"url": "https://example.test/openai.png"}},
        {"type": "image_url", "image_url": {"url": "https://example.test/secure.png"}},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,abc"}},
    ]


def test_image_edit_sends_reference_image_url_to_generation_endpoint(monkeypatch):
    CapturingEditAsyncClient.posts = []
    CapturingEditAsyncClient.timeouts = []
    monkeypatch.setattr(httpx, "AsyncClient", CapturingEditAsyncClient)
    service = AIService(
        base_url="https://lingyao.world",
        token="test-token",
        timeout_seconds=1,
        image_generation_timeout_seconds=360,
    )

    result = asyncio.run(
        service.image_edit(
            prompt="change the clothes to green",
            input_reference=[
                {"type": "image_url", "image_url": {"url": "https://example.test/ref.webp"}},
            ],
            size="960x1280",
        )
    )

    assert result == [{"url": "https://example.test/edited.png"}]
    assert CapturingEditAsyncClient.timeouts == [360]
    post = CapturingEditAsyncClient.posts[0]
    assert post["url"] == "https://lingyao.world/v1/images/generations"
    assert post["json"]["prompt"] == "change the clothes to green"
    assert post["json"]["size"] == "960x1280"
    assert post["json"]["image"] == "https://example.test/ref.webp"
    assert post["json"]["input_reference"] == [
        {"type": "image_url", "image_url": {"url": "https://example.test/ref.webp"}}
    ]


def test_image_edit_upgrades_http_reference_url_to_https(monkeypatch):
    CapturingEditAsyncClient.posts = []
    monkeypatch.setattr(httpx, "AsyncClient", CapturingEditAsyncClient)
    service = AIService(base_url="https://lingyao.world", token="test-token", timeout_seconds=1)

    asyncio.run(
        service.image_edit(
            prompt="change the clothes to green",
            input_reference="http://example.test/ref.webp",
        )
    )

    post = CapturingEditAsyncClient.posts[0]
    assert post["json"]["image"] == "https://example.test/ref.webp"
    assert post["json"]["input_reference"] == [
        {"type": "image_url", "image_url": {"url": "https://example.test/ref.webp"}}
    ]
