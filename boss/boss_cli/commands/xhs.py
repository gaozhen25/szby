"""Xiaohongshu (小红书) private-message commands."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from boss_cli.constants import XHS_COOKIE_FILE
from boss_cli.xhs.client import XhsClient
from boss_cli.xhs.credentials import (
    list_xhs_accounts,
    load_xhs_cookie,
    set_active_xhs_account,
)
from boss_cli.xhs.im import (
    account_summary,
    dump_all_conversations,
    format_message_line,
    list_chats,
    resolve_chat_target,
    resolve_client_by_nick,
    run_poll_loop,
    send_text,
)

console = Console()
logger = logging.getLogger(__name__)


@click.group()
@click.option("--account", "account_name", default="", help="指定账号名称（xhs/cookies.json）")
@click.pass_context
def xhs(ctx: click.Context, account_name: str) -> None:
    """小红书私信 — 扫码登录、收件箱、发消息、实时监听。"""
    ctx.ensure_object(dict)
    ctx.obj["account_name"] = account_name.strip()


def _account_name(ctx: click.Context) -> str:
    return str((ctx.obj or {}).get("account_name") or "")


def _client(ctx: click.Context, nick: str = "") -> tuple[XhsClient, dict]:
    if nick.strip():
        return resolve_client_by_nick(nick.strip())
    cred = load_xhs_cookie(account_name=_account_name(ctx))
    client = XhsClient(cookie=cred.cookie, account_name=cred.name)
    try:
        summary = account_summary(client)
    except Exception:
        summary = {
            "nickname": cred.nickname,
            "user_id": cred.user_id,
            "red_id": cred.red_id,
        }
    return client, summary


@xhs.command("accounts")
def xhs_accounts() -> None:
    """列出已保存的小红书账号。"""
    rows = list_xhs_accounts()
    if not rows:
        console.print("[yellow]暂无已保存账号[/yellow]")
        console.print("[dim]先执行: boss xhs login[/dim]")
        return
    table = Table(show_header=True, header_style="bold")
    table.add_column("当前", width=4)
    table.add_column("名称")
    table.add_column("昵称")
    table.add_column("user_id", overflow="fold")
    table.add_column("cookie")
    for row in rows:
        table.add_row(
            "●" if row.get("active") else "",
            str(row.get("name") or "-"),
            str(row.get("nickname") or "-"),
            str(row.get("user_id") or "-"),
            "[green]有效[/green]" if row.get("valid") else "[yellow]无效[/yellow]",
        )
    console.print(table)
    console.print(f"[dim]存储: {XHS_COOKIE_FILE}[/dim]")
    console.print("[dim]切换账号: boss xhs use 账号名[/dim]")


@xhs.command("use")
@click.argument("name")
def xhs_use(name: str) -> None:
    """切换当前使用的小红书账号。"""
    try:
        set_active_xhs_account(name)
    except KeyError as exc:
        raise click.ClickException(str(exc)) from exc
    console.print(f"[green]当前账号[/green] {name}")


@xhs.command("status")
@click.pass_context
def xhs_status(ctx: click.Context) -> None:
    """检查小红书 cookie 是否可用。"""
    try:
        client, summary = _client(ctx)
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc
    console.print("[green]cookie 可用[/green]")
    console.print(f"  昵称: {summary.get('nickname') or '-'}")
    console.print(f"  user_id: {summary.get('user_id') or '-'}")
    console.print(f"  小红书号: {summary.get('red_id') or '-'}")


@xhs.command("login")
@click.option("--name", "account_name", default="", help="账号备注名（默认用扫码后昵称）")
@click.option("--timeout", default=180, type=int, show_default=True, help="等待扫码秒数")
@click.pass_context
def xhs_login(ctx: click.Context, account_name: str, timeout: int) -> None:
    """Playwright 有界面扫码登录，写入 xhs/cookies.json。"""
    from boss_cli.xhs.login_qr import login_qr

    name = (account_name or _account_name(ctx)).strip()
    try:
        result = login_qr(account_name=name, timeout=float(timeout))
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc
    console.print(
        f"[green]已登录[/green] {result.get('name')} "
        f"nickname={result.get('nickname')!r} user_id={result.get('user_id')}"
    )


@xhs.group("im")
def xhs_im() -> None:
    """私信：dump / poll / listen / send。"""


@xhs_im.command("dump")
@click.option("--nick", default="", help="按昵称/小红书号匹配已存账号")
@click.option("--chat-limit", default=100, type=int, show_default=True)
@click.option("--page-size", default=30, type=int, show_default=True)
@click.option("-o", "--out", "out_path", default="", help="输出目录或单个 .json")
@click.option("-q", "--quiet", is_flag=True, help="少打印消息正文")
@click.pass_context
def xhs_im_dump(
    ctx: click.Context,
    nick: str,
    chat_limit: int,
    page_size: int,
    out_path: str,
    quiet: bool,
) -> None:
    """拉取会话列表 + 历史消息。"""
    client, summary = _client(ctx, nick=nick)
    console.print(
        f"[dim]account nickname={summary.get('nickname')!r} "
        f"user_id={summary.get('user_id')}[/dim]"
    )
    data = dump_all_conversations(client, chat_limit=chat_limit, page_size=page_size)
    convs = list(data.get("conversations") or [])
    me_nick = str((data.get("account") or {}).get("nickname") or "im")
    out_arg = Path(out_path) if out_path else None
    written: list[Path] = []
    if out_arg and out_arg.suffix.lower() == ".json" and len(convs) == 1:
        out_arg.parent.mkdir(parents=True, exist_ok=True)
        out_arg.write_text(json.dumps(convs[0], ensure_ascii=False, indent=2), encoding="utf-8")
        written.append(out_arg)
    else:
        base = out_arg if out_arg else Path("data") / "xhs" / "im" / me_nick
        if base.suffix.lower() == ".json":
            base = base.parent / base.stem
        base.mkdir(parents=True, exist_ok=True)
        from boss_cli.xhs.im import conversation_filename

        for conv in convs:
            name = conversation_filename(
                str(conv.get("peer") or ""),
                str(conv.get("chat_user_id") or ""),
            )
            path = base / name
            path.write_text(json.dumps(conv, ensure_ascii=False, indent=2), encoding="utf-8")
            written.append(path)
    for path in written:
        console.print(f"[green]已写入[/green] {path}")
    if not quiet:
        for conv in convs:
            console.print(f"\n# {conv.get('peer')} ({conv.get('message_count')} 条)")
            for m in conv.get("messages") or []:
                console.print(format_message_line(conv.get("peer") or "", m))


@xhs_im.command("chats")
@click.option("--nick", default="", help="按昵称/小红书号匹配已存账号")
@click.option("--limit", default=50, type=int, show_default=True)
@click.pass_context
def xhs_im_chats(ctx: click.Context, nick: str, limit: int) -> None:
    """只列会话（不拉完整历史）。"""
    client, _ = _client(ctx, nick=nick)
    chats = (list_chats(client, limit=limit).get("chats") or [])
    table = Table(show_header=True, header_style="bold")
    table.add_column("#", width=4)
    table.add_column("昵称")
    table.add_column("chat_user_id", overflow="fold")
    for i, ch in enumerate(chats, 1):
        info = ch.get("info") or {}
        table.add_row(
            str(i),
            str(info.get("nickname") or info.get("user_name") or "-"),
            str(ch.get("chat_user_id") or ""),
        )
    console.print(table)


@xhs_im.command("send")
@click.option("--to", "to_raw", required=True, help="对方昵称或 chat_user_id")
@click.option("--text", required=True, help="发送文本")
@click.option("--nick", default="", help="按昵称/小红书号匹配已存账号")
@click.option("--chat-limit", default=100, type=int, show_default=True)
@click.option("--headed", is_flag=True, help="WS/HTTP 失败时用浏览器 UI 兜底")
@click.pass_context
def xhs_im_send(
    ctx: click.Context,
    to_raw: str,
    text: str,
    nick: str,
    chat_limit: int,
    headed: bool,
) -> None:
    """发送文本私信（优先 WebSocket）。"""
    client, summary = _client(ctx, nick=nick)
    console.print(
        f"[dim]account nickname={summary.get('nickname')!r} "
        f"user_id={summary.get('user_id')}[/dim]"
    )
    chat_user_id, peer_name = resolve_chat_target(client, to_raw, chat_limit=chat_limit)
    result = send_text(
        client,
        chat_user_id,
        text,
        headed=headed,
        peer_name=peer_name,
    )
    payload = {
        "ok": bool(result),
        "to": {"chat_user_id": chat_user_id, "peer": peer_name},
        "text": text,
        "result": result,
    }
    console.print_json(data=payload)
    if not result:
        raise click.ClickException("发送失败")


@xhs_im.command("poll")
@click.option("--nick", default="", help="按昵称/小红书号匹配已存账号")
@click.option("--interval", "poll_interval", default=3.0, type=float, show_default=True)
@click.option("--seconds", default=0, type=int, show_default=True, help="0=一直听")
@click.option("--chat-limit", default=100, type=int, show_default=True)
@click.pass_context
def xhs_im_poll(
    ctx: click.Context,
    nick: str,
    poll_interval: float,
    seconds: int,
    chat_limit: int,
) -> None:
    """HTTP 轮询新私信。"""
    client, summary = _client(ctx, nick=nick)
    console.print(
        f"[dim]poll interval={poll_interval}s "
        f"seconds={'forever' if seconds <= 0 else seconds} "
        f"account={summary.get('nickname')!r}[/dim]"
    )
    try:
        run_poll_loop(
            client,
            interval=poll_interval,
            seconds=seconds,
            chat_limit=chat_limit,
        )
    except KeyboardInterrupt:
        console.print("[dim]已停止[/dim]")


@xhs_im.command("listen")
@click.option("--nick", default="", help="按昵称/小红书号匹配已存账号")
@click.option("--seconds", default=0, type=int, show_default=True, help="0=一直听")
@click.pass_context
def xhs_im_listen(ctx: click.Context, nick: str, seconds: int) -> None:
    """WebSocket 实时接收私信。"""
    from boss_cli.xhs.im_ws import receive_messages_ws

    client, summary = _client(ctx, nick=nick)
    my_uid = str(summary.get("user_id") or "")
    if not my_uid:
        raise click.ClickException("无法获取当前账号 user_id，请重新 boss xhs login")
    console.print(
        f"[cyan]WS 实时接收[/cyan][dim] 监听 {seconds or '无限'} 秒，Ctrl+C 退出…[/dim]"
    )
    try:
        for msg in receive_messages_ws(client.cookie, my_uid, seconds=seconds):
            who = msg.get("nickname") or msg.get("sender") or "?"
            direction = "我→对方" if msg.get("outgoing") else "对方→我"
            console.print(
                f"[im][{msg.get('time') or '?'}] {direction} "
                f"来自:{who} store:{msg.get('store_id')} "
                f"msg_id:{str(msg.get('message_id') or '')[:32]} "
                f"text:{msg.get('text') or ''}"
            )
    except KeyboardInterrupt:
        console.print("[dim]已停止[/dim]")


@xhs.command("web")
@click.option("--host", default="127.0.0.1", show_default=True)
@click.option("--port", default=8767, type=int, show_default=True)
@click.option("--no-open", is_flag=True, help="不自动打开浏览器")
@click.option("--nick", default="", help="按昵称/小红书号匹配已存账号")
@click.option(
    "--auto-reply/--no-auto-reply",
    default=True,
    show_default=True,
    help="对方新私信自动回复并引导换平台联系",
)
@click.pass_context
def xhs_web(
    ctx: click.Context,
    host: str,
    port: int,
    no_open: bool,
    nick: str,
    auto_reply: bool,
) -> None:
    """打开本机网页版小红书私信（对齐 spider/js web_im）。"""
    import webbrowser

    from boss_cli.xhs.credentials import load_xhs_cookie
    from boss_cli.xhs_web import serve_xhs_web

    account = _account_name(ctx)
    if not nick.strip():
        # 提前校验 cookie，失败时给出清晰提示
        load_xhs_cookie(account_name=account)

    if host not in {"127.0.0.1", "localhost", "::1"}:
        console.print("[yellow]监听非本机地址会把 cookie 暴露到局域网。[/yellow]")
        if not click.confirm("仍然继续?"):
            return

    url = f"http://{host}:{port}/"
    console.print(f"[green]小红书私信网页版启动中[/green]  {url}")
    if account:
        console.print(f"[dim]账号参数: {account}[/dim]")
    if nick.strip():
        console.print(f"[dim]按昵称匹配: {nick.strip()}[/dim]")
    if auto_reply:
        console.print(
            "[cyan]自动回复已开启[/cyan][dim]：对方首条消息回复问候，再回一条后发送联系方式；"
            "每会话只自动发两遍。关闭: --no-auto-reply[/dim]"
        )
    if not no_open:
        # 稍晚再开浏览器，避免服务尚未 bind
        def _open() -> None:
            import time

            time.sleep(0.8)
            try:
                webbrowser.open(url)
            except Exception:
                logger.debug("open browser failed", exc_info=True)

        import threading

        threading.Thread(target=_open, daemon=True).start()

    try:
        serve_xhs_web(
            host=host,
            port=port,
            account_name=account,
            nick=nick,
            auto_reply=auto_reply,
        )
    except KeyboardInterrupt:
        console.print("\n[dim]已关闭[/dim]")
