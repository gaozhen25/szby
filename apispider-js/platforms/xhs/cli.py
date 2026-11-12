# -*- coding: utf-8 -*-
"""
小红书搜索 / 博主 / 单条 CLI

JSON 命名对齐 MediaCrawler：
  data/xhs/json/{关键词|昵称|笔记ID}_{YYYY-MM-DD}.json
结构对齐 mediaspider CrawlResult。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from platforms.common.cookies import load_accounts, parse_keywords, remove_platform_cookies
from platforms.common.parallel import run_parallel_keywords
from platforms.common.store import (
    creator_json_path,
    detail_json_path,
    sanitize_filename,
    search_json_path,
    write_json,
    crawl_result,
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


def _client(args: argparse.Namespace) -> XhsClient:
    nick = (getattr(args, "nick", "") or "").strip()
    if nick:
        from .im import resolve_client_by_nick

        client, _ = resolve_client_by_nick(nick)
        return client
    return XhsClient(account_name=getattr(args, "account", "") or "")


def cmd_im(args: argparse.Namespace) -> int:
    """私信：dump=拉全部会话历史；poll=轮询新消息；send=发文本。"""
    from datetime import date

    from .im import (
        account_summary,
        conversation_filename,
        dump_all_conversations,
        format_message_line,
        resolve_chat_target,
        resolve_client_by_nick,
        run_poll_loop,
        send_text,
    )

    nick = (getattr(args, "nick", "") or "").strip()
    if nick:
        client, summary = resolve_client_by_nick(nick)
    else:
        client = XhsClient(account_name=getattr(args, "account", "") or "")
        summary = account_summary(client)
    if summary.get("nickname") or summary.get("user_id"):
        print(
            f"[im] account nickname={summary.get('nickname')!r} "
            f"user_id={summary.get('user_id')} red_id={summary.get('red_id')!r}",
            file=sys.stderr,
        )
    mode = args.mode

    if mode == "send":
        from platforms.common.cookies import parse_keywords

        text = (getattr(args, "text", "") or "").strip()
        if not text:
            raise ValueError("send 需要 --text，例如: xhs im send --text '你好'")
        to_raw = (getattr(args, "to", "") or "").strip()
        if not to_raw:
            raise ValueError("send 需要 --to <对方昵称或chat_user_id>，例如: xhs im send --to 心动 --text '你好'")
        chat_user_id, peer_name = resolve_chat_target(
            client, to_raw, chat_limit=args.chat_limit
        )
        result = send_text(
            client,
            chat_user_id,
            text,
            headed=bool(getattr(args, "headed", False)),
            peer_name=peer_name,
        )
        print(
            json.dumps(
                {
                    "ok": bool(result),
                    "to": {"chat_user_id": chat_user_id, "peer": peer_name},
                    "text": text,
                    "result": result,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0 if result else 1

    if mode == "dump":
        data = dump_all_conversations(
            client, chat_limit=args.chat_limit, page_size=args.page_size
        )
        convs = list(data.get("conversations") or [])
        me_nick = sanitize_filename(
            str((data.get("account") or {}).get("nickname") or "im")
        )
        out_arg = Path(args.out) if args.out else None
        written: list[Path] = []
        if out_arg and out_arg.suffix.lower() == ".json" and len(convs) == 1:
            written.append(write_json(convs[0], out_arg))
        else:
            if out_arg and out_arg.suffix.lower() == ".json":
                base = out_arg.parent / out_arg.stem
            elif out_arg:
                base = out_arg
            else:
                base = Path("data") / "xhs" / "im" / me_nick
            for conv in convs:
                name = conversation_filename(
                    str(conv.get("peer") or ""),
                    str(conv.get("chat_user_id") or ""),
                )
                written.append(write_json(conv, base / name))
        for path in written:
            print(f"已写入 JSON: {path}", file=sys.stderr)
        if not args.quiet:
            for conv in convs:
                print(
                    f"\n# {conv.get('peer')} ({conv.get('message_count')} 条)",
                    file=sys.stderr,
                )
                for m in conv.get("messages") or []:
                    print(
                        format_message_line(conv.get("peer") or "", m),
                        file=sys.stderr,
                    )
        return 0

    print(
        f"[im] poll interval={args.poll_interval}s "
        f"seconds={'forever' if args.seconds <= 0 else args.seconds}",
        file=sys.stderr,
    )
    if mode == "listen":
        from .im_ws import receive_messages_ws

        my_uid = str(summary.get("user_id") or "")
        if not my_uid:
            raise ValueError("无法获取当前账号 user_id")
        print(
            f"[im] WS 实时接收，监听 {args.seconds or '无限'} 秒，Ctrl+C 退出…",
            file=sys.stderr,
        )
        try:
            for msg in receive_messages_ws(
                client.cookie,
                my_uid,
                seconds=args.seconds,
            ):
                who = msg.get("nickname") or msg.get("sender") or "?"
                direction = "我→对方" if msg.get("outgoing") else "对方→我"
                print(
                    f"[im][{msg.get('time') or '?'}] {direction} "
                    f"来自:{who} store:{msg.get('store_id')} "
                    f"msg_id:{str(msg.get('message_id') or '')[:32]} "
                    f"text:{msg.get('text') or ''}",
                    flush=True,
                )
        except KeyboardInterrupt:
            print("[im] stopped", file=sys.stderr)
        return 0

    try:
        run_poll_loop(
            client,
            interval=args.poll_interval,
            seconds=args.seconds,
            chat_limit=args.chat_limit,
        )
    except KeyboardInterrupt:
        print("[im] stopped", file=sys.stderr)
    return 0


def _search_one_keyword(
    keyword: str,
    cookie: str,
    args: argparse.Namespace,
) -> dict:
    client = XhsClient(cookie=cookie)
    sort = (
        SearchSortType[args.sort.upper()]
        if args.sort.isupper()
        else SearchSortType(args.sort)
    )

    if args.max_pages > 1 or (args.start_page and args.start_page != args.page):
        start_page = args.start_page if args.start_page else args.page
        return client.search_notes_pages(
            keyword=keyword,
            start_page=start_page,
            max_pages=args.max_pages,
            page_size=args.page_size,
            sort=sort,
            note_type=SearchNoteType(args.note_type),
            interval=args.interval,
            page_interval=args.page_interval,
            with_detail=not args.list_only,
        )

    if args.list_only:
        raw = client.search_notes(
            keyword=keyword,
            page=args.page,
            page_size=args.page_size,
            sort=sort,
            note_type=SearchNoteType(args.note_type),
        )
        return normalize_search_response(raw, source_keyword=keyword)

    return client.search_notes_with_detail(
        keyword=keyword,
        page=args.page,
        page_size=args.page_size,
        sort=sort,
        note_type=SearchNoteType(args.note_type),
        interval=args.interval,
    )


def cmd_me(args: argparse.Namespace) -> int:
    client = _client(args)
    _emit(client.user_me(), args.out, quiet=args.quiet)
    return 0


def cmd_accounts(args: argparse.Namespace) -> int:
    """用 cookie 池逐个调 user/me；过期/无效/半登录条目从 cookies.json 删除。"""
    accounts = load_accounts("xhs", account_name=getattr(args, "account", "") or "")
    rows = []
    to_remove: list[str] = []
    for acc in accounts:
        row = {
            "account": acc.name,
            "ok": False,
            "nickname": "",
            "red_id": "",
            "user_id": "",
            "error": "",
            "removed": False,
        }
        try:
            client = XhsClient(cookie=acc.cookie)
            me = client.user_me() or {}
            nickname = str(me.get("nickname") or "").strip()
            red_id = str(me.get("red_id") or "").strip()
            user_id = str(me.get("user_id") or "").strip()
            row.update(
                {
                    "ok": True,
                    "nickname": nickname,
                    "red_id": red_id,
                    "user_id": user_id,
                    "desc": me.get("desc") or "",
                }
            )
            # 仅有 user_id、无昵称/小红书号 = 扫码未完成的半登录态，视为无效
            if not user_id or (not nickname and not red_id):
                row["ok"] = False
                row["error"] = "半登录/资料不完整（无昵称与小红书号）"
                if acc.name != "env":
                    to_remove.append(acc.cookie)
                    row["removed"] = True
        except Exception as exc:
            row["error"] = str(exc)
            if acc.name != "env":
                to_remove.append(acc.cookie)
                row["removed"] = True
        rows.append(row)
        if not args.quiet:
            if row["removed"]:
                print(f"{acc.name}\t已删除（无效）\t{row['error']}", file=sys.stderr)
            else:
                status = row["nickname"] or row["error"] or "?"
                print(f"{acc.name}\t{status}", file=sys.stderr)

    if to_remove:
        path = remove_platform_cookies("xhs", to_remove)
        _cleanup_xhs_states_for_cookies(to_remove)
        if not args.quiet:
            print(
                f"[xhs] 已从 {path} 删除 {len(to_remove)} 条无效 cookie",
                file=sys.stderr,
            )

    _emit(
        {"platform": "xhs", "accounts": rows, "removed": len(to_remove)},
        args.out,
        quiet=args.quiet,
    )
    return 0 if any(r["ok"] for r in rows) else 1


def _cleanup_xhs_states_for_cookies(cookies: list[str]) -> None:
    """尽量清理与失效 cookie 对应的 xhs_states 登录态。"""
    try:
        import json
        from pathlib import Path

        root = Path(__file__).resolve().parents[2]
        index_path = root / "cookies" / "xhs_states" / "index.json"
        if not index_path.is_file():
            return
        prefixes = set()
        for cookie in cookies:
            for part in (cookie or "").split(";"):
                part = part.strip()
                if part.lower().startswith("web_session="):
                    prefixes.add(part.split("=", 1)[1].strip()[:8])
        if not prefixes:
            return
        data = json.loads(index_path.read_text(encoding="utf-8"))
        accounts = data.get("accounts") if isinstance(data, dict) else None
        if not isinstance(accounts, dict):
            return
        changed = False
        for key, meta in list(accounts.items()):
            if not isinstance(meta, dict):
                continue
            pref = str(meta.get("web_session_prefix") or "")
            if pref and pref in prefixes:
                rel = meta.get("storage_state") or ""
                if rel:
                    sp = root / rel
                    if sp.is_file():
                        sp.unlink()
                accounts.pop(key, None)
                changed = True
        if changed:
            index_path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
    except Exception:
        pass


def cmd_profile(args: argparse.Namespace) -> int:
    client = _client(args)
    result = client.get_profile_bundle(args.target or "")
    _emit(result, args.out, quiet=args.quiet)
    creators = result.get("creators") or []
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

    if args.all:
        raw_notes = client.get_all_notes_by_creator(
            user_id,
            max_notes=args.max_notes,
            xsec_token=xsec_token,
            xsec_source=xsec_source,
        )
        extra = {}
    else:
        page = client.get_notes_by_creator(
            user_id,
            cursor=args.cursor,
            page_size=args.page_size,
            xsec_token=xsec_token,
            xsec_source=xsec_source,
        )
        extra = {
            "has_more": bool(page.get("has_more")),
            "cursor": page.get("cursor") or "",
        }
        raw_notes = page.get("notes") or []

    if args.list_only:
        contents = normalize_creator_notes(raw_notes, xsec_source=xsec_source)
    else:
        contents = client.enrich_notes_with_detail(
            raw_notes,
            default_xsec_source=xsec_source,
            interval=args.interval,
        )

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
        help="自定义输出路径；默认 data/xhs/json/{关键词|昵称|笔记ID}_{日期}.json",
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


def cmd_login(args: argparse.Namespace) -> int:
    """有头浏览器扫码登录，cookie 写入 cookies/cookies.json。"""
    import asyncio

    from platforms.common.login.session import LoginSession
    from platforms.xhs.login_qr import run_xhs_qr_login

    name = (getattr(args, "name", "") or "").strip()
    timeout = float(getattr(args, "timeout", 300) or 300)
    # login 子命令默认有头；--headless 才无头
    headed = not bool(getattr(args, "headless", False))
    sess = LoginSession(
        session_id="cli",
        platform="xhs",
        name=name,
    )
    print(
        f"[xhs] 登录模式={'有头浏览器' if headed else '无头'} "
        f"timeout={timeout}s name={name or '-'}",
        file=sys.stderr,
    )
    if headed:
        print("[xhs] 将弹出浏览器，请扫码；如有短信/安全验证请在窗口内完成", file=sys.stderr)

    async def _run():
        await run_xhs_qr_login(sess, timeout=timeout, headed=headed)

    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        sess.cancel = True
        print("[xhs] 已取消", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 1

    print(
        json.dumps(
            {
                "status": sess.status,
                "message": sess.message,
                "profile": sess.profile,
                "cookie_saved": bool(sess.cookie),
                "error": sess.error,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if sess.status == "success" else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="小红书搜索 / 博主 / 单条（mediaspider JSON）"
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_me = sub.add_parser("me", help="当前登录用户（原始 user/me）")
    _add_output_args(p_me)
    p_me.set_defaults(func=cmd_me)

    p_login = sub.add_parser(
        "login",
        help="有头浏览器扫码登录（cookie 写入 cookies.json）",
    )
    p_login.add_argument("--name", default="", help="账号备注名 / profile 名")
    p_login.add_argument(
        "--timeout",
        type=float,
        default=300,
        help="等待扫码超时秒数，默认 300",
    )
    p_login.add_argument(
        "--headless",
        action="store_true",
        help="无头模式（默认有头，方便过二次验证）",
    )
    p_login.set_defaults(func=cmd_login)

    p_accounts = sub.add_parser(
        "accounts",
        help="检测 cookies.json 账号；过期/无效的自动删除",
    )
    _add_output_args(p_accounts)
    p_accounts.set_defaults(func=cmd_accounts)

    p_profile = sub.add_parser(
        "profile",
        help="解析主页链接：无参数=当前账号；参数=小红书号/昵称搜索",
    )
    p_profile.add_argument(
        "target",
        nargs="?",
        default="",
        help="小红书号（如 11387533599）；省略则用 cookie 查自己",
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
        help="固定用 20，其它值服务端常返回空",
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
    p_search.add_argument("--interval", type=float, default=0.8, help="详情请求间隔秒")
    p_search.add_argument(
        "--workers",
        type=int,
        default=0,
        help="并行 worker 数，默认=启用 cookie 账号数",
    )
    _add_output_args(p_search)
    p_search.set_defaults(func=cmd_search)

    p_creator = sub.add_parser("creator", help="博主资料 + 笔记")
    p_creator.add_argument("target", help="user_id 或主页完整 URL")
    p_creator.add_argument("--xsec-token", default="")
    p_creator.add_argument("--xsec-source", default="pc_feed")
    p_creator.add_argument("--cursor", default="")
    p_creator.add_argument(
        "-n", "--page-size", type=int, default=10, help="每页条数，默认 10"
    )
    p_creator.add_argument("--all", action="store_true", help="翻页拉取多页笔记")
    p_creator.add_argument("--max-notes", type=int, default=10, help="默认返回 10 条笔记")
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

    p_im = sub.add_parser("im", help="私信：拉历史 / 轮询新消息 / 发文本 / WS实时接收")
    p_im.add_argument(
        "mode",
        nargs="?",
        default="poll",
        choices=["dump", "poll", "send", "listen"],
        help="dump=拉取全部会话历史；poll=HTTP轮询新消息；send=发文本；listen=WS长连接实时接收",
    )
    p_im.add_argument(
        "--nick",
        default="",
        help="按 cookies 账号昵称/小红书号/user_id 选择",
    )
    p_im.add_argument("--chat-limit", type=int, default=100, help="最多会话数")
    p_im.add_argument("--page-size", type=int, default=30, help="历史分页大小")
    p_im.add_argument(
        "--poll-interval",
        type=float,
        default=2.0,
        help="poll 间隔秒",
    )
    p_im.add_argument(
        "--seconds",
        type=int,
        default=0,
        help="poll 监听秒数，0=一直听",
    )
    p_im.add_argument(
        "--to",
        default="",
        help="send：对方昵称 / 小红书号 / chat_user_id（在会话列表中解析）",
    )
    p_im.add_argument(
        "--text",
        default="",
        help="send：私信文本内容，如 --text '你好'",
    )
    p_im.add_argument(
        "--headed",
        action="store_true",
        help="send：HTTP 接口不可用时，弹出浏览器用 UI 发送",
    )
    _add_output_args(p_im)
    p_im.set_defaults(func=cmd_im)

    args = parser.parse_args(argv)
    args.out = (getattr(args, "out", None) or "").strip() or None
    try:
        return args.func(args)
    except Exception as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
