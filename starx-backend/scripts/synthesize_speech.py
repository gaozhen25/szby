"""将文案合成为音频文件。

示例：
    conda run --no-capture-output -n starx \
      python -m scripts.synthesize_speech \
      --text "欢迎使用 StarX。" \
      --voice female-shaonv \
      --output output/welcome.mp3

也可以从文本文件或管道读取文案：
    conda run --no-capture-output -n starx \
      python -m scripts.synthesize_speech --input copy.txt --output copy.mp3

    printf "这是一段口播文案" | conda run --no-capture-output -n starx \
      python -m scripts.synthesize_speech --output copy.mp3
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Protocol

# 兼容 ``python scripts/synthesize_speech.py`` 和
# ``python -m scripts.synthesize_speech`` 两种调用方式。
BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.services.ai_service import AIService


SUPPORTED_FORMATS = ("mp3", "wav", "opus", "aac", "flac", "pcm")
DEFAULT_VOICE = "female-shaonv"


class SpeechSynthesizer(Protocol):
    async def speech_synthesis(
        self,
        model: str | None,
        text: str,
        voice: str,
        response_format: str = "mp3",
        speed: float = 1.0,
        base_url: str | None = None,
        token: str | None = None,
        extra_body: dict[str, Any] | None = None,
    ) -> bytes: ...


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="调用 StarX 已配置的 TTS 服务，将文案合成为音频文件。"
    )
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--text", help="直接传入待合成文案")
    source.add_argument(
        "--input",
        type=Path,
        help="UTF-8 文案文件；不传 --text/--input 时从标准输入读取",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("output/speech.mp3"),
        help="输出音频路径，默认 output/speech.mp3",
    )
    parser.add_argument("--voice", default=DEFAULT_VOICE, help=f"音色，默认 {DEFAULT_VOICE}")
    parser.add_argument("--model", help="TTS 模型，默认使用项目配置")
    parser.add_argument(
        "--format",
        choices=SUPPORTED_FORMATS,
        help="音频格式，默认根据输出文件扩展名推断，无法推断时使用 mp3",
    )
    parser.add_argument(
        "--speed",
        type=float,
        default=1.0,
        help="语速倍率，范围 0.25～4.0，默认 1.0",
    )
    parser.add_argument("--base-url", help="临时覆盖项目的 AI 服务地址")
    parser.add_argument("--token", help="临时覆盖项目的 AI 服务令牌")
    parser.add_argument(
        "--extra-body",
        default="",
        help="附加到 TTS 请求体的 JSON 对象，供特定供应商扩展参数使用",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="允许覆盖已存在的输出文件",
    )
    return parser


def read_copy(*, text: str | None, input_path: Path | None) -> str:
    if text is not None:
        content = text
    elif input_path is not None:
        content = input_path.read_text(encoding="utf-8")
    elif not sys.stdin.isatty():
        content = sys.stdin.read()
    else:
        raise ValueError("请通过 --text、--input 或标准输入提供文案")

    content = content.strip()
    if not content:
        raise ValueError("文案不能为空")
    return content


def parse_extra_body(raw_value: str) -> dict[str, Any] | None:
    if not raw_value.strip():
        return None
    value = json.loads(raw_value)
    if not isinstance(value, dict):
        raise ValueError("--extra-body 必须是 JSON 对象")
    return value


def resolve_format(explicit_format: str | None, output_path: Path) -> str:
    if explicit_format:
        return explicit_format
    suffix = output_path.suffix.lower().removeprefix(".")
    return suffix if suffix in SUPPORTED_FORMATS else "mp3"


def write_audio_atomic(output_path: Path, audio: bytes, *, force: bool) -> None:
    if not audio:
        raise ValueError("TTS 服务返回了空音频")
    if output_path.exists() and not force:
        raise FileExistsError(f"输出文件已存在：{output_path}；如需覆盖请添加 --force")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            prefix=f".{output_path.name}.",
            suffix=".tmp",
            dir=output_path.parent,
            delete=False,
        ) as temporary:
            temporary.write(audio)
            temporary.flush()
            os.fsync(temporary.fileno())
            temporary_path = Path(temporary.name)
        os.replace(temporary_path, output_path)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


async def synthesize_to_file(
    synthesizer: SpeechSynthesizer,
    *,
    text: str,
    output_path: Path,
    voice: str,
    model: str | None,
    response_format: str,
    speed: float,
    base_url: str | None,
    token: str | None,
    extra_body: dict[str, Any] | None,
    force: bool,
) -> int:
    if not 0.25 <= speed <= 4.0:
        raise ValueError("--speed 必须在 0.25～4.0 之间")
    if output_path.exists() and not force:
        raise FileExistsError(f"输出文件已存在：{output_path}；如需覆盖请添加 --force")

    audio = await synthesizer.speech_synthesis(
        model=model,
        text=text,
        voice=voice,
        response_format=response_format,
        speed=speed,
        base_url=base_url,
        token=token,
        extra_body=extra_body,
    )
    write_audio_atomic(output_path, audio, force=force)
    return len(audio)


async def async_main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        text = read_copy(text=args.text, input_path=args.input)
        extra_body = parse_extra_body(args.extra_body)
        response_format = resolve_format(args.format, args.output)
        byte_count = await synthesize_to_file(
            AIService(),
            text=text,
            output_path=args.output,
            voice=args.voice,
            model=args.model,
            response_format=response_format,
            speed=args.speed,
            base_url=args.base_url,
            token=args.token,
            extra_body=extra_body,
            force=args.force,
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"合成失败：{exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"TTS 请求失败：{type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

    print(
        json.dumps(
            {
                "output": str(args.output.resolve()),
                "format": response_format,
                "voice": args.voice,
                "bytes": byte_count,
            },
            ensure_ascii=False,
        )
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    return asyncio.run(async_main(argv))


if __name__ == "__main__":
    raise SystemExit(main())
