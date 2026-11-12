# -*- coding: utf-8 -*-
"""
抖音热点宝 CLI

JSON：data/dyhot/json/搜索热点总榜_{YYYY-MM-DD}.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from platforms.common.store import current_date, json_dir, write_json

from .client import (
    DEFAULT_DATE_WINDOW,
    DEFAULT_MAX_COUNT,
    DEFAULT_PAGE_SIZE,
    DEFAULT_SUB_TYPE,
    DyHotClient,
)


def _default_out() -> Path:
    return json_dir("dyhot") / f"搜索热点总榜_{current_date()}.json"


def _emit(data, out: str | Path | None = None, *, quiet: bool = False) -> None:
    text = json.dumps(data, ensure_ascii=False, indent=2)
    if out:
        path = write_json(data, Path(out))
        print(f"已写入 JSON: {path}", file=sys.stderr)
    if not quiet:
        print(text)


def cmd_search_board(args: argparse.Namespace) -> int:
    client = DyHotClient()
    result = client.crawl_search_hot_board(
        max_count=args.max_count,
        page_size=args.page_size,
        sub_type=args.sub_type,
        date_window=args.date_window,
        page_interval=args.page_interval,
    )
    out = args.out or str(_default_out())
    _emit(result, out, quiet=args.quiet)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="抖音热点宝搜索热点总榜")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("search-board", help="搜索热点总榜（sub_type=3001）")
    p.add_argument(
        "-n",
        "--max-count",
        type=int,
        default=DEFAULT_MAX_COUNT,
        help=f"最多条数，默认前 {DEFAULT_MAX_COUNT} 条",
    )
    p.add_argument(
        "--page-size",
        type=int,
        default=DEFAULT_PAGE_SIZE,
        help="每页条数，默认 10",
    )
    p.add_argument(
        "--sub-type",
        type=int,
        default=DEFAULT_SUB_TYPE,
        help="榜单类型，搜索总榜默认 3001",
    )
    p.add_argument(
        "--date-window",
        type=int,
        default=DEFAULT_DATE_WINDOW,
        help="时间窗（小时），默认 24",
    )
    p.add_argument("--page-interval", type=float, default=1.0)
    p.add_argument("-o", "--out", default="", help="自定义输出路径")
    p.add_argument("-q", "--quiet", action="store_true", help="只写文件不打印")
    p.set_defaults(func=cmd_search_board)

    args = parser.parse_args(argv)
    args.out = (args.out or "").strip() or None
    try:
        return args.func(args)
    except Exception as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
