#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
多 Cookie + 多平台 / 多关键词并发爬取。

每个任务起一个独立 `main.py` 子进程，避免全局 config 冲突。

示例:
  # 同平台多关键词并发
  uv run python scripts/run_multi_cookies.py --platforms xhs \\
    --keywords 美食,旅行,猫咪 --parallel-keywords --concurrency 3

  # 多平台 + 多关键词
  uv run python scripts/run_multi_cookies.py --platforms xhs,dy,ks \\
    --keywords 美食,足球 --parallel-keywords --concurrency 4

  # 多关键词顺序（一个进程里逗号分隔，不拆进程）
  uv run python scripts/run_multi_cookies.py --platforms xhs \\
    --keywords 美食,旅行 --no-parallel-keywords
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, replace
from pathlib import Path
from typing import List, Optional, Sequence

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))

from cookie_accounts import PLATFORMS, CookieAccount, load_accounts_for_platform  # noqa: E402


@dataclass
class Job:
    account: CookieAccount
    keywords: str  # 传给 --keywords；dyhot 为空
    cmd: List[str]
    label: str


def _safe_id(text: str) -> str:
    return re.sub(r"[^\w.-]+", "_", (text or "").strip())[:48] or "kw"


def _split_keywords(raw: str) -> List[str]:
    return [k.strip() for k in (raw or "").split(",") if k.strip()]


def _redact(cmd: Sequence[str]) -> str:
    shown: List[str] = []
    skip = False
    for part in cmd:
        if skip:
            shown.append("<redacted>")
            skip = False
            continue
        if part == "--cookies":
            shown.append(part)
            skip = True
            continue
        shown.append(part)
    return " ".join(shown)


def _build_cmd(
    account: CookieAccount,
    args: argparse.Namespace,
    *,
    keywords: str,
) -> List[str]:
    platform = account.platform
    cmd: List[str] = [
        "uv",
        "run",
        "main.py",
        "--platform",
        platform,
        "--lt",
        "cookie",
        "--cookies",
        account.cookies,
        "--account_id",
        account.account_id,
        "--save_data_option",
        args.save_data_option,
        "--headless",
        "true" if args.headless else "false",
        # 热点宝与导出共用 CDP 目录以复用登录态；其余平台仍用 Playwright 无头
        "--enable_cdp",
        "true" if platform == "dyhot" else "false",
    ]

    # 非 default 账号 / 关键词并行时隔离落盘与 browser_data
    if account.account_id and account.account_id != "default":
        cmd.extend(
            [
                "--save_data_path",
                str(ROOT / "data" / "by_account" / f"{platform}_{account.account_id}"),
            ]
        )

    if platform in ("xhs", "dy", "ks"):
        cmd.extend(["--type", "search", "--keywords", keywords])
        if args.max_notes is not None:
            cmd.extend(["--crawler_max_notes_count", str(args.max_notes)])
        enable_comment = args.get_comment
        if enable_comment is None and args.max_comments is not None:
            enable_comment = True
        if args.max_comments is not None:
            cmd.extend(["--max_comments_count_singlenotes", str(args.max_comments)])
        if enable_comment is not None:
            cmd.extend(["--get_comment", "true" if enable_comment else "false"])
    elif platform == "dyhot":
        if args.max_notes is not None:
            cmd.extend(["--dyhot_max_count", str(args.max_notes)])
        if args.search_top_n is not None:
            cmd.extend(["--dyhot_search_top_n", str(args.search_top_n)])
        if args.notes_per_keyword is not None:
            cmd.extend(["--dyhot_search_notes_count", str(args.notes_per_keyword)])

    if args.max_concurrency_num is not None:
        cmd.extend(["--max_concurrency_num", str(args.max_concurrency_num)])

    return cmd


def _run_job(job: Job) -> tuple[str, int]:
    print(f"[run_multi] START {job.label} <- {job.account.source}")
    print(f"[run_multi]   {_redact(job.cmd)}")
    code = subprocess.call(job.cmd, cwd=str(ROOT))
    print(f"[run_multi] DONE  {job.label} exit={code}")
    return job.label, code


def _expand_jobs(
    accounts: List[CookieAccount],
    args: argparse.Namespace,
    keywords_list: List[str],
) -> List[Job]:
    """按账号 × 关键词展开任务。"""
    jobs: List[Job] = []
    for acc in accounts:
        platform = acc.platform
        if platform == "dyhot":
            # 热点宝无关键词
            cmd = _build_cmd(acc, args, keywords="")
            jobs.append(
                Job(
                    account=acc,
                    keywords="",
                    cmd=cmd,
                    label=f"{platform}/{acc.account_id}",
                )
            )
            continue

        if not keywords_list:
            keywords_list = ["美食"]

        if args.parallel_keywords:
            for kw in keywords_list:
                # 同账号多关键词并行时，account_id 追加关键词，隔离 Chrome profile
                job_acc = replace(
                    acc,
                    account_id=f"{acc.account_id}__{_safe_id(kw)}",
                )
                cmd = _build_cmd(job_acc, args, keywords=kw)
                jobs.append(
                    Job(
                        account=job_acc,
                        keywords=kw,
                        cmd=cmd,
                        label=f"{platform}/{acc.account_id}/kw={kw}",
                    )
                )
        else:
            joined = ",".join(keywords_list)
            cmd = _build_cmd(acc, args, keywords=joined)
            jobs.append(
                Job(
                    account=acc,
                    keywords=joined,
                    cmd=cmd,
                    label=f"{platform}/{acc.account_id}/kw={joined}",
                )
            )
    return jobs


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="多 Cookie / 多平台 / 多关键词并发爬取",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--platforms",
        default="xhs,dy,dyhot,ks",
        help="逗号分隔平台: xhs,dy,dyhot,ks",
    )
    parser.add_argument(
        "--cookies-file",
        action="append",
        default=[],
        help="显式 Cookie 文件（可重复）；多平台时忽略并自动发现",
    )
    parser.add_argument(
        "--keywords",
        default="美食",
        help="搜索关键词，逗号分隔（xhs/dy/ks）；配合 --parallel-keywords 可并发",
    )
    parser.add_argument(
        "--parallel-keywords",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="多关键词是否拆成并行子进程（默认开）；--no-parallel-keywords 则单进程顺序搜",
    )
    parser.add_argument("--max-notes", type=int, default=None)
    parser.add_argument("--max-comments", type=int, default=None)
    parser.add_argument(
        "--get-comment",
        dest="get_comment",
        action=argparse.BooleanOptionalAction,
        default=None,
    )
    parser.add_argument("--search-top-n", type=int, default=None)
    parser.add_argument("--notes-per-keyword", type=int, default=None)
    parser.add_argument(
        "--concurrency",
        type=int,
        default=4,
        help="同时跑的最大子进程数",
    )
    parser.add_argument("--max_concurrency_num", type=int, default=None)
    parser.add_argument(
        "--save_data_option",
        default="json",
        choices=["json", "jsonl", "csv", "sqlite", "db", "excel"],
    )
    parser.add_argument(
        "--headless",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="是否无头；Cookie 跑爬虫默认无头 CDP",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(list(argv) if argv is not None else None)

    platforms = [p.strip() for p in args.platforms.split(",") if p.strip()]
    for p in platforms:
        if p not in PLATFORMS:
            print(f"不支持平台: {p}，可选: {', '.join(PLATFORMS)}", file=sys.stderr)
            return 2

    keywords_list = _split_keywords(args.keywords)
    jobs: List[Job] = []

    for platform in platforms:
        try:
            if args.cookies_file and len(platforms) == 1:
                accounts = load_accounts_for_platform(
                    platform, cookies_files=args.cookies_file
                )
            elif args.cookies_file and len(platforms) > 1:
                print(
                    "[run_multi] 多平台模式下忽略 --cookies-file，改为自动发现 secrets/",
                    file=sys.stderr,
                )
                accounts = load_accounts_for_platform(platform)
            else:
                accounts = load_accounts_for_platform(platform)
        except FileNotFoundError as e:
            print(str(e), file=sys.stderr)
            return 2

        if not accounts:
            print(
                f"[run_multi] 跳过 {platform}：未找到有效 Cookie",
                file=sys.stderr,
            )
            continue

        jobs.extend(_expand_jobs(accounts, args, keywords_list))

    if not jobs:
        print("没有可运行的任务。请先导出 Cookie。", file=sys.stderr)
        return 2

    mode = "关键词并行" if args.parallel_keywords else "关键词顺序(单进程)"
    print(
        f"[run_multi] 共 {len(jobs)} 个任务，并发上限 {args.concurrency}，模式={mode}"
    )
    for job in jobs:
        print(f"  - {job.label} ({len(job.account.cookies)} chars)")

    if args.dry_run:
        for job in jobs:
            print(_redact(job.cmd))
        return 0

    concurrency = max(1, int(args.concurrency))
    failed = 0
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = [pool.submit(_run_job, job) for job in jobs]
        for fut in as_completed(futures):
            label, code = fut.result()
            if code != 0:
                failed += 1
                print(f"[run_multi] FAIL {label}", file=sys.stderr)

    elapsed = time.time() - t0
    print(
        f"[run_multi] 全部结束：ok={len(jobs) - failed} fail={failed} "
        f"elapsed={elapsed:.1f}s"
    )
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
