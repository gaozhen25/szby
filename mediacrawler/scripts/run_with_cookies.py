#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
纯 Cookie 跑通入口（小红书 / 抖音搜索 / 热点宝）。

服务器推荐：Cookie 落盘到 secrets/，换号只改文件。

  mkdir -p secrets && chmod 700 secrets
  cp secrets/dyhot.cookies.example secrets/dyhot.cookies
  # 编辑 secrets/*.cookies，粘贴真实 Cookie

  # 热点宝（榜单条数 / 跟搜）
  uv run python scripts/run_with_cookies.py dyhot --max-notes 50
  uv run python scripts/run_with_cookies.py dyhot --max-notes 100 --search-top-n 5 --notes-per-keyword 10

  # 抖音 / 小红书搜索
  uv run python scripts/run_with_cookies.py dy --keywords 世界杯 --max-notes 30
  uv run python scripts/run_with_cookies.py xhs --keywords 猫咪 --max-notes 40 --max-comments 20

优先级：--cookies > --cookies-file > 默认 secrets/<target>.cookies.json > 环境变量
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SECRETS_DIR = ROOT / "secrets"

DEFAULT_COOKIE_FILES = {
    "xhs": SECRETS_DIR / "cookies.json",
    "dy": SECRETS_DIR / "cookies.json",
    "dyhot": SECRETS_DIR / "dyhot.cookies.json",
    "ks": SECRETS_DIR / "cookies.json",
}

# 单平台 JSON（兼容）
PLATFORM_COOKIE_FILES = {
    "xhs": SECRETS_DIR / "xhs.cookies.json",
    "dy": SECRETS_DIR / "dy.cookies.json",
    "dyhot": SECRETS_DIR / "dyhot.cookies.json",
    "ks": SECRETS_DIR / "ks.cookies.json",
}

# 兼容旧纯文本
LEGACY_COOKIE_FILES = {
    "xhs": SECRETS_DIR / "xhs.cookies",
    "dy": SECRETS_DIR / "dy.cookies",
    "dyhot": SECRETS_DIR / "dyhot.cookies",
    "ks": SECRETS_DIR / "ks.cookies",
}

ENV_KEYS = {
    "xhs": ["XHS_COOKIES", "COOKIES"],
    "dy": ["DY_COOKIES", "COOKIES"],
    "dyhot": ["DYHOT_COOKIES", "DY_COOKIES", "COOKIES"],
    "ks": ["KS_COOKIES", "COOKIES"],
}


def _read_cookies_file(path: Path, platform: str) -> str:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from cookie_accounts import read_cookie_string

    return read_cookie_string(path, platform=platform)


def _cookies_from(
    args_cookies: str | None,
    cookies_file: str | None,
    target: str,
) -> tuple[str, str]:
    """返回 (cookies, source_label)。"""
    if args_cookies and args_cookies.strip():
        return args_cookies.strip(), "--cookies"

    if cookies_file:
        path = Path(cookies_file).expanduser()
        if not path.is_absolute():
            path = (ROOT / path).resolve()
        if not path.is_file():
            raise FileNotFoundError(f"Cookie 文件不存在: {path}")
        return _read_cookies_file(path, target), str(path)

    # 优先合并池 secrets/cookies.json
    default_path = DEFAULT_COOKIE_FILES[target]
    if default_path.is_file():
        try:
            cookie = _read_cookies_file(default_path, target)
            if cookie:
                return cookie, str(default_path)
        except ValueError:
            pass

    platform_path = PLATFORM_COOKIE_FILES[target]
    if platform_path.is_file():
        return _read_cookies_file(platform_path, target), str(platform_path)

    legacy = LEGACY_COOKIE_FILES[target]
    if legacy.is_file():
        return _read_cookies_file(legacy, target), str(legacy)

    for key in ENV_KEYS[target]:
        val = (os.environ.get(key) or "").strip()
        if val:
            return val, f"env:{key}"

    return "", ""


def _run(argv: list[str]) -> int:
    # 日志里不打印完整 Cookie，避免泄漏
    shown = []
    skip_next = False
    for part in argv:
        if skip_next:
            skip_next = False
            shown.append("<redacted>")
            continue
        if part == "--cookies":
            shown.append(part)
            skip_next = True
            continue
        shown.append(part)
    print("[run_with_cookies]", " ".join(shown))
    return subprocess.call(argv, cwd=str(ROOT))


def _append_common_counts(cmd: list[str], args: argparse.Namespace) -> None:
    if args.max_notes is not None:
        cmd.extend(["--crawler_max_notes_count", str(args.max_notes)])
    if args.max_comments is not None:
        cmd.extend(["--max_comments_count_singlenotes", str(args.max_comments)])
    if args.get_comment is not None:
        cmd.extend(["--get_comment", "true" if args.get_comment else "false"])


def build_xhs_cmd(args: argparse.Namespace, cookies: str) -> list[str]:
    cmd = [
        "uv",
        "run",
        "main.py",
        "--platform",
        "xhs",
        "--lt",
        "cookie",
        "--cookies",
        cookies,
        "--type",
        "search",
        "--keywords",
        args.keywords,
        "--save_data_option",
        args.save_data_option,
        "--headless",
        "true",
        "--enable_cdp",
        "false",
    ]
    _append_common_counts(cmd, args)
    # 指定了评论条数但未显式关评论时，默认开评论
    if args.max_comments is not None and args.get_comment is None:
        cmd.extend(["--get_comment", "true"])
    return cmd


def build_dy_cmd(args: argparse.Namespace, cookies: str) -> list[str]:
    cmd = [
        "uv",
        "run",
        "main.py",
        "--platform",
        "dy",
        "--lt",
        "cookie",
        "--cookies",
        cookies,
        "--type",
        "search",
        "--keywords",
        args.keywords,
        "--save_data_option",
        args.save_data_option,
        "--headless",
        "true",
        "--enable_cdp",
        "false",
    ]
    _append_common_counts(cmd, args)
    if args.max_comments is not None and args.get_comment is None:
        cmd.extend(["--get_comment", "true"])
    return cmd


def build_dyhot_cmd(args: argparse.Namespace, cookies: str) -> list[str]:
    # 热点宝与小红书一样走 CDP，复用 browser_data/cdp_dyhot_user_data_dir 登录态
    cmd = [
        "uv",
        "run",
        "main.py",
        "--platform",
        "dyhot",
        "--lt",
        "cookie",
        "--cookies",
        cookies,
        "--save_data_option",
        args.save_data_option,
        "--headless",
        "true",
        "--enable_cdp",
        "true",
    ]
    # 榜单条数：--max-notes → --dyhot_max_count
    if args.max_notes is not None:
        cmd.extend(["--dyhot_max_count", str(args.max_notes)])
    if args.search_top_n is not None:
        cmd.extend(["--dyhot_search_top_n", str(args.search_top_n)])
    if args.notes_per_keyword is not None:
        cmd.extend(["--dyhot_search_notes_count", str(args.notes_per_keyword)])
    if args.max_comments is not None:
        cmd.extend(["--max_comments_count_singlenotes", str(args.max_comments)])
    return cmd


def build_ks_cmd(args: argparse.Namespace, cookies: str) -> list[str]:
    cmd = [
        "uv",
        "run",
        "main.py",
        "--platform",
        "ks",
        "--lt",
        "cookie",
        "--cookies",
        cookies,
        "--type",
        "search",
        "--keywords",
        args.keywords,
        "--save_data_option",
        args.save_data_option,
        "--headless",
        "true",
        "--enable_cdp",
        "false",
    ]
    _append_common_counts(cmd, args)
    if args.max_comments is not None and args.get_comment is None:
        cmd.extend(["--get_comment", "true"])
    return cmd


def _missing_hint(target: str) -> str:
    path = DEFAULT_COOKIE_FILES.get(target) or PLATFORM_COOKIE_FILES[target]
    example = SECRETS_DIR / "cookies.json.example"
    env = ENV_KEYS[target][0]
    return (
        f"缺少 Cookie。请先导出合并池：\n"
        f"  uv run python scripts/export_cookies.py\n"
        f"  # 生成 {path.relative_to(ROOT)}（格式见 {example.relative_to(ROOT)}）\n"
        f"  uv run python scripts/run_with_cookies.py {target} --max-notes 30\n"
        f"\n"
        f"也可：--cookies-file /path/to.cookies.json 或 export {env}='...'"
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="用 Cookie 跑通：xhs / dy / dyhot / ks（单账号）。多账号并发见 run_multi_cookies.py",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例:\n"
            "  uv run python scripts/run_with_cookies.py dyhot --max-notes 50\n"
            "  uv run python scripts/run_with_cookies.py dy --keywords 世界杯 --max-notes 30\n"
            "  uv run python scripts/run_with_cookies.py xhs --keywords 猫咪 --max-notes 40\n"
            "  uv run python scripts/run_with_cookies.py ks --keywords 足球 --max-notes 40\n"
            "  # 多平台/多 Cookie 并发:\n"
            "  uv run python scripts/run_multi_cookies.py --platforms xhs,dy,ks --keywords 美食 --concurrency 4\n"
        ),
    )
    parser.add_argument(
        "target",
        choices=["xhs", "dy", "dyhot", "ks"],
        help="xhs | dy | dyhot | ks",
    )
    parser.add_argument(
        "--cookies",
        default="",
        help="完整 Cookie 串（不推荐在服务器 bash 历史里用）",
    )
    parser.add_argument(
        "--cookies-file",
        default="",
        help="Cookie 文件路径；默认 secrets/<target>.cookies.json",
    )
    parser.add_argument("--keywords", default="美食", help="搜索关键词（xhs/dy）")
    parser.add_argument(
        "--max-notes",
        type=int,
        default=None,
        help="条数：xhs/dy=搜索笔记/视频数；dyhot=热点榜最大条数",
    )
    parser.add_argument(
        "--max-comments",
        type=int,
        default=None,
        help="每条笔记/视频的一级评论上限（xhs/dy 设了会自动开评论）",
    )
    parser.add_argument(
        "--get-comment",
        dest="get_comment",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="是否拉评论（xhs/dy）；默认：设了 --max-comments 则为开",
    )
    parser.add_argument(
        "--search-top-n",
        type=int,
        default=None,
        help="仅 dyhot：跟搜关键词个数；0=榜单全部",
    )
    parser.add_argument(
        "--notes-per-keyword",
        type=int,
        default=None,
        help="仅 dyhot：每个热词搜索的视频数",
    )
    parser.add_argument(
        "--save_data_option",
        default="json",
        choices=["json", "jsonl", "csv", "sqlite", "db", "excel"],
        help="落盘格式",
    )
    args = parser.parse_args()

    try:
        cookies, source = _cookies_from(
            args.cookies, args.cookies_file or None, args.target
        )
    except FileNotFoundError as e:
        print(str(e), file=sys.stderr)
        return 2

    if not cookies or "REPLACE_ME" in cookies:
        print(_missing_hint(args.target), file=sys.stderr)
        if cookies and "REPLACE_ME" in cookies:
            print("检测到示例占位 REPLACE_ME，请换成真实 Cookie。", file=sys.stderr)
        return 2

    print(f"[run_with_cookies] cookie source: {source} ({len(cookies)} chars)")
    if args.max_notes is not None:
        print(f"[run_with_cookies] max-notes={args.max_notes}")

    if args.target == "xhs":
        if "web_session" not in cookies:
            print("警告：小红书 Cookie 通常需要包含 web_session", file=sys.stderr)
        return _run(build_xhs_cmd(args, cookies))

    if args.target == "dy":
        return _run(build_dy_cmd(args, cookies))

    if args.target == "ks":
        if "passToken" not in cookies:
            print("警告：快手 Cookie 通常需要包含 passToken", file=sys.stderr)
        return _run(build_ks_cmd(args, cookies))

    return _run(build_dyhot_cmd(args, cookies))


if __name__ == "__main__":
    raise SystemExit(main())
