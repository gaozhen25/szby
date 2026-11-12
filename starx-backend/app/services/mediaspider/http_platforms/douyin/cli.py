# -*- coding: utf-8 -*-
"""
抖音关键词搜索 / 博主 / 单条 / 抖音号资料 CLI

JSON：
  data/dy/json/{关键词|昵称|作品ID}_{YYYY-MM-DD}.json
  data/dy/json/profile_{抖音号|self}_{YYYY-MM-DD}.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ..common.cookies import load_accounts, parse_keywords
from ..common.parallel import run_parallel_keywords
from ..common.store import (
    creator_json_path,
    detail_json_path,
    profile_json_path,
    search_json_path,
    write_json,
)
from .client import DouyinClient, PublishTimeType, SearchSortType


def _emit(data, out: str | Path | None = None, *, quiet: bool = False) -> None:
    text = json.dumps(data, ensure_ascii=False, indent=2)
    if out:
        path = write_json(data, Path(out))
        print(f"已写入 JSON: {path}", file=sys.stderr)
    if not quiet:
        print(text)


def _limit_contents(result: dict, limit: int) -> dict:
    if limit <= 0:
        return result
    result = dict(result)
    contents = list(result.get("contents") or [])[:limit]
    result["contents"] = contents
    result["content_count"] = len(contents)
    return result


def _client(args: argparse.Namespace) -> DouyinClient:
    from ..common.proxy import resolve_requests_proxies

    return DouyinClient(
        account_name=getattr(args, "account", "") or "",
        proxies=resolve_requests_proxies(),
    )


def _search_one_keyword(keyword: str, account, args: argparse.Namespace) -> dict:
    # 搜索强制直连：代理出口与登录态不一致时，第二次搜索极易 verify_check
    client = DouyinClient(
        cookie=account.cookie,
        ms_token=account.ms_token,
        proxies=None,
    )
    result = client.search_pages(
        keyword,
        max_pages=args.max_pages,
        page_size=args.page_size,
        sort_type=SearchSortType(args.sort),
        publish_time=PublishTimeType(args.publish_time),
        page_interval=max(float(args.page_interval or 0), 6.0),
    )
    result = _limit_contents(dict(result), args.limit)
    result["cookie_account"] = account.name
    return result


def cmd_search(args: argparse.Namespace) -> int:
    keywords = parse_keywords(*args.keywords)
    if not keywords:
        print("错误: 请提供至少一个关键词", file=sys.stderr)
        return 1

    accounts = load_accounts("dy", account_name=getattr(args, "account", "") or "")
    out_arg = args.out

    if len(keywords) == 1:
        kw = keywords[0]
        result = _search_one_keyword(kw, accounts[0], args)
        out = out_arg or str(search_json_path("dy", kw))
        _emit(result, out, quiet=args.quiet)
        return 0

    if out_arg:
        print(
            "错误: 多关键词并行时请勿使用 -o，将按关键词分别写入默认路径",
            file=sys.stderr,
        )
        return 1

    def worker(keyword: str, account) -> dict:
        print(f"[dy][{account.name}] 搜索: {keyword}", file=sys.stderr)
        result = _search_one_keyword(keyword, account, args)
        out = str(search_json_path("dy", keyword))
        write_json(result, Path(out))
        print(f"已写入 JSON: {Path(out).resolve()}", file=sys.stderr)
        return result

    results, errors = run_parallel_keywords(
        keywords,
        accounts,
        worker,
        max_workers=getattr(args, "workers", 0) or 0,
    )
    if not args.quiet:
        summary = {
            "platform": "dy",
            "crawl_type": "search",
            "keywords": keywords,
            "ok": list(results.keys()),
            "failed": errors,
            "content_count": sum(
                int(r.get("content_count") or len(r.get("contents") or []))
                for r in results.values()
            ),
        }
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    if errors and not results:
        return 1
    return 1 if errors else 0


def cmd_creator(args: argparse.Namespace) -> int:
    client = _client(args)
    result = client.get_creator_bundle(
        args.target,
        max_notes=args.max_notes,
        interval=args.interval,
        with_posts=not args.profile_only,
    )
    nickname = ""
    if result.get("creators"):
        nickname = result["creators"][0].get("display_name") or ""
    if not nickname:
        nickname = "unknown_creator"
    out = args.out or str(creator_json_path("dy", nickname))
    _emit(result, out, quiet=args.quiet)
    return 0


def cmd_detail(args: argparse.Namespace) -> int:
    client = _client(args)
    result = client.get_detail_bundle(args.target)
    content_id = "unknown_content"
    if result.get("contents"):
        content_id = result["contents"][0].get("aweme_id") or content_id
    out = args.out or str(detail_json_path("dy", content_id))
    _emit(result, out, quiet=args.quiet)
    return 0


def cmd_profile(args: argparse.Namespace) -> int:
    client = _client(args)
    target = (args.target or "").strip()
    result = client.get_profile_bundle(target)
    label = target or "self"
    creators = result.get("creators") or []
    if creators:
        label = (
            creators[0].get("unique_id")
            or creators[0].get("display_name")
            or label
        )
    out = args.out or str(profile_json_path("dy", label))
    _emit(result, out, quiet=args.quiet)
    if creators and not args.quiet:
        print(creators[0].get("profile_url") or "", file=sys.stderr)
    return 0


def _add_output_args(p: argparse.ArgumentParser) -> None:
    p.add_argument(
        "-o",
        "--out",
        default="",
        help="自定义输出路径；默认 data/dy/json/…_{日期}.json",
    )
    p.add_argument("-q", "--quiet", action="store_true", help="只写文件不打印")
    p.add_argument(
        "--account",
        default="",
        help="指定 cookies.json 账号：dy_1 或序号 1",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="抖音搜索 / 博主 / 单条 / 抖音号资料（JSON 落盘）"
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_search = sub.add_parser("search", help="关键词搜索（多词可并行）")
    p_search.add_argument(
        "keywords",
        nargs="+",
        help="一个或多个关键词；也可用逗号分隔：美食,旅游",
    )
    p_search.add_argument("--max-pages", type=int, default=1)
    p_search.add_argument("--page-size", type=int, default=10, help="默认每页 10 条")
    p_search.add_argument(
        "--limit",
        type=int,
        default=10,
        help="最终返回条数，默认 10",
    )
    p_search.add_argument(
        "--sort",
        type=int,
        default=0,
        choices=[0, 1, 2],
        help="0综合 1最多点赞 2最新",
    )
    p_search.add_argument(
        "--publish-time",
        type=int,
        default=0,
        choices=[0, 1, 7, 180],
        help="0不限 1一天 7一周 180半年",
    )
    p_search.add_argument("--page-interval", type=float, default=1.5)
    p_search.add_argument(
        "--workers",
        type=int,
        default=0,
        help="并行 worker 数，默认=启用 cookie 账号数",
    )
    _add_output_args(p_search)
    p_search.set_defaults(func=cmd_search)

    p_creator = sub.add_parser("creator", help="博主资料 + 最新作品")
    p_creator.add_argument("target", help="sec_user_id 或主页 URL")
    p_creator.add_argument("--max-notes", type=int, default=10, help="默认返回最新 10 条")
    p_creator.add_argument("--interval", type=float, default=1.0)
    p_creator.add_argument("--profile-only", action="store_true", help="只要资料")
    _add_output_args(p_creator)
    p_creator.set_defaults(func=cmd_creator)

    p_detail = sub.add_parser("detail", help="单条作品详情")
    p_detail.add_argument(
        "target",
        help="aweme_id、video/note URL、modal_id 链接或 v.douyin.com 短链",
    )
    _add_output_args(p_detail)
    p_detail.set_defaults(func=cmd_detail)

    p_profile = sub.add_parser(
        "profile",
        help="解析主页：无参数=当前账号；参数=抖音号/昵称搜索",
    )
    p_profile.add_argument(
        "target",
        nargs="?",
        default="",
        help="抖音号；省略则用 cookie 查自己",
    )
    _add_output_args(p_profile)
    p_profile.set_defaults(func=cmd_profile)

    args = parser.parse_args(argv)
    args.out = (args.out or "").strip() or None
    try:
        return args.func(args)
    except Exception as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
