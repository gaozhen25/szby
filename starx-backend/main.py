# -*- coding: utf-8 -*-
"""
统一入口（对齐 js/main.py 命令）

用法:
  python main.py xhs search 美食
  python main.py dy search 足球
  python main.py xhs creator 'https://www.xiaohongshu.com/user/profile/...'
  python main.py dy creator 'https://www.douyin.com/user/...'
  python main.py xhs detail 'https://www.xiaohongshu.com/explore/...?xsec_token=...'
  python main.py dy detail 'https://www.douyin.com/video/...'
  python main.py xhs profile
  python main.py xhs profile 小红书号
  python main.py dy profile
  python main.py dy profile 抖音号

默认:
  - 小红书关键词搜索默认 20 条；抖音默认 10 条
  - 博主返回最新 10 条内容
  - profile / detail 同样落盘到 data/…
"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

try:
    from dotenv import load_dotenv

    load_dotenv(_ROOT / ".env")
except Exception:
    pass


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] in ("-h", "--help"):
        print(__doc__.strip())
        return 0
    platform = args.pop(0).lower()
    if platform in ("xhs", "xiaohongshu", "red"):
        from app.services.mediaspider.http_platforms.xhs.cli import main as xhs_main

        return xhs_main(args)
    if platform in ("dy", "douyin"):
        from app.services.mediaspider.http_platforms.douyin.cli import main as dy_main

        return dy_main(args)
    print(f"未知平台: {platform}（支持 xhs / dy）", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
