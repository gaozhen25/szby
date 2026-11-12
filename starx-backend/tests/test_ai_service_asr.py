import asyncio

import httpx

from app.services.ai_service import AIService


class CapturingASRAsyncClient:
    posts: list[dict] = []
    timeouts: list[httpx.Timeout] = []
    response_payload: dict = {
        "id": "chatcmpl-asr",
        "model": "qwen3-asr-flash",
        "choices": [{
            "finish_reason": "stop",
            "message": {
                "role": "assistant",
                "content": "欢迎使用灵曜中转站。",
                "annotations": [{
                    "type": "audio_info",
                    "language": "zh",
                    "emotion": "neutral",
                }],
            },
        }],
        "usage": {
            "prompt_tokens": 42,
            "completion_tokens": 8,
            "total_tokens": 50,
            "seconds": 1,
        },
    }

    def __init__(self, timeout):  # noqa: ANN001
        self.timeout = timeout
        self.__class__.timeouts.append(timeout)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):  # noqa: ANN001
        return False

    async def post(self, url, **kwargs):  # noqa: ANN001, ANN003
        self.__class__.posts.append({
            "url": str(url),
            "headers": kwargs["headers"],
            "json": kwargs["json"],
        })
        return httpx.Response(
            200,
            json=self.__class__.response_payload,
            request=httpx.Request("POST", str(url)),
        )


class CapturingFiletransAsyncClient:
    posts: list[dict] = []
    gets: list[dict] = []

    def __init__(self, timeout):  # noqa: ANN001
        self.timeout = timeout

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):  # noqa: ANN001
        return False

    async def post(self, url, **kwargs):  # noqa: ANN001, ANN003
        self.__class__.posts.append({
            "url": str(url),
            "headers": kwargs["headers"],
            "json": kwargs["json"],
        })
        return httpx.Response(
            200,
            json={"output": {"task_id": "task-asr-1", "task_status": "PENDING"}},
            request=httpx.Request("POST", str(url)),
        )

    async def get(self, url, **kwargs):  # noqa: ANN001, ANN003
        self.__class__.gets.append({"url": str(url), "headers": kwargs.get("headers")})
        if str(url).endswith("/api/v1/tasks/task-asr-1"):
            payload = {
                "output": {
                    "task_id": "task-asr-1",
                    "task_status": "SUCCEEDED",
                    "result": {"transcription_url": "https://result.example.test/asr.json"},
                },
                "usage": {"seconds": 60},
            }
        else:
            payload = {
                "transcripts": [{
                    "sentences": [{
                        "begin_time": 0,
                        "end_time": 1200,
                        "text": "转写成功",
                        "emotion": "happy",
                    }],
                }],
            }
        return httpx.Response(
            200,
            json=payload,
            request=httpx.Request("GET", str(url)),
        )


def test_qwen3_asr_flash_uses_lingyao_base_url_and_official_payload(monkeypatch):
    CapturingASRAsyncClient.posts = []
    CapturingASRAsyncClient.timeouts = []
    monkeypatch.setattr(httpx, "AsyncClient", CapturingASRAsyncClient)
    service = AIService(
        base_url="https://lingyao.example.test",
        token="lingyao-token",
        voice_discern_model="qwen3-asr-flash",
    )

    result = asyncio.run(
        service.speech_discern(
            "https://oss.example.test/audio.mp3",
            language="zh",
        )
    )

    assert result == "欢迎使用灵曜中转站。"
    request = CapturingASRAsyncClient.posts[0]
    assert request["url"] == "https://lingyao.example.test/v1/chat/completions"
    assert request["headers"] == {
        "Content-Type": "application/json",
        "Authorization": "Bearer lingyao-token",
    }
    assert request["json"] == {
        "model": "qwen3-asr-flash",
        "messages": [{
            "role": "user",
            "content": [{
                "type": "input_audio",
                "input_audio": {"data": "https://oss.example.test/audio.mp3"},
            }],
        }],
        "stream": False,
        "asr_options": {
            "enable_itn": False,
            "language": "zh",
        },
    }
    assert CapturingASRAsyncClient.timeouts[0].read == service.video_analysis_timeout_seconds
    assert CapturingASRAsyncClient.timeouts[0].connect == 30


def test_qwen3_asr_flash_accepts_openai_v1_base_url_and_data_uri(monkeypatch):
    CapturingASRAsyncClient.posts = []
    monkeypatch.setattr(httpx, "AsyncClient", CapturingASRAsyncClient)
    service = AIService(
        base_url="https://lingyao.example.test/v1",
        token="test-token",
    )

    result = asyncio.run(
        service.speech_discern(
            "data:audio/mpeg;base64,ZmFrZS1hdWRpbw==",
            prompt="背景词：StarX、灵曜",
            enable_itn=True,
        )
    )

    assert result == "欢迎使用灵曜中转站。"
    request = CapturingASRAsyncClient.posts[0]
    assert request["url"] == "https://lingyao.example.test/v1/chat/completions"
    assert [message["role"] for message in request["json"]["messages"]] == [
        "system",
        "user",
    ]
    assert request["json"]["messages"][0]["content"] == "背景词：StarX、灵曜"
    assert request["json"]["asr_options"] == {"enable_itn": True}


def test_qwen3_asr_flash_returns_none_without_audio(monkeypatch):
    CapturingASRAsyncClient.posts = []
    monkeypatch.setattr(httpx, "AsyncClient", CapturingASRAsyncClient)

    result = asyncio.run(
        AIService(
            base_url="https://lingyao.example.test",
            token="test-token",
        ).speech_discern("")
    )

    assert result is None
    assert CapturingASRAsyncClient.posts == []


def test_qwen3_asr_filetrans_uses_lingyao_async_endpoints(monkeypatch):
    CapturingFiletransAsyncClient.posts = []
    CapturingFiletransAsyncClient.gets = []
    monkeypatch.setattr(httpx, "AsyncClient", CapturingFiletransAsyncClient)
    service = AIService(
        base_url="https://lingyao.example.test/v1",
        token="lingyao-token",
        voice_filetrans_model="qwen3-asr-flash-filetrans",
    )

    result = asyncio.run(
        service.speech_filetrans("https://oss.example.test/chunk-1.mp3")
    )

    assert result["transcripts"][0]["sentences"][0]["emotion"] == "happy"
    request = CapturingFiletransAsyncClient.posts[0]
    assert request["url"] == (
        "https://lingyao.example.test/api/v1/services/audio/asr/transcription"
    )
    assert request["headers"]["Authorization"] == "Bearer lingyao-token"
    assert request["headers"]["X-DashScope-Async"] == "enable"
    assert request["json"] == {
        "model": "qwen3-asr-flash-filetrans",
        "input": {"file_url": "https://oss.example.test/chunk-1.mp3"},
        "parameters": {
            "channel_id": [0],
            "enable_itn": False,
            "enable_words": True,
        },
    }
    assert [item["url"] for item in CapturingFiletransAsyncClient.gets] == [
        "https://lingyao.example.test/api/v1/tasks/task-asr-1",
        "https://result.example.test/asr.json",
    ]
