from dataclasses import dataclass
from typing import Any, Protocol

from ..subtitles import SubtitleCue


@dataclass(frozen=True)
class ProviderVideoResult:
    state: str
    media_url: str = ""
    error_message: str = ""
    raw: dict[str, Any] | None = None


@dataclass(frozen=True)
class SynthesizedSpeech:
    audio: bytes
    subtitle_cues: tuple[SubtitleCue, ...] = ()


class DigitalHumanVideoProvider(Protocol):
    async def create_video(
        self, *, title: str, video_url: str, audio_url: str
    ) -> str: ...

    async def get_video_result(self, project_id: str) -> ProviderVideoResult: ...


class VoiceCloneProvider(Protocol):
    async def create_voice(self, *, name: str, audio_url: str) -> str: ...

    async def synthesize(
        self, *, voice_id: str, text: str, speed: float = 1.0
    ) -> bytes: ...
