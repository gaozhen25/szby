#!/usr/bin/env python3
"""提取本机抖音/小红书 Cookie，并同步到 StarX 服务器。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if __package__ in (None, ""):
    sys.path.insert(0, str(BACKEND_ROOT))

from scripts.cookie_sync.extractor import discover_sources, extract_cookies
from scripts.cookie_sync.storage import atomic_write_pool, build_pool, upload_pool


DEFAULT_OUTPUT = BACKEND_ROOT / "cookies/cookies.json"
DEFAULT_REMOTE_PATH = "~/projects/starx-backend/cookies/cookies.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="starx", help="SSH config 中的服务器别名")
    parser.add_argument("--remote-path", default=DEFAULT_REMOTE_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--no-upload", action="store_true", help="只生成本地文件")
    parser.add_argument(
        "--print-cookies",
        action="store_true",
        help="将完整 Cookie 原文打印到控制台（敏感信息）",
    )
    parser.add_argument(
        "--allow-partial",
        action="store_true",
        help="允许仅更新找到的平台；未找到的平台保留本地旧值",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    sources = discover_sources()
    if not sources:
        print("错误：没有找到受支持的浏览器 Cookie 数据库。", file=sys.stderr)
        return 2

    print(f"发现 {len(sources)} 个浏览器配置，正在读取……")
    result = extract_cookies(sources)
    for warning in result.warnings:
        print(f"警告：{warning}", file=sys.stderr)

    try:
        pool = build_pool(result.cookies, args.output, allow_partial=args.allow_partial)
        atomic_write_pool(args.output, pool)
    except (OSError, ValueError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2

    print(
        f"已安全写入 {args.output}（小红书 {len(pool['xhs'])} 组，"
        f"抖音 {len(pool['dy'])} 组）"
    )
    if args.print_cookies:
        print("\n===== 小红书 Cookie（xhs）=====")
        for index, cookie in enumerate(pool["xhs"], start=1):
            print(f"[{index}] {cookie}")
        print("\n===== 抖音 Cookie（dy）=====")
        for index, cookie in enumerate(pool["dy"], start=1):
            print(f"[{index}] {cookie}")
        print("===== Cookie 输出结束 =====\n")
    if args.no_upload:
        return 0

    try:
        upload_pool(args.output, args.host, args.remote_path)
    except (OSError, ValueError) as exc:
        print(f"上传失败：{exc}", file=sys.stderr)
        return 3
    except Exception as exc:
        print(f"上传失败：{type(exc).__name__}", file=sys.stderr)
        return 3
    print(f"已原子上传到 {args.host}:{args.remote_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
