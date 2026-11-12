#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
小红书登录 Cookie → 写入 cookies/cookies.json

默认 Playwright 无头浏览器：扫码 / 手机验证码。
滑块异常时加 --headed。纯 HTTP 加 --http。

用法:
  python scripts/xhs_login_to_pool.py qrcode
  python scripts/xhs_login_to_pool.py phone --phone 13800138000
  python scripts/xhs_login_to_pool.py qrcode --headed
  python scripts/xhs_login_to_pool.py qrcode --proxy
  python scripts/xhs_login_to_pool.py qrcode --upload --also-crawler
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional


BACKEND_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REMOTE_PATH = "~/projects/starx-backend/cookies/cookies.json"

if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

try:
    from dotenv import load_dotenv

    load_dotenv(BACKEND_ROOT / ".env")
except ImportError:
    pass


def save_to_pool(cookie: str, *, replace: bool) -> Path:
    from app.services.mediaspider.http_platforms.common.cookies import (
        save_platform_cookie,
    )

    path = save_platform_cookie("xhs", cookie, replace=replace)
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return path


def upload_pool(host: str, remote_path: str, local_path: Path) -> None:
    from scripts.cookie_sync.storage import upload_pool as _upload

    _upload(local_path, host, remote_path)


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="小红书登录（Playwright 扫码/验证码）→ cookies/cookies.json",
    )
    parser.add_argument(
        "mode",
        choices=("qrcode", "phone"),
        help="qrcode=App 扫码；phone=手机验证码（终端输入）",
    )
    parser.add_argument(
        "--phone",
        default="",
        help="手机号：phone 模式登录；qrcode 模式用于扫码后二次验证预填",
    )
    parser.add_argument("--timeout", type=float, default=180)
    parser.add_argument(
        "--headed",
        action="store_true",
        help="有头浏览器（本机排障/滑块）；服务器请用默认无头 + 终端 ASCII 码",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="兼容参数：默认已是无头",
    )
    parser.add_argument(
        "--http",
        action="store_true",
        help="改用纯 HTTP（不启浏览器）",
    )
    parser.add_argument(
        "--no-terminal-qr",
        action="store_true",
        help="尽量不打开系统图片查看器",
    )
    parser.add_argument("--replace", action="store_true")
    parser.add_argument("--print-cookie", action="store_true")
    parser.add_argument("--upload", action="store_true")
    parser.add_argument("--host", default="starx")
    parser.add_argument("--remote-path", default=DEFAULT_REMOTE_PATH)
    parser.add_argument("--also-crawler", action="store_true")
    parser.add_argument(
        "--proxy",
        action="store_true",
        help="启用快代理（登录默认直连；代理 IP 易触发扫码风控）",
    )
    parser.add_argument(
        "--no-proxy",
        action="store_true",
        help="兼容参数：默认已是直连",
    )
    return parser.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(argv)
    from app.services.mediaspider.http_platforms.xhs.login import (
        login_by_phone,
        login_by_qrcode,
    )

    use_proxy = bool(args.proxy) and not args.no_proxy
    method = "http" if args.http else "browser"
    # 服务器部署默认无头；需要看浏览器窗口时加 --headed
    if args.headed:
        headless = False
    else:
        headless = True
    try:
        if args.mode == "qrcode":
            cookie = login_by_qrcode(
                timeout_sec=args.timeout,
                show_in_terminal=not args.no_terminal_qr,
                use_proxy=use_proxy,
                headless=headless,
                method=method,
                phone=args.phone.strip(),
            )
        else:
            cookie = login_by_phone(
                phone=args.phone.strip(),
                timeout_sec=args.timeout,
                use_proxy=use_proxy,
                headless=headless,
                method=method,
            )
    except KeyboardInterrupt:
        print("\n已取消", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"登录失败: {exc}", file=sys.stderr)
        return 1

    path = save_to_pool(cookie, replace=args.replace)
    print(f"已写入 Cookie 池: {path}", file=sys.stderr)
    if args.print_cookie:
        print(cookie)

    if args.upload:
        try:
            upload_pool(args.host, args.remote_path, path)
            print(f"已上传到 {args.host}:{args.remote_path}", file=sys.stderr)
            if args.also_crawler:
                crawler_path = "~/projects/starx-crawler/cookies/cookies.json"
                upload_pool(args.host, crawler_path, path)
                print(f"已上传到 {args.host}:{crawler_path}", file=sys.stderr)
        except Exception as exc:
            print(f"上传失败: {exc}", file=sys.stderr)
            return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
