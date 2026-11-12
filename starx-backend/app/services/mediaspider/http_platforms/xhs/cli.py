# -*- coding: utf-8 -*-
"""
小红书搜索 / 博主 / 单条 / 小红书号资料 CLI

JSON：
  data/xhs/json/{关键词|昵称|笔记ID}_{YYYY-MM-DD}.json
  data/xhs/json/profile_{小红书号|self}_{YYYY-MM-DD}.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ..common.cookies import load_accounts, parse_keywords
from ..common.parallel import run_parallel_keywords
from ..common.store import (
    crawl_result,
    creator_json_path,
    detail_json_path,
    profile_json_path,
    search_json_path,
    write_json,
)
from .client import SearchNoteType, SearchSortType, XhsClient, parse_creator_url
from .normalize import (
    normalize_creator,
    normalize_creator_notes,
    normalize_search_response,
)


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


def _client(args: argparse.Namespace) -> XhsClient:
    from ..common.proxy import resolve_requests_proxies

    return XhsClient(
        account_name=getattr(args, "account", "") or "",
        proxies=resolve_requests_proxies(),
    )


def _search_one_keyword(
    keyword: str,
    cookie: str,
    args: argparse.Namespace,
) -> dict:
    from ..common.proxy import resolve_requests_proxies

    client = XhsClient(cookie=cookie, proxies=resolve_requests_proxies())
    sort = (
        SearchSortType[args.sort.upper()]
        if args.sort.isupper()
        else SearchSortType(args.sort)
    )

    if args.max_pages > 1 or (args.start_page and args.start_page != args.page):
        start_page = args.start_page if args.start_page else args.page
        result = client.search_notes_pages(
            keyword=keyword,
            start_page=start_page,
            max_pages=args.max_pages,
            page_size=args.page_size,
            sort=sort,
            note_type=SearchNoteType(args.note_type),
            interval=args.interval,
            page_interval=args.page_interval,
            with_detail=not args.list_only,
            max_contents=args.limit,
        )
    elif args.list_only:
        raw = client.search_notes(
            keyword=keyword,
            page=args.page,
            page_size=args.page_size,
            sort=sort,
            note_type=SearchNoteType(args.note_type),
        )
        result = normalize_search_response(raw, source_keyword=keyword)
        result = _limit_contents(dict(result), args.limit)
    else:
        result = client.search_notes_with_detail(
            keyword=keyword,
            page=args.page,
            page_size=args.page_size,
            sort=sort,
            note_type=SearchNoteType(args.note_type),
            interval=args.interval,
            max_contents=args.limit,
        )
    return dict(result)


def cmd_me(args: argparse.Namespace) -> int:
    client = _client(args)
    out = args.out or str(profile_json_path("xhs", "me"))
    _emit(client.user_me(), out, quiet=args.quiet)
    return 0


def cmd_profile(args: argparse.Namespace) -> int:
    client = _client(args)
    target = (args.target or "").strip()
    result = client.get_profile_bundle(target)
    label = target or "self"
    creators = result.get("creators") or []
    if creators:
        label = creators[0].get("red_id") or creators[0].get("display_name") or label
    out = args.out or str(profile_json_path("xhs", label))
    _emit(result, out, quiet=args.quiet)
    if creators and not args.quiet:
        print(creators[0].get("profile_url") or "", file=sys.stderr)
    return 0


def cmd_search(args: argparse.Namespace) -> int:
    keywords = parse_keywords(*args.keywords)
    if not keywords:
        print("错误: 请提供至少一个关键词", file=sys.stderr)
        return 1

    accounts = load_accounts("xhs", account_name=getattr(args, "account", "") or "")
    out_arg = args.out

    if len(keywords) == 1:
        kw = keywords[0]
        result = dict(_search_one_keyword(kw, accounts[0].cookie, args))
        result["cookie_account"] = accounts[0].name
        out = out_arg or str(search_json_path("xhs", kw))
        _emit(result, out, quiet=args.quiet)
        return 0

    if out_arg:
        print(
            "错误: 多关键词并行时请勿使用 -o，将按关键词分别写入默认路径",
            file=sys.stderr,
        )
        return 1

    def worker(keyword: str, account) -> dict:
        print(f"[xhs][{account.name}] 搜索: {keyword}", file=sys.stderr)
        result = dict(_search_one_keyword(keyword, account.cookie, args))
        result["cookie_account"] = account.name
        out = str(search_json_path("xhs", keyword))
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
            "platform": "xhs",
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
    target = args.target
    xsec_token = args.xsec_token or ""
    xsec_source = args.xsec_source or "pc_feed"
    if target.startswith("http"):
        info = parse_creator_url(target)
        user_id = info["user_id"]
        xsec_token = xsec_token or info["xsec_token"]
        xsec_source = info["xsec_source"] or xsec_source
        creator_url = target.split("?")[0]
    else:
        user_id = target
        creator_url = f"https://www.xiaohongshu.com/user/profile/{user_id}"

    creators = []
    if not args.skip_profile:
        raw_profile = client.get_creator_info(
            user_id, xsec_token=xsec_token, xsec_source=xsec_source
        )
        creator = normalize_creator(user_id, raw_profile)
        if creator:
            creators.append(creator)

    # 默认拉最新 max_notes 条
    raw_notes = client.get_all_notes_by_creator(
        user_id,
        max_notes=args.max_notes,
        xsec_token=xsec_token,
        xsec_source=xsec_source,
    )
    extra: dict = {}

    if args.list_only:
        contents = normalize_creator_notes(raw_notes, xsec_source=xsec_source)
    else:
        contents = client.enrich_notes_with_detail(
            raw_notes,
            default_xsec_token=xsec_token,
            default_xsec_source=xsec_source,
            interval=args.interval,
        )
    contents = contents[: args.max_notes]

    nickname = (creators[0].get("display_name") if creators else "") or user_id
    out = args.out or str(creator_json_path("xhs", nickname))
    result = crawl_result(
        platform="xhs",
        crawl_type="creator",
        creator_url=creator_url,
        creators=creators,
        contents=contents,
        **extra,
    )
    _emit(result, out, quiet=args.quiet)
    return 0


def cmd_detail(args: argparse.Namespace) -> int:
    client = _client(args)
    result = client.get_detail_bundle(
        args.target,
        xsec_token=args.xsec_token or "",
        xsec_source=args.xsec_source or "",
    )
    content_id = "unknown_content"
    if result.get("contents"):
        content_id = result["contents"][0].get("note_id") or content_id
    out = args.out or str(detail_json_path("xhs", content_id))
    _emit(result, out, quiet=args.quiet)
    return 0


def _add_output_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "-o",
        "--out",
        default="",
        help="自定义输出路径；默认 data/xhs/json/…_{日期}.json",
    )
    parser.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="只写文件，不在终端打印 JSON",
    )
    parser.add_argument(
        "--account",
        default="",
        help="指定 cookies.json 账号：xhs_1 或序号 1",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="小红书搜索 / 博主 / 单条 / 小红书号资料（JSON 落盘）"
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_me = sub.add_parser("me", help="当前登录用户（原始 user/me）")
    _add_output_args(p_me)
    p_me.set_defaults(func=cmd_me)

    p_profile = sub.add_parser(
        "profile",
        help="解析主页：无参数=当前账号；参数=小红书号/昵称搜索",
    )
    p_profile.add_argument(
        "target",
        nargs="?",
        default="",
        help="小红书号；省略则用 cookie 查自己",
    )
    _add_output_args(p_profile)
    p_profile.set_defaults(func=cmd_profile)

    p_search = sub.add_parser("search", help="关键词搜索笔记（多词可并行）")
    p_search.add_argument(
        "keywords",
        nargs="+",
        help="一个或多个关键词；也可用逗号分隔：美食,旅游",
    )
    p_search.add_argument("-p", "--page", type=int, default=1, help="单页模式页码")
    p_search.add_argument(
        "--start-page",
        type=int,
        default=0,
        help="多页模式起始页（配合 --max-pages）",
    )
    p_search.add_argument("--max-pages", type=int, default=1, help="最多翻页数，默认 1")
    p_search.add_argument("--page-interval", type=float, default=1.5, help="翻页间隔秒")
    p_search.add_argument(
        "-n",
        "--page-size",
        type=int,
        default=20,
        help="接口固定用 20，其它值常返回空",
    )
    p_search.add_argument(
        "--limit",
        type=int,
        default=20,
        help="最终返回条数，默认 20（对齐 js）",
    )
    p_search.add_argument(
        "--sort",
        default="general",
        choices=["general", "popularity_descending", "time_descending"],
    )
    p_search.add_argument("--note-type", type=int, default=0, help="0全部 1视频 2图文")
    p_search.add_argument(
        "--list-only",
        action="store_true",
        help="只拿搜索列表，不拉详情",
    )
    p_search.add_argument("--interval", type=float, default=0.8, help="详情请求间隔秒，默认 0.8")
    p_search.add_argument(
        "--workers",
        type=int,
        default=0,
        help="并行 worker 数，默认=启用 cookie 账号数",
    )
    _add_output_args(p_search)
    p_search.set_defaults(func=cmd_search)

    p_creator = sub.add_parser("creator", help="博主资料 + 最新笔记")
    p_creator.add_argument("target", help="user_id 或主页完整 URL")
    p_creator.add_argument("--xsec-token", default="")
    p_creator.add_argument("--xsec-source", default="pc_feed")
    p_creator.add_argument("--cursor", default="")
    p_creator.add_argument(
        "-n", "--page-size", type=int, default=10, help="每页条数，默认 10"
    )
    p_creator.add_argument("--all", action="store_true", help="兼容参数：默认已按最新 N 条拉取")
    p_creator.add_argument("--max-notes", type=int, default=10, help="默认返回最新 10 条")
    p_creator.add_argument("--skip-profile", action="store_true")
    p_creator.add_argument(
        "--list-only",
        action="store_true",
        help="只要列表，不拉详情",
    )
    p_creator.add_argument("--interval", type=float, default=0.8)
    _add_output_args(p_creator)
    p_creator.set_defaults(func=cmd_creator)

    p_detail = sub.add_parser("detail", help="单条笔记详情")
    p_detail.add_argument(
        "target",
        help="note_id 或 explore/discovery URL（建议带 xsec_token）",
    )
    p_detail.add_argument("--xsec-token", default="", help="未含在 URL 时必填")
    p_detail.add_argument("--xsec-source", default="", help="默认 pc_search")
    _add_output_args(p_detail)
    p_detail.set_defaults(func=cmd_detail)

    args = parser.parse_args(argv)
    args.out = (args.out or "").strip() or None
    try:
        return args.func(args)
    except Exception as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
