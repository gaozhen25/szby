import asyncio
import json
from types import SimpleNamespace

import httpx

from app.services.digital_human.providers.aliyun_ice import (
    AliyunIceEditingProvider,
    EditingOptions,
    NonRetryableEditingError,
    build_timeline,
    split_subtitles,
)
from app.services.digital_human.providers.dashscope import DashScopeVoiceProvider
from app.services.digital_human.providers.kyy import KyyProvider
from app.services.digital_human.subtitles import SubtitleCue


def test_dashscope_voice_clone_and_synthesis_follow_official_http_contract():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/customization"):
            return httpx.Response(200, json={"output": {"voice_id": "cosyvoice-v2-sx-test"}})
        if request.url.path.endswith("/SpeechSynthesizer"):
            return httpx.Response(
                200,
                json={"output": {"audio": {"url": "https://audio.test/result.mp3"}}},
            )
        if request.url.host == "audio.test":
            return httpx.Response(200, content=b"mp3-bytes")
        return httpx.Response(404)

    provider = DashScopeVoiceProvider(
        api_key="dashscope-key",
        transport=httpx.MockTransport(handler),
    )
    voice_id = asyncio.run(
        provider.create_voice(name="创始人数字分身", audio_url="https://cdn.test/sample.mp3")
    )
    audio = asyncio.run(
        provider.synthesize(voice_id=voice_id, text="新的口播文案", speed=1.2)
    )

    clone_body = json.loads(requests[0].content)
    synthesis_body = json.loads(requests[1].content)
    assert voice_id == "cosyvoice-v2-sx-test"
    assert audio == b"mp3-bytes"
    assert clone_body["input"]["target_model"] == "cosyvoice-v2"
    assert clone_body["input"]["prefix"].isalnum()
    assert len(clone_body["input"]["prefix"]) <= 10
    assert synthesis_body == {
        "model": "cosyvoice-v2",
        "input": {
            "text": "新的口播文案",
            "voice": "cosyvoice-v2-sx-test",
            "format": "mp3",
            "sample_rate": 24000,
            "rate": 1.2,
        },
    }


def test_dashscope_synthesis_retries_read_timeout():
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        if request.url.path.endswith("/SpeechSynthesizer"):
            attempts += 1
            if attempts == 1:
                raise httpx.ReadTimeout("slow response", request=request)
            return httpx.Response(
                200,
                json={"output": {"audio": {"url": "https://audio.test/result.mp3"}}},
            )
        if request.url.host == "audio.test":
            return httpx.Response(200, content=b"audio")
        return httpx.Response(404)

    provider = DashScopeVoiceProvider(
        api_key="dashscope-key",
        max_attempts=2,
        retry_base_delay_seconds=0,
        transport=httpx.MockTransport(handler),
    )

    audio = asyncio.run(
        provider.synthesize(voice_id="voice-test", text="测试文案")
    )

    assert audio == b"audio"
    assert attempts == 2


def test_dashscope_timed_synthesis_returns_real_subtitle_cues():
    requests: list[httpx.Request] = []
    events = [
        {
            "output": {
                "type": "sentence-begin",
                "original_text": "你好，世界。",
                "sentence": {"index": 0, "words": []},
                "audio": {"data": ""},
            }
        },
        {
            "output": {
                "type": "sentence-end",
                "original_text": "你好，世界。",
                "sentence": {
                    "index": 0,
                    "words": [
                        {
                            "text": "你",
                            "begin_index": 0,
                            "end_index": 1,
                            "begin_time": 120,
                            "end_time": 320,
                        },
                        {
                            "text": "好",
                            "begin_index": 1,
                            "end_index": 2,
                            "begin_time": 320,
                            "end_time": 540,
                        },
                        {
                            "text": "世",
                            "begin_index": 3,
                            "end_index": 4,
                            "begin_time": 760,
                            "end_time": 980,
                        },
                        {
                            "text": "界",
                            "begin_index": 4,
                            "end_index": 5,
                            "begin_time": 980,
                            "end_time": 1210,
                        },
                    ],
                },
                "audio": {"data": ""},
            }
        },
        {
            "output": {
                "finish_reason": "stop",
                "audio": {"url": "https://audio.test/timed.mp3"},
            }
        },
    ]
    sse = "\n\n".join(
        f"data: {json.dumps(event, ensure_ascii=False)}" for event in events
    )

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/SpeechSynthesizer"):
            return httpx.Response(
                200,
                text=sse,
                headers={"content-type": "text/event-stream"},
            )
        if request.url.host == "audio.test":
            return httpx.Response(200, content=b"timed-audio")
        return httpx.Response(404)

    provider = DashScopeVoiceProvider(
        api_key="dashscope-key",
        transport=httpx.MockTransport(handler),
    )
    result = asyncio.run(
        provider.synthesize_timed(
            voice_id="cosyvoice-v2-cloned",
            text="你好，世界。",
        )
    )

    body = json.loads(requests[0].content)
    assert requests[0].headers["X-DashScope-SSE"] == "enable"
    assert body["input"]["word_timestamp_enabled"] is True
    assert result.audio == b"timed-audio"
    assert result.subtitle_cues == (
        SubtitleCue("你好，", 0.12, 0.54),
        SubtitleCue("世界。", 0.76, 1.21),
    )


def test_dashscope_timed_synthesis_normalizes_global_word_indexes():
    from app.services.digital_human.subtitles import build_timed_subtitle_cues

    cues = build_timed_subtitle_cues(
        [
            {
                "text": "第一段。",
                "words": [
                    {
                        "begin_index": 0,
                        "end_index": 1,
                        "begin_time": 100,
                        "end_time": 300,
                    },
                    {
                        "begin_index": 1,
                        "end_index": 2,
                        "begin_time": 300,
                        "end_time": 500,
                    },
                    {
                        "begin_index": 2,
                        "end_index": 3,
                        "begin_time": 500,
                        "end_time": 700,
                    },
                ],
            },
            {
                "text": "第二段。",
                "words": [
                    {
                        "begin_index": 5,
                        "end_index": 6,
                        "begin_time": 900,
                        "end_time": 1100,
                    },
                    {
                        "begin_index": 6,
                        "end_index": 7,
                        "begin_time": 1100,
                        "end_time": 1300,
                    },
                    {
                        "begin_index": 7,
                        "end_index": 8,
                        "begin_time": 1300,
                        "end_time": 1500,
                    },
                ],
            },
        ]
    )

    assert cues == (
        SubtitleCue("第一段。", 0.1, 0.7),
        SubtitleCue("第二段。", 0.9, 1.5),
    )


def test_kyy_provider_submits_source_video_and_maps_poll_result():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/v1/digitalHuman/videos"):
            return httpx.Response(
                200,
                json={
                    "id": "video-001",
                    "object": "video",
                    "model": "digitalHuman",
                    "status": "queued",
                    "error": None,
                },
            )
        if request.url.path.endswith("/v1/result/video-001"):
            return httpx.Response(
                200,
                json={
                    "id": "video-001",
                    "status": "completed",
                    "video_url": "https://cdn.test/final.mp4",
                    "error": None,
                },
            )
        return httpx.Response(404)

    provider = KyyProvider(
        api_key="api-key",
        base_url="https://kyy.test/kyyReactApiServer",
        transport=httpx.MockTransport(handler),
    )
    project_id = asyncio.run(
        provider.create_video(
            title="产品口播",
            video_url="https://cdn.test/source.mp4",
            audio_url="https://cdn.test/audio.mp3",
        )
    )
    result = asyncio.run(provider.get_video_result(project_id))

    create_body = json.loads(requests[0].content)
    assert project_id == "video-001"
    assert requests[0].method == "POST"
    assert requests[0].headers["Authorization"] == "Bearer api-key"
    assert create_body == {
        "model": "digitalHuman",
        "audioUrl": "https://cdn.test/audio.mp3",
        "videoUrl": "https://cdn.test/source.mp4",
        "modelVersion": 2,
    }
    assert requests[1].method == "GET"
    assert requests[1].headers["Authorization"] == "Bearer api-key"
    assert result.state == "completed"
    assert result.media_url == "https://cdn.test/final.mp4"


def test_kyy_provider_retries_transient_tls_connection_errors():
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise httpx.ConnectError("TLS handshake failed", request=request)
        return httpx.Response(
            200,
            json={
                "id": "video-001",
                "status": "processing",
                "video_url": None,
                "error": None,
            },
        )

    provider = KyyProvider(
        api_key="api-key",
        base_url="https://result.test/kyyReactApiServer",
        request_retry_base_delay_seconds=0,
        transport=httpx.MockTransport(handler),
    )

    result = asyncio.run(provider.get_video_result("video-001"))

    assert attempts == 3
    assert result.state == "processing"


def test_aliyun_ice_timeline_combines_all_editing_layers():
    timeline = build_timeline(
        raw_video_url="https://cdn.test/raw.mp4",
        duration_seconds=12,
        options=EditingOptions(
            title="产品口播",
            script_text="第一句内容。第二句内容！",
            background_url="https://cdn.test/background.jpg",
            bubble_url="https://cdn.test/bubble.png",
            background_music_url="https://cdn.test/bgm.mp3",
            background_music_gain=0.12,
        ),
        font_url="https://cdn.test/font.ttf",
    )

    assert len(timeline["VideoTracks"]) == 3
    assert timeline["VideoTracks"][0]["VideoTrackClips"][0]["MediaURL"].endswith(
        "background.jpg"
    )
    assert timeline["VideoTracks"][1]["VideoTrackClips"][0]["MediaURL"].endswith(
        "raw.mp4"
    )
    assert timeline["VideoTracks"][2]["VideoTrackClips"][0]["MediaURL"].endswith(
        "bubble.png"
    )
    subtitle_clips = timeline["SubtitleTracks"][0]["SubtitleTrackClips"]
    assert subtitle_clips[0]["Content"] == "产品口播"
    assert [item["Content"] for item in subtitle_clips[1:]] == [
        "第一句内容。",
        "第二句内容！",
    ]
    raw_clip = timeline["VideoTracks"][1]["VideoTrackClips"][0]
    assert raw_clip["Effects"] == [
        {"Type": "ALoudNorm", "Loudness": -16.0, "TruePeak": -2.0}
    ]
    music_clip = timeline["AudioTracks"][0]["AudioTrackClips"][0]
    assert music_clip["LoopMode"] is True
    assert music_clip["Effects"] == [
        {"Type": "Volume", "Gain": 0.12}
    ]
    assert timeline["EffectTracks"][0]["EffectTrackItems"] == [
        {"Type": "AEqualize", "Peak": 0.95, "Gain": 1.0}
    ]


def test_subtitles_cover_full_duration_without_gaps():
    clips = split_subtitles("短句。这里是更长的一句话。", 9)

    assert clips[0][1] == 0
    assert clips[-1][2] == 9
    assert all(left[2] == right[1] for left, right in zip(clips, clips[1:]))


def test_aliyun_ice_prefers_real_tts_timestamps_for_subtitles():
    timeline = build_timeline(
        raw_video_url="https://cdn.test/raw.mp4",
        duration_seconds=30,
        options=EditingOptions(
            title="标题",
            script_text="第一句。第二句。",
            subtitle_cues=(
                SubtitleCue("第一句。", 1.25, 3.5),
                SubtitleCue("第二句。", 4.1, 6.8),
            ),
        ),
    )

    clips = timeline["SubtitleTracks"][0]["SubtitleTrackClips"][1:]
    assert [
        (clip["Content"], clip["TimelineIn"], clip["TimelineOut"])
        for clip in clips
    ] == [("第一句。", 1.25, 3.5), ("第二句。", 4.1, 6.8)]


def test_aliyun_ice_falls_back_when_timed_subtitles_are_incomplete():
    timeline = build_timeline(
        raw_video_url="https://cdn.test/raw.mp4",
        duration_seconds=20,
        options=EditingOptions(
            title="标题",
            script_text="第一句完整文案。第二句也必须显示。第三句不能丢失。",
            subtitle_cues=(SubtitleCue("第一句完整文案。", 0.5, 4.0),),
        ),
    )

    clips = timeline["SubtitleTracks"][0]["SubtitleTrackClips"][1:]
    assert "".join(clip["Content"] for clip in clips) == (
        "第一句完整文案。第二句也必须显示。第三句不能丢失。"
    )
    assert clips[-1]["TimelineOut"] == 20


def test_aliyun_ice_provider_uses_real_sdk_request_models():
    class FakeIceClient:
        def __init__(self) -> None:
            self.submit_request = None

        def submit_media_producing_job(self, request):
            self.submit_request = request
            return SimpleNamespace(body=SimpleNamespace(job_id="ice-job-1"))

        def get_media_producing_job(self, request):
            assert request.job_id == "ice-job-1"
            job = SimpleNamespace(
                status="Success",
                media_url="https://bucket.oss-cn-beijing.aliyuncs.com/final.mp4",
                message="",
            )
            return SimpleNamespace(
                body=SimpleNamespace(
                    media_producing_job=job,
                    request_id="request-1",
                )
            )

    client = FakeIceClient()
    provider = AliyunIceEditingProvider(
        output_bucket="bucket",
        region="cn-beijing",
        produce_template_id="mps-template-1",
        client=client,
    )
    job_id, output_url = asyncio.run(
        provider.submit(
            workflow_id="wf-test",
            raw_video_url="https://cdn.test/raw.mp4",
            duration_seconds=8,
            options=EditingOptions(title="标题", script_text="字幕内容。"),
        )
    )
    result = asyncio.run(provider.get_result(job_id))

    assert job_id == "ice-job-1"
    assert output_url.endswith("/digital-human/ice-results/wf-test.mp4")
    assert json.loads(client.submit_request.timeline)["SubtitleTracks"]
    output_config = json.loads(client.submit_request.output_media_config)
    assert output_config["MaxDuration"] == 9
    assert output_config["ProduceTemplateId"] == "mps-template-1"
    assert result.state == "completed"
    assert result.media_url.endswith("/final.mp4")


def test_aliyun_ice_retries_tls_eof_before_submit_success(monkeypatch):
    class TlsEofClient:
        def __init__(self) -> None:
            self.attempts = 0

        def submit_media_producing_job(self, _request):
            self.attempts += 1
            if self.attempts < 3:
                raise RuntimeError(
                    "SSLEOFError: [SSL: UNEXPECTED_EOF_WHILE_READING] "
                    "EOF occurred in violation of protocol"
                )
            return SimpleNamespace(body=SimpleNamespace(job_id="ice-job-retried"))

    monkeypatch.setattr(
        "app.services.digital_human.providers.aliyun_ice.sleep",
        lambda _seconds: None,
    )
    client = TlsEofClient()
    provider = AliyunIceEditingProvider(
        output_bucket="bucket",
        region="cn-hangzhou",
        client=client,
    )

    job_id, _output_url = asyncio.run(
        provider.submit(
            workflow_id="wf-tls-retry",
            raw_video_url="https://cdn.test/raw.mp4",
            duration_seconds=8,
            options=EditingOptions(title="标题", script_text="字幕。"),
        )
    )

    assert job_id == "ice-job-retried"
    assert client.attempts == 3


def test_aliyun_ice_forbidden_is_not_retried_as_transient_error():
    class ForbiddenClient:
        def submit_media_producing_job(self, _request):
            raise RuntimeError(
                "Forbidden code: 403, User not authorized to operate on the resource"
            )

    provider = AliyunIceEditingProvider(
        output_bucket="bucket",
        client=ForbiddenClient(),
    )

    try:
        asyncio.run(
            provider.submit(
                workflow_id="wf-forbidden",
                raw_video_url=(
                    "https://input.oss-cn-beijing.aliyuncs.com/raw.mp4"
                ),
                duration_seconds=8,
                options=EditingOptions(title="标题", script_text="字幕。"),
            )
        )
    except NonRetryableEditingError as exc:
        assert "ice:SubmitMediaProducingJob" in str(exc)
    else:
        raise AssertionError("403 should be converted to a non-retryable error")


def test_aliyun_ice_missing_subscription_has_specific_error():
    class SubscriptionRequiredClient:
        def submit_media_producing_job(self, _request):
            raise RuntimeError(
                "Forbidden.SubscriptionRequired code: 403, "
                "Please purchase the appropriate subscription plan"
            )

    provider = AliyunIceEditingProvider(
        output_bucket="bucket",
        client=SubscriptionRequiredClient(),
    )

    try:
        asyncio.run(
            provider.submit(
                workflow_id="wf-subscription",
                raw_video_url=(
                    "https://input.oss-cn-beijing.aliyuncs.com/raw.mp4"
                ),
                duration_seconds=8,
                options=EditingOptions(title="标题", script_text="字幕。"),
            )
        )
    except NonRetryableEditingError as exc:
        assert "服务未开通" in str(exc)
    else:
        raise AssertionError("subscription error should have a specific message")
