from __future__ import annotations

import asyncio
import hashlib
import json
from typing import Any

import httpx

from app.core.config import settings
from app.services.digital_human.subtitles import build_timed_subtitle_cues

from .base import SynthesizedSpeech


class DashScopeVoiceProvider:
    base_url = "https://dashscope.aliyuncs.com"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        timeout_seconds: float | None = None,
        max_attempts: int | None = None,
        retry_base_delay_seconds: float | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.api_key = (
            api_key if api_key is not None else settings.digital_human_bailian_api_key
        )
        effective_timeout = (
            timeout_seconds
            if timeout_seconds is not None
            else settings.digital_human_dashscope_timeout_seconds
        )
        self.timeout = httpx.Timeout(effective_timeout, connect=10)
        self.max_attempts = max(
            1,
            int(
                max_attempts
                if max_attempts is not None
                else settings.digital_human_dashscope_max_attempts
            ),
        )
        self.retry_base_delay_seconds = max(
            0.0,
            float(
                retry_base_delay_seconds
                if retry_base_delay_seconds is not None
                else settings.digital_human_dashscope_retry_base_delay_seconds
            ),
        )
        self.transport = transport

    def _headers(self) -> dict[str, str]:
        if not self.api_key:
            raise RuntimeError("百炼声音克隆配置不完整")
        return {"Authorization": f"Bearer {self.api_key}"}

    async def _request(
        self,
        client: httpx.AsyncClient,
        method: str,
        url: str,
        **kwargs: Any,
    ) -> httpx.Response:
        for attempt in range(self.max_attempts):
            try:
                response = await client.request(method, url, **kwargs)
                response.raise_for_status()
                return response
            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code
                if status != 429 and status < 500:
                    raise
                error: Exception = exc
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                error = exc
            if attempt + 1 >= self.max_attempts:
                raise error
            await asyncio.sleep(
                self.retry_base_delay_seconds * (2**attempt)
            )
        raise RuntimeError("百炼请求重试状态异常")

    async def create_voice(self, *, name: str, audio_url: str) -> str:
        # 百炼要求 prefix 只能包含小写字母和数字，且最长 10 个字符。
        prefix = f"sx{hashlib.sha1(name.encode('utf-8')).hexdigest()[:8]}"
        body = {
            "model": "voice-enrollment",
            "input": {
                "action": "create_voice",
                "target_model": "cosyvoice-v2",
                "prefix": prefix,
                "url": audio_url,
            },
        }
        async with httpx.AsyncClient(
            timeout=self.timeout,
            transport=self.transport,
        ) as client:
            response = await self._request(
                client,
                "POST",
                f"{self.base_url}/api/v1/services/audio/tts/customization",
                headers=self._headers(),
                json=body,
            )
            payload = response.json()
        voice_id = str((payload.get("output") or {}).get("voice_id") or "")
        if not voice_id:
            raise RuntimeError("声音克隆失败，未返回音色 ID")
        return voice_id

    async def synthesize(
        self, *, voice_id: str, text: str, speed: float = 1.0
    ) -> bytes:
        result = await self._synthesize(
            voice_id=voice_id,
            text=text,
            speed=speed,
            word_timestamps=False,
        )
        return result.audio

    async def synthesize_timed(
        self, *, voice_id: str, text: str, speed: float = 1.0
    ) -> SynthesizedSpeech:
        """合成口播并返回与同一音频一起生成的字级字幕时间戳。"""
        return await self._synthesize(
            voice_id=voice_id,
            text=text,
            speed=speed,
            word_timestamps=True,
        )

    async def _synthesize(
        self,
        *,
        voice_id: str,
        text: str,
        speed: float,
        word_timestamps: bool,
    ) -> SynthesizedSpeech:
        input_payload: dict[str, Any] = {
            "text": text,
            "voice": voice_id,
            "format": "mp3",
            "sample_rate": 24000,
            "rate": speed,
        }
        headers = self._headers()
        if word_timestamps:
            input_payload["word_timestamp_enabled"] = True
            headers = {**headers, "X-DashScope-SSE": "enable"}
        body = {
            "model": "cosyvoice-v2",
            "input": input_payload,
        }
        async with httpx.AsyncClient(timeout=self.timeout, transport=self.transport) as client:
            response = await self._request(
                client,
                "POST",
                f"{self.base_url}/api/v1/services/audio/tts/SpeechSynthesizer",
                headers=headers,
                json=body,
            )
            payloads = (
                _parse_sse_payloads(response.text)
                if word_timestamps
                else [response.json()]
            )
            payload = payloads[-1] if payloads else {}
            audio_url = str(
                (((payload.get("output") or {}).get("audio") or {}).get("url")) or ""
            )
            if not audio_url:
                raise RuntimeError("克隆音色合成失败，未返回音频地址")
            audio_response = await self._request(client, "GET", audio_url)
            data = audio_response.content
        if not data:
            raise RuntimeError("克隆音色合成失败")
        return SynthesizedSpeech(
            audio=data,
            subtitle_cues=(
                build_timed_subtitle_cues(_timed_sentences(payloads))
                if word_timestamps
                else ()
            ),
        )


def _parse_sse_payloads(content: str) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    for line in content.splitlines():
        if not line.startswith("data:"):
            continue
        raw = line.removeprefix("data:").strip()
        if not raw or raw == "[DONE]":
            continue
        try:
            value = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            payloads.append(value)
    return payloads


def _timed_sentences(payloads: list[dict[str, Any]]) -> list[dict[str, Any]]:
    texts: dict[int, str] = {}
    words: dict[int, list[dict[str, Any]]] = {}
    for payload in payloads:
        output = payload.get("output") or {}
        if not isinstance(output, dict):
            continue
        sentence = output.get("sentence") or {}
        if not isinstance(sentence, dict):
            continue
        try:
            index = int(sentence.get("index"))
        except (TypeError, ValueError):
            continue
        original_text = str(output.get("original_text") or "")
        if original_text:
            texts[index] = original_text
        sentence_words = sentence.get("words")
        if isinstance(sentence_words, list) and sentence_words:
            words[index] = sentence_words
    return [
        {"text": texts.get(index, ""), "words": words.get(index, [])}
        for index in sorted(set(texts) | set(words))
    ]
