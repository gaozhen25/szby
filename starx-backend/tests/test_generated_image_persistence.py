import asyncio

import httpx
import pytest

from app.services.workflow.workflows import generated_image_persistence as persistence


def _install_transport(monkeypatch, handler):
    original_client = httpx.AsyncClient
    transport = httpx.MockTransport(handler)

    def client_factory(*args, **kwargs):
        return original_client(*args, transport=transport, **kwargs)

    monkeypatch.setattr(persistence.httpx, "AsyncClient", client_factory)


def test_download_generated_image_accepts_supported_image_and_follows_size_limit(monkeypatch):
    image_bytes = b"generated png bytes"
    _install_transport(
        monkeypatch,
        lambda request: httpx.Response(
            200,
            headers={"Content-Type": "image/png", "Content-Length": str(len(image_bytes))},
            content=image_bytes,
            request=request,
        ),
    )

    data, content_type = asyncio.run(
        persistence._download_generated_image("https://provider.example/generated.png")
    )

    assert data == image_bytes
    assert content_type == "image/png"


def test_download_generated_image_rejects_non_image_response(monkeypatch):
    _install_transport(
        monkeypatch,
        lambda request: httpx.Response(
            200,
            headers={"Content-Type": "text/plain"},
            text="not an image",
            request=request,
        ),
    )

    with pytest.raises(ValueError, match="unsupported content type: text/plain"):
        asyncio.run(
            persistence._download_generated_image("https://provider.example/generated.png")
        )


def test_download_generated_image_rejects_oversized_response_header(monkeypatch):
    monkeypatch.setattr(persistence.settings, "max_generated_image_bytes", 4)
    _install_transport(
        monkeypatch,
        lambda request: httpx.Response(
            200,
            headers={"Content-Type": "image/png", "Content-Length": "5"},
            content=b"12345",
            request=request,
        ),
    )

    with pytest.raises(ValueError, match="generated image exceeds 4 bytes"):
        asyncio.run(
            persistence._download_generated_image("https://provider.example/generated.png")
        )
