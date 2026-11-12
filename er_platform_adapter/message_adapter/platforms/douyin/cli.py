"""Uniform Douyin private-message commands."""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

import click
from rich.console import Console
from rich.table import Table

from message_adapter.browser_profiles import BrowserProfile, legacy_profile_issues, migrate_legacy_browser_profile
from message_adapter.platforms.cli_support import (
    active_adapter_config,
    active_workspace_manager_lock,
    emit_json,
)
from message_adapter.storage import CredentialStore, inspect_actor_binding, migrate_legacy_state_database

from .browser_login import login_interactive, save_browser_login_result
from .credentials import load_douyin_cookie, load_im_cred
from .protocol import (
    account_summary,
    get_messages_by_conversation,
    im_uplink_content,
    list_conversations,
    load_auth,
    peer_uid_from_conversation,
    send_text,
    sort_messages,
)

console = Console()


@click.group()
@click.option("--dotenv", default=".env", show_default=True, type=click.Path(dir_okay=False))
@click.pass_context
def douyin(ctx: click.Context, dotenv: str) -> None:
    """管理抖音私信账号与消息。"""
    ctx.with_resource(active_workspace_manager_lock())
    config = active_adapter_config("douyin", dotenv)
    profile = BrowserProfile(config.browser_profile_root, "douyin")
    issues = legacy_profile_issues(profile)
    if issues:
        raise click.ClickException("; ".join(issues))
    migrate_legacy_state_database(config)
    migrate_legacy_browser_profile(profile)
    store = CredentialStore(config.credential_db)
    ctx.ensure_object(dict)
    ctx.obj.update(
        credential_store=store,
        config=config,
        browser_profile=profile,
    )
    ctx.call_on_close(store.close)


def _context(ctx: click.Context) -> CredentialStore:
    return (ctx.obj or {})["credential_store"]


def _profile(ctx: click.Context) -> BrowserProfile:
    return (ctx.obj or {})["browser_profile"]


def _auth(ctx: click.Context):
    store = _context(ctx)
    credential = load_douyin_cookie(store=store)
    send_credential = load_im_cred(store=store, sessionid=credential.sessionid)
    return load_auth(
        cookie=credential.cookie,
        account_name=credential.name,
        uid=credential.uid,
        send_credential=send_credential,
    )


def _find_conversation(auth, conversation_id: str) -> dict[str, Any]:
    for conversation in list_conversations(auth, page_size=50, max_pages=10):
        if str(conversation.get("conversation_id") or "") == conversation_id:
            return conversation
    raise click.ClickException(f"未找到抖音会话: {conversation_id}")


@douyin.command("login")
@click.pass_context
def login(ctx: click.Context) -> None:
    """扫码登录当前账号。"""
    store = _context(ctx)

    def show_status(message: str) -> None:
        console.print(f"[dim]{message}[/dim]")

    console.print("[bold]请在弹出的浏览器中使用抖音 APP 扫码[/bold]")
    try:
        profile = _profile(ctx)
        console.print("[dim]正在清理本机浏览器登录态[/dim]")
        profile.clear()
        result = asyncio.run(login_interactive(profile=profile, headless=False, on_status=show_status))
    except (RuntimeError, TimeoutError) as exc:
        raise click.ClickException(str(exc)) from exc
    if not result.uid:
        raise click.ClickException("抖音登录成功但未取得稳定 UID")
    bound_uid = inspect_actor_binding((ctx.obj or {})["config"].state_db, "douyin")
    if bound_uid and bound_uid != result.uid:
        raise click.ClickException(
            f"本机抖音槽位已绑定 platform_actor_id={bound_uid}；请先执行 adapter reset"
        )
    save_browser_login_result(
        result,
        store=store,
        browser_profile=str(profile.path),
    )
    console.print(
        f"[green]登录成功[/green]  platform=douyin  platform_actor_id={result.uid or '-'}"
    )


@douyin.command("logout")
@click.pass_context
def logout(ctx: click.Context) -> None:
    """清除当前账号凭证与 Chrome Profile。"""
    from message_adapter.services.accounts import logout_platform

    config = (ctx.obj or {})["config"]
    logout_platform("douyin", config)
    console.print("[green]已退出[/green]  platform=douyin")


@douyin.command("status")
@click.option("--json", "as_json", is_flag=True, help="输出统一 JSON")
@click.pass_context
def status(ctx: click.Context, as_json: bool) -> None:
    """检查当前账号是否可用于私信。"""
    store = _context(ctx)
    try:
        auth = _auth(ctx)
        summary = account_summary(auth)
        platform_actor_id = str(auth.uid or summary.get("uid") or "")
        bound_uid = inspect_actor_binding((ctx.obj or {})["config"].state_db, "douyin")
        if bound_uid and bound_uid != platform_actor_id:
            raise RuntimeError(
                f"本机抖音槽位已绑定 platform_actor_id={bound_uid}；请先执行 adapter reset"
            )
        store.bind_actor("douyin", platform_actor_id)
        list_conversations(auth, page_size=1, max_pages=1)
        send_credential = load_im_cred(store=store, sessionid=str(auth.cookie.get("sessionid") or ""))
        send_ready = all(
            send_credential.get(field)
            for field in ("DY_TICKET", "DY_TS_SIGN", "DY_CLIENT_CERT", "DY_PRIVATE_KEY")
        )
        data = {
            "authenticated": True,
            "platform_actor_id": platform_actor_id,
            "send_ready": send_ready,
            "reason": "" if send_ready else "send_credential_missing",
        }
    except Exception as exc:
        data = {
            "authenticated": False,
            "platform_actor_id": "",
            "send_ready": False,
            "reason": str(exc),
        }
    ready = bool(data["authenticated"] and data["send_ready"])
    if as_json:
        emit_json("douyin", data, ok=ready)
    else:
        state = "[green]ready[/green]" if ready else "[red]not ready[/red]"
        console.print(f"platform=douyin  status={state}")
        console.print(f"platform_actor_id={data['platform_actor_id'] or '-'}  send_ready={str(data['send_ready']).lower()}")
        if data["reason"]:
            console.print(f"reason={data['reason']}")
    if not ready:
        raise SystemExit(1)


@douyin.command("conversations")
@click.option("-n", "--limit", default=20, show_default=True, type=click.IntRange(1, 100))
@click.option("--json", "as_json", is_flag=True, help="输出统一 JSON")
@click.pass_context
def conversations(ctx: click.Context, limit: int, as_json: bool) -> None:
    """列出私信会话。"""
    auth = _auth(ctx)
    rows = []
    for raw in list_conversations(auth, page_size=min(limit, 100), max_pages=2)[:limit]:
        conversation_id = str(raw.get("conversation_id") or "")
        rows.append(
            {
                "conversation_id": conversation_id,
                "audience_id": peer_uid_from_conversation(conversation_id, auth.uid),
                "audience_name": "",
                "audience_avatar": "",
            }
        )
    if as_json:
        emit_json("douyin", rows)
        return
    table = Table("conversation_id", "audience_id", "audience_name")
    for row in rows:
        table.add_row(row["conversation_id"], row["audience_id"], row["audience_name"] or "-")
    console.print(table)


@douyin.command("messages")
@click.argument("conversation_id")
@click.option("-n", "--limit", default=30, show_default=True, type=click.IntRange(1, 100))
@click.option("--json", "as_json", is_flag=True, help="输出统一 JSON")
@click.pass_context
def messages(ctx: click.Context, conversation_id: str, limit: int, as_json: bool) -> None:
    """查看指定 conversation_id 的最近消息。"""
    auth = _auth(ctx)
    conversation = _find_conversation(auth, conversation_id)
    short_id = int(conversation.get("conversation_short_id") or 0)
    raw_messages = get_messages_by_conversation(auth, conversation_id, short_id, limit=limit)
    rows = []
    for raw in sort_messages(raw_messages):
        uplink = im_uplink_content(raw)
        if uplink is None:
            continue
        rows.append(
            {
                "message_id": str(raw.get("server_message_id") or raw.get("index_in_conversation") or ""),
                "sent_at_ms": int(raw.get("create_time_ms") or 0),
                "direction": "outgoing" if str(raw.get("sender") or "") == auth.uid else "incoming",
                "content_type": int(uplink["content_type"]),
                "text": str(uplink["text"]),
                "content": uplink["content"],
            }
        )
    if as_json:
        emit_json("douyin", {"conversation_id": conversation_id, "messages": rows})
        return
    table = Table("time", "direction", "text")
    for row in rows:
        stamp = datetime.fromtimestamp(row["sent_at_ms"] / 1000).strftime("%Y-%m-%d %H:%M:%S") if row["sent_at_ms"] else "-"
        table.add_row(stamp, row["direction"], row["text"])
    console.print(table)


@douyin.command("send")
@click.argument("conversation_id")
@click.argument("text")
@click.option("--json", "as_json", is_flag=True, help="输出统一 JSON")
@click.pass_context
def send(ctx: click.Context, conversation_id: str, text: str, as_json: bool) -> None:
    """向指定 conversation_id 发送文本消息。"""
    auth = _auth(ctx)
    conversation = _find_conversation(auth, conversation_id)
    result = send_text(
        auth,
        text,
        conversation_id=conversation_id,
        conversation_short_id=int(conversation.get("conversation_short_id") or 0),
        conversation_ticket=str(conversation.get("conversation_ticket") or ""),
        to_user_id=peer_uid_from_conversation(conversation_id, auth.uid),
    )
    data = {
        "sent": bool(result.get("ok")),
        "conversation_id": conversation_id,
        "audience_id": peer_uid_from_conversation(conversation_id, auth.uid),
        "platform_message_id": str(result.get("server_message_id") or result.get("client_message_id") or ""),
    }
    if as_json:
        emit_json("douyin", data, ok=data["sent"])
    elif data["sent"]:
        console.print(f"[green]发送成功[/green]  platform=douyin  conversation_id={conversation_id}")
    else:
        raise click.ClickException(str(result.get("error_desc") or result.get("message") or "抖音发送失败"))
