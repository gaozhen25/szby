"""Uniform BOSS private-message commands."""

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

from .auth import get_credential, save_credential, verify_credential_details
from .browser import login_with_profile
from .client import BossClient
from .mapping import history_message

console = Console()


@click.group()
@click.option("--dotenv", default=".env", show_default=True, type=click.Path(dir_okay=False))
@click.pass_context
def boss(ctx: click.Context, dotenv: str) -> None:
    """管理 BOSS 私信账号与消息。"""
    ctx.with_resource(active_workspace_manager_lock())
    config = active_adapter_config("boss", dotenv)
    profile = BrowserProfile(config.browser_profile_root, "boss")
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


def _credential(ctx: click.Context):
    store = _context(ctx)
    credential = get_credential(store=store)
    if credential is None:
        raise click.ClickException("BOSS 未登录，请先执行 adapter boss login")
    return credential


def _friends(client: BossClient, *, limit: int) -> list[dict[str, Any]]:
    listed = client.get_boss_friend_list().get("result") or []
    friend_ids = [int(item["friendId"]) for item in listed if item.get("friendId")]
    details = client.get_boss_friend_details(friend_ids[:limit]).get("friendList") or listed[:limit]
    return [dict(item) for item in details[:limit]]


def _conversation(friend: dict[str, Any]) -> dict[str, str]:
    return {
        "conversation_id": str(friend.get("friendId") or ""),
        "audience_id": str(friend.get("uid") or friend.get("friendId") or ""),
        "audience_name": str(friend.get("name") or friend.get("geekName") or ""),
        "audience_avatar": str(friend.get("avatar") or friend.get("tinyUrl") or ""),
    }


def _find_friend(client: BossClient, conversation_id: str) -> dict[str, Any]:
    try:
        friend_id = int(conversation_id)
    except ValueError as exc:
        raise click.ClickException("conversation_id 必须是 BOSS friend ID") from exc
    details = client.get_boss_friend_details([friend_id]).get("friendList") or []
    if not details:
        raise click.ClickException(f"未找到 BOSS 会话: {conversation_id}")
    return dict(details[0])


@boss.command("login")
@click.pass_context
def login(ctx: click.Context) -> None:
    """扫码登录当前账号。"""
    store = _context(ctx)
    console.print("[bold]请在弹出的 Google Chrome 中使用 BOSS 直聘 APP 扫码[/bold]")
    try:
        credential = asyncio.run(login_with_profile(_profile(ctx)))
    except (RuntimeError, TimeoutError) as exc:
        raise click.ClickException(str(exc)) from exc
    health = verify_credential_details(credential, force_refresh=True)
    if not health["authenticated"]:
        raise click.ClickException(str(health.get("reason") or "BOSS 登录校验失败"))
    with BossClient(credential) as client:
        info = client.get_user_info()
    platform_actor_id = str(info.get("userId") or info.get("uid") or "").strip()
    if not platform_actor_id:
        raise click.ClickException("BOSS 登录成功但用户信息未返回稳定 UID")
    bound_uid = inspect_actor_binding((ctx.obj or {})["config"].state_db, "boss")
    if bound_uid and bound_uid != platform_actor_id:
        raise click.ClickException(
            f"本机 BOSS 槽位已绑定 platform_actor_id={bound_uid}；请先执行 adapter reset"
        )
    save_credential(credential, store=store, platform_actor_id=platform_actor_id)
    console.print(f"[green]登录成功[/green]  platform=boss  platform_actor_id={platform_actor_id}")


@boss.command("logout")
@click.pass_context
def logout(ctx: click.Context) -> None:
    """清除当前账号凭证与 Chrome Profile。"""
    from message_adapter.services.accounts import logout_platform

    config = (ctx.obj or {})["config"]
    logout_platform("boss", config)
    console.print("[green]已退出[/green]  platform=boss")


@boss.command("status")
@click.option("--json", "as_json", is_flag=True, help="输出统一 JSON")
@click.pass_context
def status(ctx: click.Context, as_json: bool) -> None:
    """检查当前账号是否可用于私信。"""
    store = _context(ctx)
    credential = get_credential(store=store)
    if credential is None:
        data = {"authenticated": False, "platform_actor_id": "", "send_ready": False, "reason": "credential_missing"}
    else:
        health = verify_credential_details(credential)
        data = {
            "authenticated": bool(health["authenticated"]),
            "platform_actor_id": "",
            "send_ready": bool(health["authenticated"]),
            "reason": str(health.get("reason") or ""),
        }
        if data["authenticated"]:
            with BossClient(credential) as client:
                info = client.get_user_info()
            data["platform_actor_id"] = str(info.get("userId") or info.get("uid") or "")
            bound_uid = inspect_actor_binding((ctx.obj or {})["config"].state_db, "boss")
            if bound_uid and bound_uid != data["platform_actor_id"]:
                raise click.ClickException(
                    f"本机 BOSS 槽位已绑定 platform_actor_id={bound_uid}；请先执行 adapter reset"
                )
            store.bind_actor("boss", data["platform_actor_id"])
    if as_json:
        emit_json("boss", data, ok=bool(data["authenticated"]))
    else:
        state = "[green]ready[/green]" if data["authenticated"] else "[red]not ready[/red]"
        console.print(f"platform=boss  status={state}")
        console.print(f"platform_actor_id={data['platform_actor_id'] or '-'}  send_ready={str(data['send_ready']).lower()}")
        if data["reason"]:
            console.print(f"reason={data['reason']}")
    if not data["authenticated"]:
        raise SystemExit(1)


@boss.command("conversations")
@click.option("-n", "--limit", default=20, show_default=True, type=click.IntRange(1, 100))
@click.option("--json", "as_json", is_flag=True, help="输出统一 JSON")
@click.pass_context
def conversations(ctx: click.Context, limit: int, as_json: bool) -> None:
    """列出私信会话。"""
    with BossClient(_credential(ctx)) as client:
        rows = [_conversation(friend) for friend in _friends(client, limit=limit)]
    if as_json:
        emit_json("boss", rows)
        return
    table = Table("conversation_id", "audience_id", "audience_name")
    for row in rows:
        table.add_row(row["conversation_id"], row["audience_id"], row["audience_name"] or "-")
    console.print(table)


@boss.command("messages")
@click.argument("conversation_id")
@click.option("-n", "--limit", default=30, show_default=True, type=click.IntRange(1, 100))
@click.option("--json", "as_json", is_flag=True, help="输出统一 JSON")
@click.pass_context
def messages(ctx: click.Context, conversation_id: str, limit: int, as_json: bool) -> None:
    """查看指定 conversation_id 的最近消息。"""
    with BossClient(_credential(ctx)) as client:
        friend = _find_friend(client, conversation_id)
        info = client.get_user_info()
        raw_messages = client.get_boss_chat_history(int(conversation_id), count=limit)
    my_uid = int(info.get("userId") or info.get("uid") or 0)
    peer_uid = int(friend.get("uid") or friend.get("friendId") or 0)
    rows = []
    for raw in raw_messages.get("messages") or raw_messages.get("messageList") or []:
        mapped = history_message(raw, my_uid=my_uid, peer_uid=peer_uid)
        if mapped["kind"] != "text":
            continue
        rows.append(
            {
                "message_id": str(mapped["mid"] or ""),
                "sent_at_ms": int(mapped["ts"] or 0),
                "direction": "outgoing" if mapped["mine"] else "incoming",
                "text": str(mapped["text"] or ""),
            }
        )
    rows.sort(key=lambda item: item["sent_at_ms"])
    if as_json:
        emit_json("boss", {"conversation_id": conversation_id, "messages": rows})
        return
    table = Table("time", "direction", "text")
    for row in rows:
        stamp = datetime.fromtimestamp(row["sent_at_ms"] / 1000).strftime("%Y-%m-%d %H:%M:%S") if row["sent_at_ms"] else "-"
        table.add_row(stamp, row["direction"], row["text"])
    console.print(table)


@boss.command("send")
@click.argument("conversation_id")
@click.argument("text")
@click.option("--json", "as_json", is_flag=True, help="输出统一 JSON")
@click.pass_context
def send(ctx: click.Context, conversation_id: str, text: str, as_json: bool) -> None:
    """向指定 conversation_id 发送文本消息。"""
    with BossClient(_credential(ctx)) as client:
        friend = _find_friend(client, conversation_id)
        audience_id = int(friend.get("uid") or 0)
        encrypted_id = str(friend.get("encryptGeekId") or friend.get("encryptUid") or "")
        if not audience_id or not encrypted_id:
            raise click.ClickException("该会话缺少稳定 audience_id 或 encryptGeekId")
        result = client.send_boss_message(audience_id, encrypted_id, text)
    data = {
        "sent": bool(result.get("ok")),
        "conversation_id": conversation_id,
        "audience_id": str(audience_id),
        "platform_message_id": str(result.get("mid") or ""),
    }
    if as_json:
        emit_json("boss", data, ok=data["sent"])
    elif data["sent"]:
        console.print(f"[green]发送成功[/green]  platform=boss  conversation_id={conversation_id}")
    else:
        raise click.ClickException(str(result.get("message") or "BOSS 发送失败"))
