"""阿里云 ICE 配置与最小云剪辑任务冒烟测试。

默认只检查当前 AccessKey 身份和最终生效的 ICE 配置，不创建任务：

    conda run --no-capture-output -n starx \
      python scripts/test_aliyun_ice.py

传入 --submit 后会创建一个可能计费的最小剪辑任务：

    conda run --no-capture-output -n starx \
      python scripts/test_aliyun_ice.py \
      --submit \
      --input-url "https://bucket.oss-cn-hangzhou.aliyuncs.com/path/raw.mp4"
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from alibabacloud_sts20150401.client import Client as StsClient
from alibabacloud_tea_openapi import models as open_api_models

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.core.config import settings
from app.services.digital_human.providers.aliyun_ice import (
    AliyunIceEditingProvider,
    EditingOptions,
)


@dataclass(frozen=True)
class EffectiveConfig:
    access_key_id: str
    credential_source: str
    region: str
    endpoint: str
    output_bucket: str
    output_prefix: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="使用 StarX 当前配置检查阿里云身份，并可提交 ICE 最小剪辑任务。"
    )
    parser.add_argument(
        "--submit",
        action="store_true",
        help="实际提交 ICE 云剪辑任务（可能产生费用）。",
    )
    parser.add_argument(
        "--input-url",
        default="",
        help="ICE 可访问的原始视频 URL；使用 --submit 时必填。",
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=10.0,
        help="测试时间线长度，单位秒，默认 10 秒。",
    )
    parser.add_argument(
        "--poll",
        action="store_true",
        help="提交成功后轮询任务结果。",
    )
    parser.add_argument(
        "--poll-timeout",
        type=int,
        default=120,
        help="轮询最长等待秒数，默认 120 秒。",
    )
    return parser.parse_args()


def mask_access_key(access_key_id: str) -> str:
    if len(access_key_id) <= 8:
        return "*" * len(access_key_id)
    return f"{access_key_id[:4]}...{access_key_id[-4:]}"


def effective_config(provider: AliyunIceEditingProvider) -> EffectiveConfig:
    using_ice_key = bool(settings.digital_human_ice_access_key_id)
    return EffectiveConfig(
        access_key_id=mask_access_key(provider.access_key_id),
        credential_source=(
            "STARX_DIGITAL_HUMAN_ICE_ACCESS_KEY_ID"
            if using_ice_key
            else "OSS_ACCESS_KEY_ID / STARX_OBJECT_STORAGE_ACCESS_KEY"
        ),
        region=provider.region,
        endpoint=provider.endpoint,
        output_bucket=provider.output_bucket,
        output_prefix=provider.output_prefix,
    )


def get_caller_identity(provider: AliyunIceEditingProvider) -> dict[str, Any]:
    config = open_api_models.Config(
        access_key_id=provider.access_key_id,
        access_key_secret=provider.access_key_secret,
    )
    config.region_id = provider.region
    config.endpoint = f"sts.{provider.region}.aliyuncs.com"
    response = StsClient(config).get_caller_identity()
    body = getattr(response, "body", None)
    if body is None:
        return {}
    to_map = getattr(body, "to_map", None)
    return to_map() if callable(to_map) else {}


def validate_submit_args(args: argparse.Namespace, provider: AliyunIceEditingProvider) -> None:
    if not args.submit:
        return
    if not args.input_url:
        raise ValueError("使用 --submit 时必须传入 --input-url")
    parsed = urlparse(args.input_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("--input-url 必须是完整的 HTTP/HTTPS URL")
    if args.duration <= 0:
        raise ValueError("--duration 必须大于 0")
    if not provider.output_bucket:
        raise ValueError("当前配置无法解析 ICE 输出 Bucket")


def exception_details(exc: BaseException) -> dict[str, Any]:
    chain: list[dict[str, Any]] = []
    current: BaseException | None = exc
    visited: set[int] = set()
    while current is not None and id(current) not in visited:
        visited.add(id(current))
        item: dict[str, Any] = {
            "type": type(current).__name__,
            "message": str(current),
        }
        for name in ("code", "status_code", "request_id", "data"):
            value = getattr(current, name, None)
            if value not in (None, "", {}):
                item[name] = value
        chain.append(item)
        current = current.__cause__ or current.__context__
    return {"exception_chain": chain}


async def poll_job(
    provider: AliyunIceEditingProvider,
    job_id: str,
    timeout_seconds: int,
) -> int:
    deadline = time.monotonic() + max(1, timeout_seconds)
    while True:
        result = await provider.get_result(job_id)
        print_json(
            "ICE 任务状态",
            {
                "status": result.status,
                "media_url": result.media_url,
                "error_message": result.error_message,
                "raw": result.raw,
            },
        )
        if result.status == "completed":
            return 0
        if result.status == "failed":
            return 2
        if time.monotonic() >= deadline:
            print(f"轮询超时：等待超过 {timeout_seconds} 秒", file=sys.stderr)
            return 3
        await asyncio.sleep(5)


def print_json(title: str, value: Any) -> None:
    print(f"\n{title}")
    print(json.dumps(value, ensure_ascii=False, indent=2, default=str))


async def run(args: argparse.Namespace) -> int:
    provider = AliyunIceEditingProvider()
    validate_submit_args(args, provider)

    print_json("当前生效配置（密钥已脱敏）", asdict(effective_config(provider)))
    identity = await asyncio.to_thread(get_caller_identity, provider)
    print_json("STS GetCallerIdentity", identity)

    if not args.submit:
        print("\n身份检查完成；未传入 --submit，因此没有创建 ICE 任务。")
        return 0

    workflow_id = f"ice-smoke-{uuid.uuid4().hex[:12]}"
    output_url = provider.output_url(workflow_id)
    print_json(
        "准备提交最小 ICE 任务",
        {
            "workflow_id": workflow_id,
            "input_url": args.input_url,
            "output_url": output_url,
            "duration_seconds": args.duration,
        },
    )
    job_id, submitted_output_url = await provider.submit(
        workflow_id=workflow_id,
        raw_video_url=args.input_url,
        duration_seconds=args.duration,
        options=EditingOptions(
            title="ICE 服务测试",
            script_text="这是一条阿里云智能媒体服务连通性测试字幕。",
        ),
    )
    print_json(
        "ICE 提交成功",
        {"job_id": job_id, "output_url": submitted_output_url},
    )
    if args.poll:
        return await poll_job(provider, job_id, args.poll_timeout)
    return 0


def main() -> int:
    args = parse_args()
    try:
        return asyncio.run(run(args))
    except Exception as exc:
        print_json("ICE 测试失败", exception_details(exc))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
