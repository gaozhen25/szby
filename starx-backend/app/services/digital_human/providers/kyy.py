from __future__ import annotations

import asyncio
from typing import Any
from urllib.parse import quote

import httpx

from app.core.config import settings

from .base import ProviderVideoResult


class KyyProvider:
    model = "digitalHuman"
    model_version = 2

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout_seconds: float = 30,
        request_retry_attempts: int = 3,
        request_retry_base_delay_seconds: float = 0.5,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.api_key = api_key if api_key is not None else settings.digital_human_kyy_api_key
        self.base_url = (base_url or settings.digital_human_kyy_base_url).rstrip("/")
        self.timeout = httpx.Timeout(timeout_seconds, connect=10)
        self.request_retry_attempts = max(int(request_retry_attempts), 1)
        self.request_retry_base_delay_seconds = max(
            float(request_retry_base_delay_seconds), 0
        )
        self.transport = transport

    def _require_config(self) -> None:
        if not self.api_key:
            raise RuntimeError("客易云 API Key 未配置")

    @property
    def _headers(self) -> dict[str, str]:
        self._require_config()
        return {"Authorization": f"Bearer {self.api_key}"}

    async def _request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        """对供应商瞬时网络故障短重试，每次尝试都使用全新的连接池。"""
        last_error: httpx.TransportError | None = None
        for attempt in range(self.request_retry_attempts):
            try:
                async with httpx.AsyncClient(
                    timeout=self.timeout,
                    transport=self.transport,
                ) as client:
                    return await client.request(method, url, **kwargs)
            except httpx.TransportError as exc:
                last_error = exc
                if attempt + 1 >= self.request_retry_attempts:
                    raise
                delay = self.request_retry_base_delay_seconds * (2**attempt)
                if delay:
                    await asyncio.sleep(delay)
        assert last_error is not None
        raise last_error

    async def create_video(self, *, title: str, video_url: str, audio_url: str) -> str:
        del title  # 官方接口不接收任务标题。
        payload = {
            "model": self.model,
            "audioUrl": audio_url,
            "videoUrl": video_url,
            "modelVersion": self.model_version,
        }
        response = await self._request(
            "POST",
            f"{self.base_url}/v1/digitalHuman/videos",
            json=payload,
            headers=self._headers,
        )
        response.raise_for_status()
        data: dict[str, Any] = response.json()
        project_id = str(data.get("id") or "")
        if not project_id:
            raise RuntimeError("客易云创建视频失败，未返回任务 ID")
        return project_id

    async def get_video_result(self, project_id: str) -> ProviderVideoResult:
        response = await self._request(
            "GET",
            f"{self.base_url}/v1/result/{quote(project_id, safe='')}",
            headers=self._headers,
        )
        response.raise_for_status()
        data: dict[str, Any] = response.json()
        status = str(data.get("status") or "").lower()
        media_url = str(data.get("video_url") or "")
        if status == "completed" and media_url:
            return ProviderVideoResult("completed", media_url=media_url, raw=data)
        if status == "completed":
            return ProviderVideoResult(
                "failed",
                error_message="客易云任务已完成但未返回视频地址",
                raw=data,
            )
        if status == "failed":
            return ProviderVideoResult(
                "failed",
                error_message=str(data.get("error") or "数字人生成失败"),
                raw=data,
            )
        return ProviderVideoResult("processing", raw=data)
