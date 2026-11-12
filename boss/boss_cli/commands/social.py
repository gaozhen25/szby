"""Social commands: chat, messages, reply, greet, batch-greet."""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

import click
from rich.table import Table

from ..index_cache import find_chat, find_chat_by_uid, load_chat_items, save_chat_index
from ..client import resolve_city
from ..constants import DEGREE_CODES, EXP_CODES, SALARY_CODES
from ..exceptions import BossApiError
from ._common import (
    console,
    handle_command,
    require_auth,
    run_client_action,
    structured_output_options,
)

logger = logging.getLogger(__name__)


def _conversation_json(friend: dict, index: int) -> dict:
    last = friend.get("lastMessageInfo") or {}
    return {
        "index": index,
        "name": friend.get("name") or friend.get("bossName") or "",
        "title": friend.get("title") or "",
        "company": friend.get("brandName") or friend.get("companyName") or "",
        "job": friend.get("jobName") or "",
        "lastMessage": friend.get("lastMsg") or last.get("showText") or friend.get("lastText") or "",
        "lastTime": friend.get("lastTime") or "",
        "unread": friend.get("unreadMsgCount") or 0,
        "encryptBossId": (
            friend.get("encryptBossId")
            or friend.get("encryptFriendId")
            or friend.get("encryptUid")
            or ""
        ),
        "encryptJobId": friend.get("encryptJobId") or "",
        "securityId": friend.get("securityId") or "",
        "uid": friend.get("uid") or friend.get("friendId"),
    }


def _friend_from_list(friend: dict, index: int) -> dict:
    return {
        "index": index,
        "name": friend.get("name") or friend.get("bossName") or "",
        "company": friend.get("brandName") or friend.get("companyName") or "",
        "job": friend.get("jobName") or "",
        "encryptBossId": (
            friend.get("encryptBossId")
            or friend.get("encryptFriendId")
            or friend.get("encryptUid")
            or ""
        ),
        "securityId": friend.get("securityId") or "",
        "uid": friend.get("uid") or friend.get("friendId"),
    }


def _resolve_conversation(cred, target: str) -> dict:
    """Resolve chat index / uid / encryptBossId to cached conversation metadata."""
    found = find_chat(target)
    if found and found.get("encryptBossId") and found.get("uid"):
        return found

    data = run_client_action(cred, lambda c: c.get_friend_list())
    friends = data.get("result") or data.get("friendList") or data.get("list") or []
    save_chat_index(friends)
    found = find_chat(target)
    if found:
        return found
    for i, friend in enumerate(friends, 1):
        row = _friend_from_list(friend, i)
        if target == row["encryptBossId"] or (target.isdigit() and str(row.get("uid") or "") == target):
            return row
    console.print("[yellow]没有找到该会话。请先运行 uv run boss chat[/yellow]")
    raise SystemExit(1)


@click.command("chat")
@click.option("-o", "--output", "output_path", default=None, help="将完整结果写入 JSON 文件，例如 -o chats.json")
@structured_output_options
def chat_list(as_json: bool, as_yaml: bool, output_path: str | None) -> None:
    """查看沟通过的 Boss 列表"""
    cred = require_auth()

    def _friends(data: dict) -> list:
        return data.get("result") or data.get("friendList") or data.get("list") or []

    def _payload(data: dict) -> dict:
        friends = _friends(data)
        conversations = [_conversation_json(friend, i) for i, friend in enumerate(friends, 1)]
        return {
            "ok": True,
            "schema_version": "1",
            "count": len(conversations),
            "conversations": conversations,
        }

    def _render(data: dict) -> None:
        friend_list = _friends(data)

        if not friend_list:
            if not data:
                console.print(
                    "[yellow]沟通列表接口返回空数据。[/yellow]\n"
                    "请重新扫码登录：[bold]uv run boss login[/bold]"
                )
            else:
                console.print("[yellow]暂无沟通记录[/yellow]")
            return

        table = Table(title=f"💬 沟通列表 ({len(friend_list)} 个)", show_lines=True, expand=True)
        table.add_column("#", style="dim", width=3)
        table.add_column("Boss", style="bold cyan", overflow="fold")
        table.add_column("公司", style="green", overflow="fold")
        table.add_column("职位", overflow="fold")
        table.add_column("最近消息", style="dim", overflow="fold")

        for i, friend in enumerate(friend_list, 1):
            row = _conversation_json(friend, i)
            table.add_row(
                str(i),
                row["name"],
                row["company"],
                row["job"] or row["title"] or "-",
                row["lastMessage"],
            )

        console.print(table)
        console.print("[dim]完整列表: uv run boss chat --json  或  -o chats.json[/dim]")
        console.print("[dim]查看记录: uv run boss messages <序号>   例如 boss messages 1 --json[/dim]")
        console.print('[dim]发送私信: uv run boss reply <序号> "正文"   例如 boss reply 1 "您好"[/dim]')
        console.print("[dim]持续接听: uv run boss listen[/dim]")

    def _cache_and_render(data: dict) -> None:
        save_chat_index(_friends(data))
        _render(data)

    if as_json or as_yaml or output_path:
        try:
            data = run_client_action(cred, lambda c: c.get_friend_list())
        except BossApiError as exc:
            from ._common import _print_error
            _print_error(exc, as_json=as_json, as_yaml=as_yaml)
            raise SystemExit(1) from None
        payload = _payload(data)
        save_chat_index(_friends(data))
        if as_yaml and not as_json:
            try:
                import yaml
                text = yaml.dump(payload, allow_unicode=True, default_flow_style=False)
            except ImportError:
                text = json.dumps(payload, indent=2, ensure_ascii=False)
        else:
            text = json.dumps(payload, indent=2, ensure_ascii=False)
        if output_path:
            path = Path(output_path)
            path.write_text(text, encoding="utf-8")
            console.print(f"[green]已写入[/green] {path.resolve()}")
        if as_json or as_yaml or not output_path:
            click.echo(text)
        return

    handle_command(cred, action=lambda c: c.get_friend_list(), render=_cache_and_render, as_json=False, as_yaml=False)


@click.command("messages")
@click.argument("target")
@click.option("-n", "--count", default=20, type=int, help="消息条数，默认 20")
@click.option("--all", "fetch_all", is_flag=True, help="自动翻页拉取该会话全部记录")
@click.option("--max-msg-id", default="0", help="翻页游标，传上一页最小 mid")
@click.option("-o", "--output", "output_path", default=None, help="写入 JSON 文件")
@structured_output_options
def chat_messages(
    target: str,
    count: int,
    fetch_all: bool,
    max_msg_id: str,
    output_path: str | None,
    as_json: bool,
    as_yaml: bool,
) -> None:
    """查看与某个 Boss 的完整聊天记录。

    TARGET 可以是 boss chat 列表里的序号（如 1），或 encryptBossId。
    """
    cred = require_auth()
    meta = _resolve_conversation(cred, target)
    boss_id = str(meta.get("encryptBossId") or "")
    if not boss_id:
        console.print("[red]该会话缺少 encryptBossId，无法拉聊天记录[/red]")
        raise SystemExit(1)

    def _action(c):
        if fetch_all:
            history = c.get_geek_chat_history_all(
                boss_id=boss_id, page_size=max(count, 20), start_msg_id=max_msg_id,
            )
        else:
            history = c.get_geek_chat_history(boss_id=boss_id, max_msg_id=max_msg_id, count=count)
        return {"boss": meta, "bossId": boss_id, **history}

    def _render(data: dict) -> None:
        messages = data.get("messages") or []
        title = meta.get("name") or boss_id
        if not messages:
            console.print(f"[yellow]暂无聊天记录[/yellow] ({title})")
            return
        table = Table(title=f"与 {title} 的聊天记录 ({len(messages)} 条)", show_lines=True, expand=True)
        table.add_column("#", style="dim", width=3)
        table.add_column("方向", width=6)
        table.add_column("发送者", overflow="fold")
        table.add_column("内容", overflow="fold")
        for i, msg in enumerate(messages, 1):
            received = msg.get("received")
            direction = "对方" if received else "我"
            text = msg.get("text") or ""
            job = msg.get("job") or {}
            if not text and job.get("title"):
                text = f"[职位] {job.get('title')} {job.get('salary') or ''}"
            table.add_row(str(i), direction, msg.get("fromName") or "-", text or "[非文本消息]")
        console.print(table)
        if data.get("hasMore") and messages and not fetch_all:
            mids = [m.get("mid") for m in messages if m.get("mid") is not None]
            nxt = min(mids) if mids else 0
            console.print(f"[dim]更多: uv run boss messages {target} --all[/dim]")
            console.print(f"[dim]或: uv run boss messages {target} --max-msg-id {nxt} -n {count}[/dim]")
        elif data.get("hasMore"):
            console.print("[yellow]已达翻页上限，可能还有更早的记录[/yellow]")
        console.print(f'[dim]回复: uv run boss reply {target} "正文"[/dim]')

    if as_json or output_path:
        try:
            data = run_client_action(cred, _action)
        except BossApiError as exc:
            from ._common import _print_error
            _print_error(exc, as_json=True, as_yaml=False)
            raise SystemExit(1) from None
        text = json.dumps({"ok": True, "schema_version": "1", **data}, indent=2, ensure_ascii=False)
        if output_path:
            path = Path(output_path)
            path.write_text(text, encoding="utf-8")
            console.print(f"[green]已写入[/green] {path.resolve()}")
        if as_json or not output_path:
            click.echo(text)
        return

    handle_command(cred, action=_action, render=_render, as_json=as_json, as_yaml=as_yaml)


@click.command()
@click.argument("security_id")
@click.option("--lid", default="", help="Lid parameter from search results")
@structured_output_options
def greet(security_id: str, lid: str, as_json: bool, as_yaml: bool) -> None:
    """向 Boss 打招呼 / 投递简历 (需要 securityId)"""
    cred = require_auth()

    def _action(c):
        return c.add_friend(security_id=security_id, lid=lid)

    def _render(data: dict) -> None:
        console.print("[green]✅ 打招呼成功！[/green]")
        if data:
            click.echo(json.dumps(data, indent=2, ensure_ascii=False))

    handle_command(cred, action=_action, render=_render, as_json=as_json, as_yaml=as_yaml)


@click.command("batch-greet")
@click.argument("keyword")
@click.option("-c", "--city", default="全国", help="城市名称或代码")
@click.option("-n", "--count", default=5, type=int, help="打招呼数量 (默认: 5)")
@click.option("--salary", type=click.Choice(list(SALARY_CODES.keys())), help="薪资筛选")
@click.option("--exp", type=click.Choice(list(EXP_CODES.keys())), help="工作经验筛选")
@click.option("--degree", type=click.Choice(list(DEGREE_CODES.keys())), help="学历筛选")
@click.option("--dry-run", is_flag=True, help="仅预览，不实际发送")
@click.option("-y", "--yes", is_flag=True, help="跳过确认提示")
def batch_greet(keyword: str, city: str, count: int, salary: str | None, exp: str | None, degree: str | None, dry_run: bool, yes: bool) -> None:
    """批量向搜索结果中的 Boss 打招呼

    例: boss batch-greet "golang" --city 杭州 -n 10 --salary 20-30K
    """
    cred = require_auth()

    city_code = resolve_city(city)
    salary_code = SALARY_CODES.get(salary) if salary else None
    exp_code = EXP_CODES.get(exp) if exp else None
    degree_code = DEGREE_CODES.get(degree) if degree else None

    try:
        data = run_client_action(
            cred,
            lambda client: client.search_jobs(
                query=keyword,
                city=city_code,
                experience=exp_code,
                degree=degree_code,
                salary=salary_code,
            ),
        )

        job_list = data.get("jobList", [])
        if not job_list:
            console.print("[yellow]没有找到匹配的职位[/yellow]")
            return

        targets = job_list[:count]

        # Preview table
        table = Table(title=f"🎯 将向以下 {len(targets)} 个职位打招呼", show_lines=True)
        table.add_column("#", style="dim", width=3)
        table.add_column("职位", style="bold cyan", max_width=25)
        table.add_column("公司", style="green", max_width=20)
        table.add_column("薪资", style="yellow", max_width=12)

        for i, job in enumerate(targets, 1):
            table.add_row(str(i), job.get("jobName", "-"), job.get("brandName", "-"), job.get("salaryDesc", "-"))

        console.print(table)

        if dry_run:
            console.print("\n  [dim]📋 预览模式，未实际发送[/dim]")
            return

        if not yes:
            confirm = click.confirm(f"\n确定向 {len(targets)} 个职位打招呼吗?")
            if not confirm:
                console.print("[dim]已取消[/dim]")
                return

        # Send greetings with auth auto-refresh on every request.
        success = 0
        for i, job in enumerate(targets, 1):
            security_id = job.get("securityId", "")
            lid = job.get("lid", "")
            job_name = job.get("jobName", "?")
            brand = job.get("brandName", "?")

            if not security_id:
                console.print(f"  [{i}] [yellow]跳过 {job_name} (无 securityId)[/yellow]")
                continue

            try:
                run_client_action(
                    cred,
                    lambda client, security_id=security_id, lid=lid: client.add_friend(
                        security_id=security_id,
                        lid=lid,
                    ),
                )
                console.print(f"  [{i}] [green]✅ {job_name} @ {brand}[/green]")
                success += 1
            except BossApiError as e:
                console.print(f"  [{i}] [red]❌ {job_name}: {e}[/red]")

            # Explicit rate-limit delay between greetings to avoid detection
            if i < len(targets):
                time.sleep(1.5)

        console.print(f"\n[bold]完成: {success}/{len(targets)} 个打招呼成功[/bold]")

    except BossApiError as exc:
        console.print(f"[red]❌ 搜索失败: {exc}[/red]")
        raise SystemExit(1) from None


@click.command("reply")
@click.argument("target")
@click.argument("message")
@click.option("-y", "--yes", is_flag=True, help="跳过确认提示")
def chat_reply(target: str, message: str, yes: bool) -> None:
    """向已沟通过的 Boss 发送私信。

    TARGET 可以是 boss chat 列表里的序号（如 1），或 encryptBossId。

    例: boss reply 1 "您好，我对这个职位很感兴趣"
    """
    cred = require_auth()
    text = message.strip()
    if not text:
        console.print("[red]消息内容不能为空[/red]")
        raise SystemExit(1)

    meta = _resolve_conversation(cred, target)
    to_uid = meta.get("uid")
    to_enc = str(meta.get("encryptBossId") or "")
    name = meta.get("name") or to_enc or str(to_uid)
    if not to_uid:
        console.print("[red]该会话缺少 uid，无法发送。请先运行 uv run boss chat[/red]")
        raise SystemExit(1)

    if not yes:
        console.print(f"[cyan]将向 {name} 发送:[/cyan]")
        console.print(f"  {text}")
        if not click.confirm("\n确认发送?"):
            console.print("[dim]已取消[/dim]")
            return

    console.print("[dim]正在通过 MQTT 发送...[/dim]")
    try:
        run_client_action(
            cred,
            lambda c: c.send_geek_message(to_uid=int(to_uid), to_encrypt_uid=to_enc, text=text),
        )
    except BossApiError as exc:
        console.print(f"[red]发送失败: {exc}[/red]")
        raise SystemExit(1) from None
    except Exception as exc:
        console.print(f"[red]发送失败: {exc}[/red]")
        raise SystemExit(1) from None

    console.print(f"[green]已发送给 {name}[/green]")
    console.print("[dim]可用 uv run boss messages 查看是否出现在记录里[/dim]")


def _listen_time(ts: int) -> str:
    from datetime import datetime

    if ts and ts > 10_000_000_000:
        ts = int(ts / 1000)
    try:
        when = datetime.fromtimestamp(ts) if ts else datetime.now()
    except (OSError, OverflowError, ValueError):
        when = datetime.now()
    return when.strftime("%H:%M:%S")


def _listen_peer(msg: dict, my_uid: int | None) -> tuple[str, str, int]:
    from_obj = msg.get("from") or {}
    from_uid = int(from_obj.get("uid") or 0)
    from_name = str(from_obj.get("name") or "")
    if my_uid and from_uid == my_uid:
        return "我", from_name or "我", from_uid
    cached = find_chat_by_uid(from_uid) if from_uid else None
    name = from_name or (cached or {}).get("name") or (str(from_uid) if from_uid else "Boss")
    return "对方", name, from_uid


def _refresh_chat_index(cred) -> None:
    data = run_client_action(cred, lambda c: c.get_friend_list())
    friends = data.get("result") or data.get("friendList") or data.get("list") or []
    save_chat_index(friends)


@click.command("listen")
@click.option("-t", "--timeout", "duration", default=0, type=int, help="监听秒数，0 表示直到 Ctrl+C")
@click.option("--poll", "poll_seconds", default=0, type=int, help="额外按秒轮询沟通列表，0 关闭")
@click.option("--all", "show_all", is_flag=True, help="也显示自己发出的消息")
@click.option("--backlog", is_flag=True, help="也显示连上时补推的历史消息")
@click.option("--json-lines", is_flag=True, help="每条消息输出一行 JSON")
def chat_listen(duration: int, poll_seconds: int, show_all: bool, backlog: bool, json_lines: bool) -> None:
    """持续接听 Boss 发来的私信（MQTT）。按 Ctrl+C 结束。"""
    from ..mqtt_chat import IDENTITY_GEEK, run_mqtt_listen

    cred = require_auth()
    console.print("[dim]正在获取认证并连接 MQTT...[/dim]")
    try:
        if not load_chat_items():
            _refresh_chat_index(cred)
        page_token, wt2, user_info, cookies = run_client_action(
            cred,
            lambda c: (*c.get_ws_auth(), c.session_cookies()),
        )
    except BossApiError as exc:
        console.print(f"[red]连接失败: {exc}[/red]")
        raise SystemExit(1) from None

    my_uid = user_info.get("userId")
    seen_poll: dict[str, str] = {}

    def _emit(payload: dict) -> None:
        if json_lines:
            click.echo(json.dumps(payload, ensure_ascii=False))
            return
        direction = payload.get("direction") or "对方"
        name = payload.get("name") or ""
        text = payload.get("text") or ""
        stamp = payload.get("time") or _listen_time(0)
        style = "green" if direction == "对方" else "blue"
        console.print(f"[dim]{stamp}[/dim] [{style}]{direction}[/{style}] {name}: {text}")

    def _poll_once() -> None:
        try:
            data = run_client_action(cred, lambda c: c.get_friend_list())
        except BossApiError as exc:
            logger.debug("listen poll failed: %s", exc)
            return
        friends = data.get("result") or data.get("friendList") or data.get("list") or []
        save_chat_index(friends)
        first = not seen_poll
        for i, friend in enumerate(friends, 1):
            row = _conversation_json(friend, i)
            key = str(row.get("uid") or row.get("encryptBossId") or i)
            last_msg = str(row.get("lastMessage") or "")
            if first:
                seen_poll[key] = last_msg
                continue
            if last_msg and seen_poll.get(key) != last_msg:
                _emit({
                    "time": _listen_time(0),
                    "direction": "对方",
                    "name": row.get("name") or key,
                    "uid": row.get("uid"),
                    "mid": None,
                    "text": last_msg,
                    "source": "poll",
                })
            seen_poll[key] = last_msg

    console.print("[green]已连接，正在接听私信。[/green] [dim]Ctrl+C 结束[/dim]")
    if poll_seconds > 0:
        console.print(f"[dim]额外每 {poll_seconds}s 轮询沟通列表[/dim]")

    def _reconnect():
        token, secret, info, jar = run_client_action(
            cred,
            lambda c: (*c.get_ws_auth(), c.session_cookies()),
        )
        return token, secret, jar, info.get("userId") or my_uid

    try:
        run_mqtt_listen(
            page_token=page_token,
            wt2=wt2,
            cookies=cookies,
            my_uid=my_uid,
            identity=IDENTITY_GEEK,
            duration=duration,
            poll_seconds=poll_seconds,
            show_all=show_all,
            backlog=backlog,
            on_message=_emit,
            lookup_peer=lambda uid: (find_chat_by_uid(uid) or {}).get("name") or None,
            refresh_peers=lambda: _refresh_chat_index(cred),
            poll_once=_poll_once if poll_seconds > 0 else None,
            on_status=lambda msg: console.print(f"[yellow]{msg}[/yellow]" if "中断" in msg else f"[dim]{msg}[/dim]"),
            on_reconnect=_reconnect,
        )
    except KeyboardInterrupt:
        console.print("\n[dim]已停止接听[/dim]")
