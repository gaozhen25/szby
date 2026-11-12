#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""MediaCrawlerService 试跑脚本（支持多关键词并行）。

用法:
  python scripts/media_spider.py xhs 美食
  python scripts/media_spider.py xhs 美食 美女 少妇 人妻
  python scripts/media_spider.py dy 足球 篮球

多 Cookie 时按关键词并行；单 Cookie 时一次批量。
启用 STARX_MEDIASPIDER_ENABLE_IP_PROXY 时走快代理。
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(_project_root / ".env")

from app.services.account_report.collection.keyword_parallel import (  # noqa: E402
    crawl_keywords_with_cookie_pool,
)
from app.services.mediaspider.cookie_pool import load_cookie_pool  # noqa: E402
from app.services.mediaspider.models import CrawlerExecutionError  # noqa: E402
from app.services.mediaspider.service import MediaCrawlerService  # noqa: E402


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="并行试跑 MediaSpider 关键词搜索")
    parser.add_argument(
        "platform",
        choices=("xhs", "dy"),
        help="平台：xhs / dy",
    )
    parser.add_argument(
        "keywords",
        nargs="+",
        help="一个或多个关键词",
    )
    parser.add_argument(
        "-n",
        "--max-notes",
        type=int,
        default=5,
        help="每个关键词最多条数，默认 5",
    )
    parser.add_argument(
        "--sleep",
        type=float,
        default=0.5,
        help="请求间隔秒，默认 0.5",
    )
    return parser.parse_args(argv)


async def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    service = MediaCrawlerService()
    cookie_pool = load_cookie_pool()
    started = time.perf_counter()
    try:
        result = await crawl_keywords_with_cookie_pool(
            crawler=service,
            cookie_pool=cookie_pool,
            platform=args.platform,
            keywords=args.keywords,
            runtime_options={
                "max_notes_count": args.max_notes,
                "enable_comments": False,
                "max_sleep_sec": args.sleep,
                "enable_cdp_mode": False,
                "headless": True,
            },
        )
        print(
            {
                "ok": True,
                "platform": args.platform,
                "keywords": list(args.keywords),
                "elapsed_sec": round(time.perf_counter() - started, 1),
                "content_count": result.content_count,
                "warnings": list(result.discovery_warnings or []),
                "sample_titles": [
                    (c.get("title") or c.get("desc") or "")[:40]
                    for c in (result.contents or [])[:4]
                ],
            }
        )
        return 0
    except CrawlerExecutionError as exc:
        print(
            {
                "ok": False,
                "platform": args.platform,
                "keywords": list(args.keywords),
                "elapsed_sec": round(time.perf_counter() - started, 1),
                "error": str(exc),
                "cause_type": getattr(exc, "cause_type", None),
                "failure": getattr(getattr(exc, "failure", None), "code", None),
            }
        )
        return 1


if __name__ == "__main__":
    import asyncio

    raise SystemExit(asyncio.run(main()))
