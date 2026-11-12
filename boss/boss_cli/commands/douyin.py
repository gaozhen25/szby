"""Douyin (抖音) private-message commands."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from ..douyin.credentials import (
    extract_browser_douyin_cookie,
    import_im_cred_from_spider,
    im_cred_status,
    list_douyin_accounts,
    load_douyin_cookie,
    save_douyin_cookie,
    save_im_cred,
    set_active_douyin_account,
)
from boss_cli.constants import DOUYIN_COOKIE_FILE, DOUYIN_IM_CRED_FILE
from ..douyin.im import (
    account_summary,
    dump_conversation,
    format_im_message,
    get_messages_by_conversation,
    list_conversations,
    load_auth,
    send_text,
    sort_messages,
)

console = Console()
logger = logging.getLogger(__name__)


@click.group()
def douyin() -> None:
    """抖音私信 — 收件箱、消息、网页版沟通。"""


@click.group()
@click.option("--account", "account_name", default="", help="指定账号名称（cookies.json / im_cred.json）")
@click.pass_context
def douyin(ctx: click.Context, account_name: str) -> None:
    """抖音私信 — 收件箱、消息、网页版沟通。"""
    ctx.ensure_object(dict)
    ctx.obj["account_name"] = account_name.strip()


def _account_name(ctx: click.Context) -> str:
    return str((ctx.obj or {}).get("account_name") or "")


@douyin.command("accounts")
@click.pass_context
def douyin_accounts(ctx: click.Context) -> None:
    """列出已保存的抖音账号（cookie + ticket 状态）。"""
    rows = list_douyin_accounts()
    if not rows:
        console.print("[yellow]暂无已保存账号[/yellow]")
        console.print("[dim]先执行: boss douyin login（浏览器扫码）[/dim]")
        return
    table = Table(show_header=True, header_style="bold")
    table.add_column("当前", width=4)
    table.add_column("名称")
    table.add_column("sessionid", overflow="fold")
    table.add_column("发信凭据")
    for row in rows:
        table.add_row(
            "●" if row.get("active") else "",
            str(row.get("name") or "-"),
            str(row.get("sessionid") or "-")[:16] + "…" if row.get("sessionid") else "-",
            "[green]就绪[/green]" if row.get("send_ready") else "[yellow]缺失[/yellow]",
        )
    console.print(table)
    console.print("[dim]切换账号: boss douyin use 账号名[/dim]")


@douyin.command("use")
@click.argument("name")
@click.pass_context
def douyin_use(ctx: click.Context, name: str) -> None:
    """切换当前使用的抖音账号。"""
    try:
        set_active_douyin_account(name)
    except KeyError as exc:
        raise click.ClickException(str(exc)) from exc
    console.print(f"[green]当前账号[/green] {name}")


@douyin.command("status")
@click.pass_context
def douyin_status(ctx: click.Context) -> None:
    """检查抖音 cookie 是否可用。"""
    account = _account_name(ctx)
    try:
        cred = load_douyin_cookie(account_name=account)
        auth = load_auth(cookie=cred.cookie)
        me = account_summary(auth)
        im_ok = False
        try:
            im_ok = bool(list_conversations(auth, page_size=3, max_pages=1))
        except Exception:
            im_ok = False
        console.print(f"[green]已加载[/green] cookie 账号: {cred.name}")
        if cred.source:
            console.print(f"  来源: {cred.source}")
        else:
            console.print(f"  配置: {DOUYIN_COOKIE_FILE}")
        nick = me.get("nickname") or ""
        uid = me.get("uid") or ""
        unique_id = me.get("unique_id") or ""
        if nick:
            console.print(f"  昵称: {nick}")
        elif uid:
            console.print(f"  昵称: [dim](profile 接口被风控，暂无法拉取)[/dim]")
        else:
            console.print("  昵称: -")
        console.print(f"  uid: {uid or '-'}")
        console.print(f"  抖音号: {unique_id or '-'}")
        if im_ok:
            console.print("[green]私信 IM 可用[/green]")
        elif uid:
            console.print("[yellow]uid 已解析，但私信列表拉取失败，请检查 cookie[/yellow]")
        else:
            console.print("[yellow]未能解析账号信息；若私信不可用请重新 login[/yellow]")
        cred_flags = im_cred_status(account_name=cred.name)
        if all(cred_flags.values()):
            console.print("[green]发信凭据已就绪[/green]")
        else:
            missing = [k for k, ok in cred_flags.items() if not ok]
            console.print(f"[yellow]发信凭据缺失: {', '.join(missing)}[/yellow]")
            console.print("[dim]可执行: boss douyin grab-ticket --qr  或  boss douyin login[/dim]")
        others = [r for r in list_douyin_accounts() if not r.get("active")]
        if others:
            console.print(f"[dim]另有 {len(others)} 个账号，执行 boss douyin accounts 查看[/dim]")
    except Exception as exc:
        console.print(f"[red]未就绪[/red]: {exc}")


def _run_browser_qr_login(*, account_name: str = "", headless: bool = False) -> None:
    import asyncio

    from ..douyin.browser_login import login_interactive, save_browser_login_result

    def on_status(msg: str) -> None:
        console.print(f"[dim]{msg}[/dim]")

    if headless:
        raise click.ClickException("扫码登录需要有界面，请去掉 --headless")

    console.print("[bold]请在弹出的浏览器中用抖音 APP 扫码登录[/bold]")
    console.print(
        "[dim]与 spider ``dy_im_grab_ticket.py --qr`` 相同："
        "同一次扫码追加 cookie + ticket（不覆盖其它账号）[/dim]"
    )
    try:
        result = asyncio.run(
            login_interactive(
                headless=False,
                account_name=account_name,
                on_status=on_status,
            )
        )
    except RuntimeError as exc:
        raise click.ClickException(str(exc)) from exc
    except TimeoutError as exc:
        raise click.ClickException(str(exc)) from exc

    save_browser_login_result(result)
    console.print(f"[green]已追加账号[/green] {result.account_name}")
    if result.nickname:
        console.print(f"  昵称: {result.nickname}")
    if result.uid:
        console.print(f"  uid: {result.uid}")
    console.print(f"  cookie → {DOUYIN_COOKIE_FILE}")
    console.print(f"  ticket → {DOUYIN_IM_CRED_FILE}")
    console.print("[dim]切换账号: boss douyin use 账号名[/dim]")


def _run_cookie_source_login(cookie_source: str, *, account_name: str = "") -> None:
    cookie, errors = extract_browser_douyin_cookie(cookie_source)
    if not cookie:
        console.print("[red]提取失败[/red]")
        for line in errors:
            console.print(f"  [dim]{line}[/dim]")
        console.print("[dim]推荐改用扫码: boss douyin login[/dim]")
        raise SystemExit(1)
    resolved = account_name.strip()
    try:
        auth = load_auth(cookie=cookie)
        me = account_summary(auth)
        if not resolved:
            resolved = str(me.get("nickname") or me.get("unique_id") or cookie_source)
    except Exception:
        if not resolved:
            resolved = cookie_source
    save_douyin_cookie(
        cookie,
        name=resolved,
        source=f"browser:{cookie_source}",
        append=True,
        set_active=True,
    )
    console.print(f"[green]已追加保存[/green] {DOUYIN_COOKIE_FILE}  账号: {resolved}")
    console.print("[dim]抓发信 ticket: boss douyin grab-ticket --qr[/dim]")


@douyin.command("login")
@click.option(
    "--cookie-source",
    default=None,
    help="从本地浏览器读 cookie（chrome/edge/brave/firefox/chromium/safari）；默认改为浏览器扫码",
)
@click.option("--name", default="", help="账号名称；默认用抖音昵称")
@click.option("--headless", is_flag=True, help="无界面（默认有界面浏览器扫码）")
@click.pass_context
def douyin_login(ctx: click.Context, cookie_source: str | None, name: str, headless: bool) -> None:
    """有界面浏览器扫码登录，追加保存 cookie + ticket。"""
    if cookie_source:
        _run_cookie_source_login(cookie_source, account_name=name)
        return
    _run_browser_qr_login(account_name=name, headless=headless)


@douyin.command("set-cookie")
@click.argument("cookie", required=False)
@click.option("--file", "cookie_file", type=click.Path(exists=True, dir_okay=False), help="从文件读取 cookie")
@click.option("--name", default="default", show_default=True, help="账号名称标记")
@click.pass_context
def douyin_set_cookie(ctx: click.Context, cookie: str | None, cookie_file: str | None, name: str) -> None:
    """手动写入 boss 抖音 cookie 配置（追加，不覆盖其它账号）。"""
    text = (cookie or "").strip()
    if cookie_file:
        text = Path(cookie_file).read_text(encoding="utf-8").strip()
    if not text:
        if click.get_text_stream("stdin").isatty():
            raise click.ClickException("请提供 cookie 字符串，或使用 --file")
        text = click.get_text_stream("stdin").read().strip()
    if "sessionid=" not in text:
        console.print("[yellow]警告: cookie 中未见 sessionid，收信可能失败[/yellow]")
    path = save_douyin_cookie(text, name=name, source="manual", append=True, set_active=True)
    console.print(f"[green]已追加写入[/green] {path}  账号: {name}")


@douyin.command("grab-ticket")
@click.option("--qr", is_flag=True, help="扫码登录，同时追加 cookie + ticket（推荐，对齐 spider --qr）")
@click.option("--headed", is_flag=True, help="cookie 模式有界面（仅注入已有 cookie 时）")
@click.option("--name", default="", help="账号名称；--qr 时默认用抖音昵称")
@click.option("--timeout", default=0, type=int, help="超时秒数（默认 qr=180 / cookie=90）")
@click.option("--no-sync-cookie", is_flag=True, help="--qr 时不写回 cookies.json（不推荐）")
@click.pass_context
def douyin_grab_ticket(
    ctx: click.Context,
    qr: bool,
    headed: bool,
    name: str,
    timeout: int,
    no_sync_cookie: bool,
) -> None:
    """抓取发信 ticket；推荐 --qr 同一次扫码追加 cookie + ticket。"""
    import asyncio

    from ..douyin.grab_ticket import grab, grab_with_qr, save_qr_grab_result

    if qr:
        console.print("[bold]扫码模式：同一次登录追加 cookie + ticket[/bold]")
        console.print("[dim]对齐 spider/js: python scripts/dy_im_grab_ticket.py --qr[/dim]")
        try:
            cred = asyncio.run(grab_with_qr(timeout_s=timeout or 180))
            account, sid = save_qr_grab_result(
                cred,
                account_name=name or _account_name(ctx),
                sync_cookie=not no_sync_cookie,
            )
        except Exception as exc:
            raise click.ClickException(str(exc)) from exc
        console.print(f"[green]已追加[/green] 账号={account} sessionid={sid[:8]}…")
        console.print(f"  cookie → {DOUYIN_COOKIE_FILE}")
        console.print(f"  ticket → {DOUYIN_IM_CRED_FILE}")
        return

    account = name or _account_name(ctx)
    cred = load_douyin_cookie(account_name=account)
    console.print(f"[dim]账号 {cred.name}：注入 cookie 抓取 web_protect（常失败，建议 --qr）…[/dim]")
    payload = asyncio.run(grab(cred.cookie, headless=not headed, timeout_s=timeout or 90))
    save_im_cred(payload, account_name=cred.name, sessionid=cred.sessionid, append=True)
    console.print(f"[green]已追加发信凭据[/green] {DOUYIN_IM_CRED_FILE}  账号: {cred.name}")


@douyin.command("add-account")
@click.option(
    "--cookie-source",
    default=None,
    help="从本地浏览器读 cookie；默认改为有界面浏览器扫码登录",
)
@click.option("--name", default="", help="账号名称；默认用抖音昵称")
@click.option("--headless", is_flag=True, help="无界面（默认有界面浏览器扫码）")
def douyin_add_account(cookie_source: str | None, name: str, headless: bool) -> None:
    """添加新抖音号：浏览器扫码登录，追加 cookie + ticket。"""
    if cookie_source:
        _run_cookie_source_login(cookie_source, account_name=name)
        import asyncio

        from ..douyin.grab_ticket import grab

        cred = load_douyin_cookie()
        console.print("[dim]正在抓取发信 ticket…[/dim]")
        payload = asyncio.run(grab(cred.cookie, headless=not headless))
        save_im_cred(payload, account_name=cred.name, sessionid=cred.sessionid, append=True)
        console.print(f"[green]ticket 已追加[/green] {DOUYIN_IM_CRED_FILE}")
        console.print("[dim]切换账号: boss douyin use 账号名[/dim]")
        return
    _run_browser_qr_login(account_name=name, headless=headless)


@douyin.command("import-cred")
@click.option(
    "--from",
    "source",
    type=click.Path(exists=True, dir_okay=False),
    default=None,
    help="源凭据文件，默认 ~/spider/js/cookies/dy_im_cred.json",
)
@click.pass_context
def douyin_import_cred(ctx: click.Context, source: str | None) -> None:
    """从 spider/js 复制发信凭据到 boss 配置目录（追加到当前账号）。"""
    account = _account_name(ctx)
    try:
        active = load_douyin_cookie(account_name=account)
        path = import_im_cred_from_spider(source=Path(source) if source else None, account_name=active.name)
    except (FileNotFoundError, RuntimeError) as exc:
        raise click.ClickException(str(exc)) from exc
    flags = im_cred_status(account_name=active.name)
    console.print(f"[green]已导入[/green] {path}  账号: {active.name}")
    console.print(
        "  "
        + "  ".join(f"{k}={'✓' if flags.get(k) else '✗'}" for k in flags),
    )


@douyin.command("inbox")
@click.option("-n", "--limit", default=20, show_default=True, help="显示会话数量")
@click.pass_context
def douyin_inbox(ctx: click.Context, limit: int) -> None:
    """列出私信会话。"""
    auth = load_auth(account_name=_account_name(ctx))
    convs = list_conversations(auth, page_size=min(max(limit, 1), 100), max_pages=2)
    if not convs:
        console.print("[yellow]暂无会话[/yellow]")
        return
    table = Table(show_header=True, header_style="bold")
    table.add_column("#", style="dim", width=4)
    table.add_column("conversation_id", overflow="fold")
    table.add_column("short_id", overflow="fold")
    for i, conv in enumerate(convs[:limit], 1):
        table.add_row(
            str(i),
            str(conv.get("conversation_id") or ""),
            str(conv.get("conversation_short_id") or ""),
        )
    console.print(table)


@douyin.command("messages")
@click.argument("index", type=int)
@click.option("-n", "--limit", default=30, show_default=True, help="消息条数")
@click.pass_context
def douyin_messages(ctx: click.Context, index: int, limit: int) -> None:
    """查看第 N 个会话的最近消息（inbox 序号，从 1 开始）。"""
    auth = load_auth(account_name=_account_name(ctx))
    convs = list_conversations(auth, page_size=50, max_pages=2)
    if index < 1 or index > len(convs):
        raise click.ClickException(f"无效序号 {index}，当前共 {len(convs)} 个会话")
    conv = convs[index - 1]
    cid = str(conv.get("conversation_id") or "")
    cshort = int(conv.get("conversation_short_id") or 0)
    msgs = get_messages_by_conversation(auth, cid, cshort, limit=max(5, min(limit, 50)))
    for msg in sort_messages(msgs):
        console.print(format_im_message(auth, msg))


@douyin.command("send")
@click.option("--to", "to_user_id", required=True, help="对方 uid（纯数字，直发不触发搜索限流）")
@click.argument("text")
@click.option("--headed", is_flag=True, help="缺 ticket 时用有界面浏览器自动抓取")
@click.pass_context
def douyin_send(
    ctx: click.Context, to_user_id: str, text: str, headed: bool
) -> None:
    """按 uid 直接发送（不经过昵称搜索，避免触发抖音搜索限流 2484）。"""
    to_user_id = (to_user_id or "").strip()
    if not to_user_id.isdigit():
        raise click.ClickException(
            "--to 必须是纯数字 uid（可用 boss douyin inbox 查看对方 uid）"
        )
    auth = load_auth(account_name=_account_name(ctx))
    from ..douyin.im import ensure_send_cred

    ensure_send_cred(auth, headed=headed)
    result = send_text(auth, text, to_user_id=to_user_id)
    if result.get("ok", True):
        console.print("[green]已发送[/green]")
    else:
        raise click.ClickException(
            str(result.get("error_desc") or result.get("message") or "发送失败")
        )


@douyin.command("reply")
@click.argument("index", type=int)
@click.argument("text")
@click.option("--headed", is_flag=True, help="缺 ticket 时用有界面浏览器自动抓取")
@click.pass_context
def douyin_reply(ctx: click.Context, index: int, text: str, headed: bool) -> None:
    """向第 N 个会话发送文本消息。"""
    auth = load_auth(account_name=_account_name(ctx))
    convs = list_conversations(auth, page_size=50, max_pages=2)
    if index < 1 or index > len(convs):
        raise click.ClickException(f"无效序号 {index}，当前共 {len(convs)} 个会话")
    conv = convs[index - 1]
    cid = str(conv.get("conversation_id") or "")
    cshort = int(conv.get("conversation_short_id") or 0)
    from ..douyin.im import ensure_send_cred

    ensure_send_cred(auth, headed=headed)
    result = send_text(auth, text, conversation_id=cid, conversation_short_id=cshort)
    if result.get("ok", True):
        console.print("[green]已发送[/green]")
    else:
        raise click.ClickException(str(result.get("error_desc") or result.get("message") or "发送失败"))


@douyin.command("dump")
@click.argument("index", type=int)
@click.option("-n", "--limit", default=40, show_default=True)
@click.option("-o", "--output", default="", help="输出 JSON 文件")
@click.pass_context
def douyin_dump(ctx: click.Context, index: int, limit: int, output: str) -> None:
    """导出单个会话为 JSON。"""
    auth = load_auth(account_name=_account_name(ctx))
    convs = list_conversations(auth, page_size=50, max_pages=2)
    if index < 1 or index > len(convs):
        raise click.ClickException(f"无效序号 {index}")
    conv = convs[index - 1]
    cid = str(conv.get("conversation_id") or "")
    cshort = int(conv.get("conversation_short_id") or 0)
    payload = dump_conversation(auth, cid, cshort, limit=limit)
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    if output:
        from pathlib import Path

        Path(output).write_text(text, encoding="utf-8")
        console.print(f"[green]已写入[/green] {output}")
    else:
        console.print(text)


@douyin.command("web")
@click.option("--host", default="127.0.0.1", show_default=True)
@click.option("--port", default=8766, type=int, show_default=True)
@click.option("--no-open", is_flag=True, help="不自动打开浏览器")
@click.option(
    "--auto-reply/--no-auto-reply",
    default=True,
    show_default=True,
    help="对方新私信自动回复并引导换平台联系",
)
@click.pass_context
def douyin_web(
    ctx: click.Context,
    host: str,
    port: int,
    no_open: bool,
    auto_reply: bool,
) -> None:
    """打开本机网页版抖音私信（对齐 BOSS 沟通 UI）。"""
    import webbrowser

    cred = load_douyin_cookie(account_name=_account_name(ctx))
    if host not in {"127.0.0.1", "localhost", "::1"}:
        console.print("[yellow]监听非本机地址会把 cookie 暴露到局域网。[/yellow]")
        if not click.confirm("仍然继续?"):
            return

    from ..douyin_web import serve_douyin_web

    server = serve_douyin_web(cred, host, port, auto_reply=auto_reply)
    url = f"http://{host}:{port}/"
    console.print(f"[green]抖音私信网页版已启动[/green]  {url}")
    console.print(f"[dim]当前账号: {cred.name}[/dim]")
    if getattr(cred, "uid", ""):
        console.print(f"[dim]uid: {cred.uid}[/dim]")
    else:
        console.print(
            "[yellow]警告: 本地未缓存 uid，发信/实时收信可能异常。"
            "请执行: boss douyin grab-ticket --qr[/yellow]"
        )
    console.print("[dim]收信 frontier-im WebSocket 推送；发信需 im_cred.json（boss douyin grab-ticket --qr）。[/dim]")
    if auto_reply:
        from ..douyin.im import _send_cred_missing, load_auth

        auth = load_auth(
            cookie=cred.cookie,
            account_name=cred.name,
            uid=str(getattr(cred, "uid", "") or ""),
        )
        missing = _send_cred_missing(auth)
        if missing:
            console.print(
                f"[yellow]警告: 自动回复需要发信凭据，缺少 {', '.join(missing)}。"
                "请先执行 boss douyin grab-ticket --qr[/yellow]"
            )
        console.print(
            "[cyan]自动回复已开启[/cyan][dim]：对方首条消息回复问候，再回一条后发送联系方式；"
            "每会话只自动发两遍。关闭: --no-auto-reply[/dim]"
        )
    if not no_open:
        try:
            webbrowser.open(url)
        except Exception:
            logger.debug("open browser failed", exc_info=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        console.print("\n[dim]已关闭[/dim]")
    finally:
        app = getattr(server, "web_app", None)
        if app is not None:
            app.stop()
        server.shutdown()
        server.server_close()
