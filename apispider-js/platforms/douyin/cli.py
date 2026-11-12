# -*- coding: utf-8 -*-
"""
抖音关键词搜索 / 博主 / 单条 CLI

JSON 命名对齐 MediaCrawler：
  data/dy/json/{关键词|昵称|作品ID}_{YYYY-MM-DD}.json
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
    creator_excel_path,
    creator_json_path,
    creator_media_dir,
    detail_json_path,
    sanitize_filename,
    search_excel_path,
    search_json_path,
    write_json,
)
from .client import DouyinClient, PublishTimeType, SearchSortType
from .normalize import crawl_result


def _emit(data, out: str | Path | None = None, *, quiet: bool = False) -> None:
    text = json.dumps(data, ensure_ascii=False, indent=2)
    if out:
        path = write_json(data, Path(out))
        print(f"已写入 JSON: {path}", file=sys.stderr)
    if not quiet:
        print(text)


def _client(args: argparse.Namespace) -> DouyinClient:
    return DouyinClient(account_name=getattr(args, "account", "") or "")


def _search_one_keyword(keyword: str, account, args: argparse.Namespace) -> dict:
    client = DouyinClient(cookie=account.cookie, ms_token=account.ms_token)
    accounts = getattr(args, "_accounts", None) or []
    if accounts and not getattr(args, "no_rotate_cookies", False):
        client.set_cookie_pool(accounts, start_name=account.name)
    min_images = int(getattr(args, "min_images", 0) or 0)
    # 多词并行时均分目标张数，避免单词拖太久
    nkw = max(1, int(getattr(args, "_keyword_count", 1) or 1))
    per_kw = (min_images + nkw - 1) // nkw if min_images > 0 else 0
    result = client.search_pages(
        keyword,
        max_pages=args.max_pages,
        page_size=args.page_size,
        sort_type=SearchSortType(args.sort),
        publish_time=PublishTimeType(args.publish_time),
        page_interval=args.page_interval,
        min_images=per_kw,
        images_only=bool(getattr(args, "images_only", False)),
    )
    result = dict(result)
    result["cookie_account"] = client.account_name or account.name
    return result


def _enrich_image_details(
    contents: list[dict],
    client: DouyinClient,
    *,
    interval: float = 1.0,
    quiet: bool = False,
) -> list[dict]:
    """图文补拉 detail，拿全 image_list（搜索结果常只有封面）。"""
    from .normalize import normalize_aweme

    out: list[dict] = []
    total = len(contents)
    for i, item in enumerate(contents, start=1):
        if item.get("type") != "image":
            out.append(item)
            continue
        imgs = item.get("image_list") or []
        if len(imgs) >= 2:
            out.append(item)
            continue
        aweme_id = str(item.get("aweme_id") or "")
        if not aweme_id:
            out.append(item)
            continue
        if not quiet and (i == 1 or i % 20 == 0 or i == total):
            print(
                f"[dy] 补图文详情 {i}/{total} id={aweme_id}",
                file=sys.stderr,
            )
        try:
            raw = client.get_aweme_detail(aweme_id)
            enriched = normalize_aweme(
                raw, source_keyword=str(item.get("source_keyword") or "")
            )
            if enriched and (enriched.get("image_list") or []):
                # 保留搜索侧展示名等兜底字段
                for k in ("display_name", "nickname", "source_keyword"):
                    if not enriched.get(k) and item.get(k):
                        enriched[k] = item[k]
                out.append(enriched)
            else:
                out.append(item)
        except Exception as exc:
            if not quiet:
                print(f"[dy] detail 失败 {aweme_id}: {exc}", file=sys.stderr)
            out.append(item)
        if interval > 0:
            import time

            time.sleep(interval)
    return out


def _merge_search_results(
    keywords: list[str], results: dict[str, dict]
) -> dict:
    seen: set[str] = set()
    contents: list[dict] = []
    for kw in keywords:
        r = results.get(kw) or {}
        for item in r.get("contents") or []:
            aid = str(item.get("aweme_id") or "")
            if aid and aid in seen:
                continue
            if aid:
                seen.add(aid)
            contents.append(item)
    return crawl_result(
        crawl_type="search",
        keywords=keywords,
        contents=contents,
        content_count=len(contents),
    )


def _export_search_excel(
    result: dict, args: argparse.Namespace, label: str
) -> None:
    if not getattr(args, "excel", False):
        return
    from .excel_export import export_creator_excel

    excel_out = (getattr(args, "excel_out", "") or "").strip() or str(
        search_excel_path("dy", label)
    )
    media = creator_media_dir("dy", label)
    export_creator_excel(
        result,
        out=excel_out,
        media_dir=media,
        max_images=int(getattr(args, "excel_max_images", 0) or 0),
        retries=int(getattr(args, "excel_retries", 3) or 3),
        progress=not args.quiet,
    )


def cmd_search(args: argparse.Namespace) -> int:
    keywords = parse_keywords(*args.keywords)
    if not keywords:
        print("错误: 请提供至少一个关键词", file=sys.stderr)
        return 1

    accounts = load_accounts("dy", account_name=getattr(args, "account", "") or "")
    out_arg = args.out
    args._keyword_count = len(keywords)
    args._accounts = accounts
    want_excel = bool(getattr(args, "excel", False))
    enrich = bool(getattr(args, "enrich_images", False) or want_excel)

    if len(keywords) == 1:
        kw = keywords[0]
        result = _search_one_keyword(kw, accounts[0], args)
        if enrich:
            client = DouyinClient(
                cookie=accounts[0].cookie, ms_token=accounts[0].ms_token
            )
            result["contents"] = _enrich_image_details(
                list(result.get("contents") or []),
                client,
                interval=float(getattr(args, "page_interval", 1.5) or 1.5),
                quiet=args.quiet,
            )
            result["content_count"] = len(result["contents"])
        out = out_arg or str(search_json_path("dy", kw))
        _emit(result, out, quiet=args.quiet)
        _export_search_excel(result, args, kw)
        return 0

    if out_arg and not want_excel:
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
    merged = _merge_search_results(keywords, results)
    if enrich and merged.get("contents"):
        client = DouyinClient(
            cookie=accounts[0].cookie, ms_token=accounts[0].ms_token
        )
        if not getattr(args, "no_rotate_cookies", False):
            client.set_cookie_pool(accounts, start_name=accounts[0].name)
        merged["contents"] = _enrich_image_details(
            list(merged.get("contents") or []),
            client,
            interval=float(getattr(args, "page_interval", 1.5) or 1.5),
            quiet=args.quiet,
        )
        merged["content_count"] = len(merged["contents"])

    label = "美业医美职场plog"
    if want_excel or out_arg:
        merged_out = out_arg or str(search_json_path("dy", label))
        write_json(merged, Path(merged_out))
        print(f"已写入合并 JSON: {Path(merged_out).resolve()}", file=sys.stderr)
        _export_search_excel(merged, args, label)

    if not args.quiet:
        from .excel_export import count_content_images

        summary = {
            "platform": "dy",
            "crawl_type": "search",
            "keywords": keywords,
            "ok": list(results.keys()),
            "failed": errors,
            "content_count": len(merged.get("contents") or []),
            "image_count": count_content_images(list(merged.get("contents") or [])),
        }
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    if errors and not results:
        return 1
    return 1 if errors else 0


def cmd_creator(args: argparse.Namespace) -> int:
    accounts = load_accounts("dy")
    start = getattr(args, "account", "") or ""
    client = DouyinClient(account_name=start)
    # 默认启用 cookie 池轮换；--account 只决定起始号
    if not getattr(args, "no_rotate_cookies", False):
        client.set_cookie_pool(accounts, start_name=start)
    max_notes = args.max_notes
    if getattr(args, "all", False):
        max_notes = max(max_notes, 10_000)
    max_comments = int(args.max_comments)
    if not args.quiet:
        pool = f"cookie池={len(accounts)}" if not args.no_rotate_cookies else f"单号={client.account_name}"
        print(
            f"[dy] creator target={args.target!r} max_notes={max_notes} "
            f"comments={'all' if args.with_comments and max_comments <= 0 else ('on/' + str(max_comments) if args.with_comments else 'off')} "
            f"{pool} resume={not args.no_resume}",
            file=sys.stderr,
        )
    try:
        result = client.get_creator_bundle(
            args.target,
            max_notes=max_notes,
            interval=args.interval,
            with_posts=not args.profile_only,
            with_comments=bool(args.with_comments) and not args.profile_only,
            max_comments=max_comments,
            progress=not args.quiet,
            resume=not args.no_resume,
            checkpoint_path=args.checkpoint or None,
            clear_checkpoint=bool(args.fresh),
            refetch_posts=bool(getattr(args, "refetch_posts", False)),
        )
    except KeyboardInterrupt:
        print("[dy] 已中断（断点已保存）", file=sys.stderr)
        return 130
    nickname = ""
    if result.get("creators"):
        nickname = (
            result["creators"][0].get("display_name")
            or result["creators"][0].get("unique_id")
            or ""
        )
    if not nickname:
        nickname = "unknown_creator"
    out = args.out or str(creator_json_path("dy", nickname))
    _emit(result, out, quiet=args.quiet)
    if getattr(args, "excel", False):
        from .excel_export import export_creator_excel

        excel_out = (getattr(args, "excel_out", "") or "").strip() or str(
            creator_excel_path("dy", nickname)
        )
        export_creator_excel(
            result,
            out=excel_out,
            max_images=int(getattr(args, "excel_max_images", 8) or 8),
            retries=int(getattr(args, "excel_retries", 3) or 3),
            progress=not args.quiet,
        )
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
    result = client.get_profile_bundle(args.target or "")
    _emit(result, args.out, quiet=args.quiet)
    creators = result.get("creators") or []
    if creators and not args.quiet:
        print(creators[0].get("profile_url") or "", file=sys.stderr)
    return 0


def cmd_accounts(args: argparse.Namespace) -> int:
    """用 cookie 池逐个调 profile/self；过期/无效条目从 cookies.json 删除。

    仅删除明确失效（空响应 / 半登录）；网络/代理错误不删，避免误伤。
    """
    accounts = load_accounts("dy", account_name=getattr(args, "account", "") or "")
    rows = []
    to_remove: list[str] = []

    def _is_network_error(msg: str) -> bool:
        text = (msg or "").lower()
        needles = (
            "proxyerror",
            "proxy",
            "connection",
            "timed out",
            "timeout",
            "max retries",
            "temporarily unavailable",
            "name or service not known",
            "nodename nor servname",
            "network is unreachable",
            "ssl",
            "certificate",
        )
        return any(n in text for n in needles)

    for acc in accounts:
        row = {
            "account": acc.name,
            "ok": False,
            "nickname": "",
            "unique_id": "",
            "sec_uid": "",
            "error": "",
            "removed": False,
        }
        try:
            client = DouyinClient(cookie=acc.cookie, ms_token=acc.ms_token)
            user = client.get_self_profile()
            row.update(
                {
                    "ok": bool(user),
                    "nickname": user.get("nickname") or "",
                    "unique_id": user.get("unique_id") or user.get("short_id") or "",
                    "sec_uid": user.get("sec_uid") or "",
                    "uid": str(user.get("uid") or ""),
                    "fans_count": user.get("follower_count")
                    or user.get("mplatform_followers_count"),
                    "signature": user.get("signature") or "",
                }
            )
            if not user:
                row["error"] = "profile/self 空响应"
                if acc.name != "env":
                    to_remove.append(acc.cookie)
                    row["removed"] = True
            elif not (row.get("nickname") or row.get("unique_id") or row.get("uid")):
                row["ok"] = False
                row["error"] = "半登录/资料不完整"
                if acc.name != "env":
                    to_remove.append(acc.cookie)
                    row["removed"] = True
        except Exception as exc:
            row["error"] = str(exc)
            # 网络/代理失败 ≠ cookie 失效，绝不删除
            if acc.name != "env" and not _is_network_error(str(exc)):
                # 明确业务鉴权失败才删
                low = str(exc).lower()
                auth_fail = any(
                    k in low
                    for k in (
                        "login",
                        "未登录",
                        "login expired",
                        "status_code=8",
                        "status_code=9",
                        "请重新登录",
                    )
                )
                if auth_fail:
                    to_remove.append(acc.cookie)
                    row["removed"] = True
                else:
                    row["error"] = f"检测失败(未删除): {exc}"
            elif _is_network_error(str(exc)):
                row["error"] = f"网络/代理错误(未删除): {exc}"
        rows.append(row)
        if not args.quiet:
            if row["removed"]:
                print(f"{acc.name}\t已删除（无效）\t{row['error']}", file=sys.stderr)
            else:
                status = row["nickname"] or row["error"] or "?"
                print(f"{acc.name}\t{status}", file=sys.stderr)

    if to_remove:
        path = remove_platform_cookies("dy", to_remove)
        if not args.quiet:
            print(
                f"[dy] 已从 {path} 删除 {len(to_remove)} 条无效 cookie",
                file=sys.stderr,
            )

    _emit(
        {"platform": "dy", "accounts": rows, "removed": len(to_remove)},
        args.out,
        quiet=args.quiet,
    )
    return 0 if any(r["ok"] for r in rows) else 1


def cmd_im(args: argparse.Namespace) -> int:
    """私信：dump / poll / send。"""
    from .im import (
        DEFAULT_AUTO_REPLIES,
        DEFAULT_CONVERSATION_ID,
        DEFAULT_CONVERSATION_SHORT_ID,
        account_summary,
        conversation_filename,
        dump_all_conversations,
        dump_conversation,
        format_chat_line,
        load_auth,
        resolve_auth_by_nick,
        run_poll_loop,
        send_many,
        send_text,
    )

    nick = (getattr(args, "nick", "") or "").strip()
    if nick:
        auth, summary = resolve_auth_by_nick(nick)
    else:
        auth = load_auth(account_name=getattr(args, "account", "") or "")
        summary = account_summary(auth)
    if summary.get("nickname") or summary.get("uid"):
        print(
            f"[im] account nickname={summary.get('nickname')!r} "
            f"uid={summary.get('uid')} unique_id={summary.get('unique_id')!r}",
            file=sys.stderr,
        )
    explicit_cid = (args.conversation_id or "").strip()
    cid = explicit_cid or DEFAULT_CONVERSATION_ID
    cshort = int(args.conversation_short_id or DEFAULT_CONVERSATION_SHORT_ID)
    watch_all = bool(getattr(args, "all", False)) or (
        args.mode in ("poll", "dump") and not explicit_cid
    )

    if args.mode == "send":
        from platforms.common.cookies import parse_keywords

        text = (getattr(args, "text", "") or "").strip()
        if not text:
            raise ValueError("send 需要 --text，例如: dy im send --text '你好'")
        to_raw = getattr(args, "to", None) or []
        if isinstance(to_raw, str):
            to_raw = [to_raw]
        targets = parse_keywords(*[str(x) for x in to_raw])
        headed = bool(getattr(args, "headed", False))
        workers = int(getattr(args, "workers", 0) or 0)

        if len(targets) > 1:
            rows = send_many(auth, text, targets, workers=workers, headed=headed)
            print(json.dumps({"ok": all(r.get("ok") for r in rows), "results": rows}, ensure_ascii=False, indent=2))
            return 0 if all(r.get("ok") for r in rows) else 1

        to_uid = targets[0] if targets else ""
        use_cid = "" if to_uid and not (args.conversation_id or "").strip() else cid
        use_short = (
            0
            if to_uid and not (args.conversation_id or "").strip()
            else cshort
        )
        result = send_text(
            auth,
            text,
            conversation_id=use_cid,
            conversation_short_id=use_short,
            conversation_ticket=(getattr(args, "ticket", "") or "").strip(),
            to_user_id=to_uid,
            headed=headed,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result.get("ok") else 1

    if args.mode == "dump":
        if watch_all:
            data = dump_all_conversations(auth, limit=args.limit)
            convs = list(data.get("conversations") or [])
        else:
            data = dump_conversation(auth, cid, cshort, limit=args.limit)
            convs = [data]
        me = data.get("account") or data.get("me") or {}
        me_nick = sanitize_filename(str(me.get("nickname") or "im"))
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
                base = Path("data") / "dy" / "im" / me_nick
            for conv in convs:
                name = conversation_filename(conv.get("peer") or {})
                written.append(write_json(conv, base / name))
        for path in written:
            print(f"已写入 JSON: {path}", file=sys.stderr)
        if not args.quiet:
            for conv in convs:
                title = conv.get("title") or conversation_filename(conv.get("peer") or {})
                print(f"\n======== {title} ========", file=sys.stderr)
                last_day = ""
                for item in conv.get("messages") or []:
                    when = str(item.get("time") or "")
                    day = when[:10]
                    if day and day != last_day:
                        print(f"------ {day} ------", file=sys.stderr)
                        last_day = day
                    print(format_chat_line(item), file=sys.stderr)
        return 0

    auto_replies = []
    if getattr(args, "auto_reply", False):
        extra = [str(t).strip() for t in (getattr(args, "reply_text", None) or []) if str(t).strip()]
        auto_replies = extra or list(DEFAULT_AUTO_REPLIES)

    print(
        f"[im] poll interval={args.poll_interval}s "
        f"seconds={'forever' if args.seconds <= 0 else args.seconds} "
        f"conversation={'ALL' if watch_all else cid}"
        + (f" auto-reply={len(auto_replies)}" if auto_replies else ""),
        file=sys.stderr,
    )
    try:
        run_poll_loop(
            auth,
            conversation_id=cid,
            conversation_short_id=cshort,
            interval=args.poll_interval,
            seconds=args.seconds,
            auto_replies=auto_replies or None,
            headed=bool(getattr(args, "headed", False)),
            all_conversations=watch_all,
        )
    except KeyboardInterrupt:
        print("[im] stopped", file=sys.stderr)
    return 0


def _add_output_args(p: argparse.ArgumentParser) -> None:
    p.add_argument(
        "-o",
        "--out",
        default="",
        help="自定义输出路径；默认 data/dy/json/{关键词|昵称|作品ID}_{日期}.json",
    )
    p.add_argument("-q", "--quiet", action="store_true", help="只写文件不打印")
    p.add_argument(
        "--account",
        default="",
        help="指定 cookies.json 账号：dy_1 或序号 1",
    )


def cmd_login(args: argparse.Namespace) -> int:
    """有头浏览器扫码登录，cookie 写入 cookies/cookies.json。"""
    import asyncio

    from platforms.common.login.session import LoginSession
    from platforms.douyin.login_qr import run_dy_qr_login

    name = (getattr(args, "name", "") or "").strip()
    timeout = float(getattr(args, "timeout", 300) or 300)
    headed = not bool(getattr(args, "headless", False))
    sess = LoginSession(
        session_id="cli",
        platform="dy",
        name=name,
    )
    print(
        f"[dy] 登录模式={'有头浏览器' if headed else '无头'} "
        f"timeout={timeout}s name={name or '-'}",
        file=sys.stderr,
    )
    if headed:
        print("[dy] 将弹出浏览器，请用抖音 App 扫码", file=sys.stderr)

    async def _run():
        await run_dy_qr_login(sess, timeout=timeout, headed=headed)

    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        sess.cancel = True
        print("[dy] 已取消", file=sys.stderr)
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
        description="抖音搜索 / 博主 / 单条（mediaspider JSON）"
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

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
        help="无头模式（默认有头，方便扫码）",
    )
    p_login.set_defaults(func=cmd_login)

    p_search = sub.add_parser("search", help="关键词搜索（多词可并行）")
    p_search.add_argument(
        "keywords",
        nargs="+",
        help="一个或多个关键词；也可用逗号分隔：美食,旅游",
    )
    p_search.add_argument("--max-pages", type=int, default=1)
    p_search.add_argument("--page-size", type=int, default=10, help="默认每页 10 条")
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
    p_search.add_argument(
        "--images-only",
        action="store_true",
        help="只保留图文作品（跳过视频）",
    )
    p_search.add_argument(
        "--min-images",
        type=int,
        default=0,
        help="目标图片张数（多词均分）；0=不限制，只按 --max-pages",
    )
    p_search.add_argument(
        "--enrich-images",
        action="store_true",
        help="对图文补拉详情拿全图（--excel 时默认开启）",
    )
    p_search.add_argument(
        "--excel",
        action="store_true",
        help="导出 Excel：标题/标签/嵌入缩略图/无水印链接（一行一张图）",
    )
    p_search.add_argument(
        "--excel-out",
        default="",
        help="Excel 路径；默认 data/dy/excel/{标签}_{日期}.xlsx",
    )
    p_search.add_argument(
        "--excel-max-images",
        type=int,
        default=0,
        help="每条作品最多导出几张图，0=全部",
    )
    p_search.add_argument(
        "--excel-retries",
        type=int,
        default=3,
        help="单张图片下载失败重试次数",
    )
    _add_output_args(p_search)
    p_search.set_defaults(func=cmd_search)

    p_creator = sub.add_parser(
        "creator",
        help="博主资料 + 作品（可选评论）；支持主页URL / sec_uid / 抖音号",
    )
    p_creator.add_argument(
        "target",
        help="主页 URL、sec_user_id、抖音号或昵称",
    )
    p_creator.add_argument(
        "--max-notes",
        type=int,
        default=10,
        help="最多作品数，默认 10；配合 --all 可拉全量",
    )
    p_creator.add_argument(
        "--all",
        action="store_true",
        help="尽量爬取全部作品（内部上限 10000）",
    )
    p_creator.add_argument(
        "--interval",
        type=float,
        default=2.0,
        help="翻页间隔秒数，默认 2；全量易 403 时可再加大",
    )
    p_creator.add_argument("--profile-only", action="store_true", help="只要资料")
    p_creator.add_argument(
        "--with-comments",
        action="store_true",
        help="爬取评论（挂在每条作品 comments 下，含二级回复）",
    )
    p_creator.add_argument(
        "--max-comments",
        type=int,
        default=0,
        help="每条作品最多评论数（一级+二级合计）；0=全量，默认 0",
    )
    p_creator.add_argument(
        "--checkpoint",
        default="",
        help="断点文件路径；默认 data/dy/checkpoints/{sec_uid}.json",
    )
    p_creator.add_argument(
        "--no-resume",
        action="store_true",
        help="不读取断点（仍会写入新断点）",
    )
    p_creator.add_argument(
        "--fresh",
        action="store_true",
        help="删除旧断点后重新爬",
    )
    p_creator.add_argument(
        "--refetch-posts",
        action="store_true",
        help="重拉作品列表（补封面等），按 aweme_id 合并保留已爬评论",
    )
    p_creator.add_argument(
        "--no-rotate-cookies",
        action="store_true",
        help="禁用 cookie 池自动轮换（只用 --account / 默认号）",
    )
    p_creator.add_argument(
        "--excel",
        action="store_true",
        help="额外导出 Excel：标题/标签/嵌入图片（视频用封面，图文用多图）",
    )
    p_creator.add_argument(
        "--excel-out",
        default="",
        help="Excel 路径；默认 data/dy/excel/{昵称}_{日期}.xlsx",
    )
    p_creator.add_argument(
        "--excel-max-images",
        type=int,
        default=0,
        help="每条作品最多导出几张图，0=全部（默认；一行一张图）",
    )
    p_creator.add_argument(
        "--excel-retries",
        type=int,
        default=3,
        help="单张图片下载失败重试次数，默认 3",
    )
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
        help="解析主页链接：无参数=当前账号；参数=抖音号/昵称搜索",
    )
    p_profile.add_argument(
        "target",
        nargs="?",
        default="",
        help="抖音号；省略则用 cookie 查自己",
    )
    _add_output_args(p_profile)
    p_profile.set_defaults(func=cmd_profile)

    p_accounts = sub.add_parser(
        "accounts",
        help="检测 cookies.json 账号；过期/无效的自动删除",
    )
    _add_output_args(p_accounts)
    p_accounts.set_defaults(func=cmd_accounts)

    p_im = sub.add_parser("im", help="私信：拉历史 / 轮询 / 发文本")
    p_im.add_argument(
        "mode",
        nargs="?",
        default="poll",
        choices=["dump", "poll", "send"],
        help="dump=拉会话历史；poll=轮询；send=发文本",
    )
    p_im.add_argument(
        "--conversation-id",
        default="",
        help="会话 ID；省略则 dump/poll 全部会话",
    )
    p_im.add_argument(
        "--all",
        action="store_true",
        help="dump/poll：监听/导出全部会话（未指定 --conversation-id 时默认开启）",
    )
    p_im.add_argument(
        "--conversation-short-id",
        type=int,
        default=0,
        help="会话 short_id（默认内置测试会话）",
    )
    p_im.add_argument("--limit", type=int, default=40, help="dump 拉取条数")
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
        "--nick",
        default="",
        help="按 cookies 账号昵称/抖音号/uid 选择，如 --nick 9277",
    )
    p_im.add_argument(
        "--text",
        default="",
        help="send：文本内容，如 --text '你好'",
    )
    p_im.add_argument(
        "--to",
        action="append",
        default=[],
        help="send：对方抖音号/昵称/主页URL/uid，可多个或逗号分隔；省略则回复当前会话",
    )
    p_im.add_argument(
        "--workers",
        type=int,
        default=0,
        help="send：并发数，默认 min(8, 目标数)；多个 --to 时生效",
    )
    p_im.add_argument(
        "--ticket",
        default="",
        help="send：会话 ticket（一般可省略，由 create 自动取）",
    )
    p_im.add_argument(
        "--headed",
        action="store_true",
        help="send：自动抓 ticket 时弹出浏览器（无头失败时用）",
    )
    p_im.add_argument(
        "--auto-reply",
        action="store_true",
        help="poll：对方来消息后自动回复（默认：你好 + 飞书链接）",
    )
    p_im.add_argument(
        "--reply-text",
        action="append",
        default=[],
        help="poll：自定义自动回复文本，可多次；配合 --auto-reply",
    )
    _add_output_args(p_im)
    p_im.set_defaults(func=cmd_im)

    args = parser.parse_args(argv)
    if hasattr(args, "out"):
        args.out = (args.out or "").strip() or None
    try:
        return args.func(args)
    except Exception as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
