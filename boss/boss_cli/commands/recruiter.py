"""Recruiter (Boss) commands — Click subcommand group with 20 commands."""

from __future__ import annotations

import csv
import html
import io
import json
import logging
import re
import time
from pathlib import Path

import click
from rich.panel import Panel
from rich.table import Table

from ..client import BossClient, resolve_city
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


@click.group()
def recruiter() -> None:
    """招聘方/雇主端操作 (Recruiter mode)"""


# ── recruiter jobs ──────────────────────────────────────────────────


@recruiter.command("jobs")
@structured_output_options
def recruiter_jobs(as_json: bool, as_yaml: bool) -> None:
    """查看招聘中的职位列表"""
    cred = require_auth()

    def _render(data: list[dict]) -> None:
        if not data:
            console.print("[yellow]暂无在线职位[/yellow]")
            return

        table = Table(title=f"招聘职位 ({len(data)} 个)", show_lines=True)
        table.add_column("#", style="dim", width=3)
        table.add_column("职位", style="bold cyan", max_width=25)
        table.add_column("薪资", style="yellow", max_width=12)
        table.add_column("地区", style="blue", max_width=15)
        table.add_column("encJobId", style="dim", max_width=30)

        for i, job in enumerate(data, 1):
            table.add_row(
                str(i),
                job.get("jobName", "-"),
                job.get("salaryDesc", "-"),
                job.get("address", "-"),
                job.get("encryptJobId", "-"),
            )

        console.print(table)
        console.print("  [dim]使用 boss recruiter inbox --job <encJobId> 查看该职位的候选人[/dim]")

    handle_command(
        cred, action=lambda c: c.get_boss_chatted_jobs(),
        render=_render, as_json=as_json, as_yaml=as_yaml,
    )


# ── recruiter search ──────────────────────────────────────────────


@recruiter.command("search")
@click.argument("keyword")
@click.option("-c", "--city", default="上海", help="城市名称或代码 (默认: 上海)")
@click.option("--exp", type=click.Choice(list(EXP_CODES.keys())), help="工作经验筛选")
@click.option("--degree", type=click.Choice(list(DEGREE_CODES.keys())), help="学历筛选")
@click.option("--salary", type=click.Choice(list(SALARY_CODES.keys())), help="薪资筛选")
@click.option("--job", "encrypt_job_id", default="", help="关联职位 encryptJobId")
@click.option("-p", "--page", default=1, type=int, help="页码")
@structured_output_options
def recruiter_search(
    keyword: str, city: str, exp: str | None, degree: str | None,
    salary: str | None, encrypt_job_id: str, page: int,
    as_json: bool, as_yaml: bool,
) -> None:
    """搜索候选人 (Search candidates)"""
    cred = require_auth()
    city_code = resolve_city(city)
    exp_code = EXP_CODES.get(exp) if exp else None
    degree_code = DEGREE_CODES.get(degree) if degree else None
    salary_code = SALARY_CODES.get(salary) if salary else None

    def _action(c: BossClient) -> dict:
        return c.search_geeks(
            query=keyword, city=city_code, page=page,
            experience=exp_code, degree=degree_code,
            salary=salary_code, encrypt_job_id=encrypt_job_id,
        )

    def _render(data: dict) -> None:
        geek_list = data.get("geekList", data.get("resultList", []))
        if not geek_list:
            console.print("[yellow]未找到匹配候选人 (可能需要 __zp_stoken__)[/yellow]")
            if data:
                console.print(f"  [dim]返回数据: {json.dumps(data, ensure_ascii=False)[:200]}[/dim]")
            return

        table = Table(title=f"搜索候选人: {keyword} ({len(geek_list)} 人)", show_lines=True)
        table.add_column("#", style="dim", width=3)
        table.add_column("姓名", style="bold cyan", max_width=10)
        table.add_column("职位", style="green", max_width=20)
        table.add_column("经验", style="yellow", max_width=8)
        table.add_column("学历", max_width=6)
        table.add_column("encryptGeekId", style="dim", max_width=28)

        for i, geek in enumerate(geek_list, 1):
            table.add_row(
                str(i),
                geek.get("name", geek.get("geekName", "-")),
                geek.get("expectPositionName", geek.get("jobName", "-")),
                geek.get("workYearDesc", geek.get("workYear", "-")),
                geek.get("degreeDesc", geek.get("degree", "-")),
                geek.get("encryptGeekId", geek.get("encryptUid", "-")),
            )

        console.print(table)

    handle_command(cred, action=_action, render=_render, as_json=as_json, as_yaml=as_yaml)


# ── recruiter recommend ──────────────────────────────────────────


@recruiter.command("recommend")
@click.option("-n", "--limit", "display_limit", default=0, type=int, help="显示数量 (0=全部)")
@click.option("-p", "--page", default=1, type=int, help="页码 (默认: 1)")
@click.option("--job", "enc_job_id", default="", help="关联职位 encryptJobId (切换岗位)")
@structured_output_options
def recruiter_recommend(
    display_limit: int, page: int, enc_job_id: str,
    as_json: bool, as_yaml: bool,
) -> None:
    """推荐候选人列表 (支持 --job 切换岗位, -p 翻页)"""
    cred = require_auth()

    def _action(c: BossClient) -> dict:
        return c.get_boss_recommend_geeks(page=page, enc_job_id=enc_job_id)

    def _render(data: dict) -> None:
        friend_list = data.get("friendList", [])
        total = len(friend_list)

        if not friend_list:
            console.print("[yellow]暂无推荐候选人[/yellow]")
            return

        if display_limit > 0:
            friend_list = friend_list[:display_limit]

        table = Table(
            title=f"推荐候选人 (显示 {len(friend_list)}/{total} 人)",
            show_lines=True,
        )
        table.add_column("#", style="dim", width=3)
        table.add_column("姓名", style="bold cyan", max_width=10)
        table.add_column("职位", style="green", max_width=20)
        table.add_column("encJobId", style="dim", max_width=28)
        table.add_column("新牛人", max_width=4)
        table.add_column("时间", style="dim", max_width=10)

        for i, f in enumerate(friend_list, 1):
            new_flag = "NEW" if f.get("newGeek") else ""
            table.add_row(
                str(i),
                f.get("name", "-"),
                f.get("jobName", "-"),
                f.get("encryptJobId", "-"),
                new_flag,
                f.get("lastTime", "-"),
            )

        console.print(table)

        console.print("  [dim]💡 切换岗位: boss recruiter recommend --job <encryptJobId>[/dim]")
        console.print("  [dim]   限制显示: boss recruiter recommend -n 10[/dim]")
        console.print("  [dim]   查看职位: boss recruiter jobs[/dim]")

    handle_command(cred, action=_action, render=_render, as_json=as_json, as_yaml=as_yaml)


# ── recruiter greet ──────────────────────────────────────────────


@recruiter.command("greet")
@click.argument("encrypt_geek_id")
@click.option("--job", "encrypt_job_id", default="", help="关联职位 encryptJobId")
@structured_output_options
def recruiter_greet(encrypt_geek_id: str, encrypt_job_id: str, as_json: bool, as_yaml: bool) -> None:
    """向候选人发起沟通 (Initiate conversation with candidate)"""
    cred = require_auth()

    def _action(c: BossClient) -> dict:
        # Get job id if not provided
        job_id = encrypt_job_id
        if not job_id:
            jobs = c.get_boss_chatted_jobs()
            if jobs:
                job_id = jobs[0].get("encryptJobId", "")

        # View the geek first to show info
        if job_id:
            info = c.get_boss_view_geek(
                encrypt_geek_id=encrypt_geek_id,
                encrypt_job_id=job_id,
            )
        else:
            info = {"encryptGeekId": encrypt_geek_id, "note": "无关联职位, 无法获取详情"}
        return info

    def _render(data: dict) -> None:
        geek_info = data.get("geekDetailInfo", data.get("geekBaseInfo", data))
        base_info = geek_info.get("geekBaseInfo", geek_info) if isinstance(geek_info, dict) else data
        name = base_info.get("name", base_info.get("geekName", "-"))
        console.print(f"[cyan]候选人: {name}[/cyan]  encryptGeekId={encrypt_geek_id}")
        console.print("[dim]提示: 使用 boss recruiter reply <序号> \"正文\" 发送私信[/dim]")

    handle_command(cred, action=_action, render=_render, as_json=as_json, as_yaml=as_yaml)


# ── recruiter batch-view ──────────────────────────────────────────


@recruiter.command("batch-view")
@click.argument("keyword")
@click.option("-c", "--city", default="上海", help="城市名称或代码")
@click.option("-n", "--count", default=5, type=int, help="查看数量 (默认: 5)")
@click.option("--salary", type=click.Choice(list(SALARY_CODES.keys())), help="薪资筛选")
@click.option("--exp", type=click.Choice(list(EXP_CODES.keys())), help="工作经验筛选")
@click.option("--degree", type=click.Choice(list(DEGREE_CODES.keys())), help="学历筛选")
@click.option("--job", "encrypt_job_id", default="", help="关联职位 encryptJobId")
@click.option("--dry-run", is_flag=True, help="仅预览, 不实际查看")
@click.option("-y", "--yes", is_flag=True, help="跳过确认提示")
def recruiter_batch_view(
    keyword: str, city: str, count: int,
    salary: str | None, exp: str | None, degree: str | None,
    encrypt_job_id: str, dry_run: bool, yes: bool,
) -> None:
    """批量查看搜索结果中的候选人简历 (触发 "被查看" 通知)

    BOSS 招聘方侧 "批量打招呼" 需要 __zp_stoken__，被反爬虫拦截。
    此命令通过批量查看候选人简历实现被动外联: 候选人会收到
    "某招聘方查看了你" 的提醒, 是可行的替代方案。

    例: boss recruiter batch-view "golang" --city 上海 -n 10
    """
    cred = require_auth()
    city_code = resolve_city(city)
    salary_code = SALARY_CODES.get(salary) if salary else None
    exp_code = EXP_CODES.get(exp) if exp else None
    degree_code = DEGREE_CODES.get(degree) if degree else None

    try:
        data = run_client_action(
            cred,
            lambda client: client.search_geeks(
                query=keyword, city=city_code,
                experience=exp_code, degree=degree_code,
                salary=salary_code, encrypt_job_id=encrypt_job_id,
            ),
        )

        geek_list = data.get("geekList", data.get("resultList", []))
        if not geek_list:
            console.print("[yellow]未找到匹配候选人[/yellow]")
            return

        targets = geek_list[:count]

        # Preview table
        table = Table(title=f"将查看以下 {len(targets)} 个候选人简历", show_lines=True)
        table.add_column("#", style="dim", width=3)
        table.add_column("姓名", style="bold cyan", max_width=12)
        table.add_column("职位", style="green", max_width=20)
        table.add_column("经验", style="yellow", max_width=10)

        for i, geek in enumerate(targets, 1):
            table.add_row(
                str(i),
                geek.get("name", geek.get("geekName", "-")),
                geek.get("expectPositionName", geek.get("jobName", "-")),
                geek.get("workYearDesc", "-"),
            )

        console.print(table)

        if dry_run:
            console.print("\n  [dim]预览模式, 未实际发送[/dim]")
            return

        if not yes:
            confirm = click.confirm(f"\n确定查看这 {len(targets)} 个候选人简历吗?")
            if not confirm:
                console.print("[dim]已取消[/dim]")
                return

        success = 0
        for i, geek in enumerate(targets, 1):
            geek_id = geek.get("encryptGeekId", geek.get("encryptUid", ""))
            name = geek.get("name", geek.get("geekName", "?"))

            if not geek_id:
                console.print(f"  [{i}] [yellow]跳过 {name} (无 encryptGeekId)[/yellow]")
                continue

            try:
                run_client_action(
                    cred,
                    lambda client, gid=geek_id: client.get_boss_view_geek(
                        encrypt_geek_id=gid,
                        encrypt_job_id=encrypt_job_id,
                    ),
                )
                console.print(f"  [{i}] [green]{name} - 已查看[/green]")
                success += 1
            except BossApiError as e:
                console.print(f"  [{i}] [red]{name}: {e}[/red]")

            if i < len(targets):
                time.sleep(1.5)

        console.print(f"\n[bold]完成: {success}/{len(targets)} 个候选人已处理[/bold]")

    except BossApiError as exc:
        console.print(f"[red]搜索失败: {exc}[/red]")
        raise SystemExit(1) from None


# ── recruiter inbox ──────────────────────────────────────────────


@recruiter.command("inbox")
@click.option("--job", "enc_job_id", default="", help="按职位 encryptJobId 筛选")
@click.option("--label", "label_id", default=0, type=int, help="按标签筛选 (0=全部, 1=新招呼, 2=沟通中)")
@click.option("-n", "--limit", "display_limit", default=0, type=int, help="显示数量 (0=全部)")
@structured_output_options
def recruiter_inbox(enc_job_id: str, label_id: int, display_limit: int, as_json: bool, as_yaml: bool) -> None:
    """查看候选人消息列表 (招聘方沟通列表)"""
    cred = require_auth()

    def _action(c: BossClient) -> dict:
        friend_data = c.get_boss_friend_list(label_id=label_id, enc_job_id=enc_job_id)
        friend_list = friend_data.get("result", [])

        if not friend_list:
            return {"friendList": [], "lastMessages": []}

        friend_ids = [f["friendId"] for f in friend_list if f.get("friendId")]
        fetch_ids = friend_ids[:display_limit] if display_limit > 0 else friend_ids
        if len(fetch_ids) > 50:
            console.print(f"[dim]共 {len(friend_ids)} 人，正在分批拉取详情（{len(fetch_ids)}）...[/dim]")

        details = c.get_boss_friend_details(fetch_ids)
        detail_list = details.get("friendList") or friend_list[:len(fetch_ids)]
        from ..index_cache import save_recruiter_index
        save_recruiter_index(detail_list)

        last_msgs = c.get_boss_last_messages(fetch_ids)

        return {"friendList": detail_list, "lastMessages": last_msgs}

    def _render(data: dict) -> None:
        detail_list = data.get("friendList", [])
        last_msgs = data.get("lastMessages", [])

        if not detail_list:
            console.print("[yellow]暂无候选人消息[/yellow]")
            return

        msg_map: dict[int, dict] = {}
        if isinstance(last_msgs, list):
            for msg in last_msgs:
                uid = msg.get("uid", 0)
                if uid:
                    msg_map[uid] = msg

        total = len(detail_list)
        if display_limit > 0:
            detail_list = detail_list[:display_limit]

        table = Table(title=f"候选人列表 (显示 {len(detail_list)}/{total} 人)", show_lines=True)
        table.add_column("#", style="dim", width=3)
        table.add_column("候选人", style="bold cyan", max_width=12)
        table.add_column("职位", style="green", max_width=20)
        table.add_column("薪资", style="yellow", max_width=10)
        table.add_column("最近消息", style="dim", max_width=30)
        table.add_column("时间", style="dim", max_width=8)

        for i, friend in enumerate(detail_list, 1):
            uid = friend.get("uid", 0)
            msg_info = msg_map.get(uid, {})
            last_text = ""
            if msg_info.get("lastMsgInfo"):
                last_text = msg_info["lastMsgInfo"].get("showText", "")[:28]

            table.add_row(
                str(i),
                friend.get("name", "-"),
                friend.get("jobName", "-"),
                friend.get("salaryDesc", friend.get("lastTime", "-")),
                last_text or "-",
                msg_info.get("lastTime", friend.get("lastTime", "-")),
            )

        console.print(table)
        console.print("  [dim]查看记录: uv run boss recruiter messages <序号>[/dim]")
        console.print('  [dim]发送私信: uv run boss recruiter reply <序号> "正文"[/dim]')
        console.print("  [dim]持续接听: uv run boss recruiter listen[/dim]")

    handle_command(cred, action=_action, render=_render, as_json=as_json, as_yaml=as_yaml)


# ── recruiter reply ──────────────────────────────────────────────


def _load_recruiter_inbox(client) -> list[dict]:
    friend_data = client.get_boss_friend_list()
    friend_list = friend_data.get("result") or []
    friend_ids = [f["friendId"] for f in friend_list if f.get("friendId")]
    if not friend_ids:
        return []
    details = client.get_boss_friend_details(friend_ids)
    detail_list = details.get("friendList") or []
    from ..index_cache import save_recruiter_index
    save_recruiter_index(detail_list)
    return detail_list


def _resolve_recruiter_target(cred, target: str) -> dict:
    from ..index_cache import find_recruiter, save_recruiter_index

    found = find_recruiter(target)
    if found and (found.get("uid") or found.get("friendId")):
        return found
    details = run_client_action(cred, _load_recruiter_inbox)
    save_recruiter_index(details)
    found = find_recruiter(target)
    if found:
        return found
    console.print("[yellow]没有找到该会话。请先运行 uv run boss recruiter inbox[/yellow]")
    raise SystemExit(1)


@recruiter.command("reply")
@click.argument("target")
@click.argument("message")
@click.option("-y", "--yes", is_flag=True, help="跳过确认提示")
def recruiter_reply(target: str, message: str, yes: bool) -> None:
    """向候选人发送私信（MQTT）。

    TARGET 可以是 inbox 序号（如 1）或 friendId。

    例: boss recruiter reply 1 "您好，方便聊聊吗？"
    """
    cred = require_auth()
    text = message.strip()
    if not text:
        console.print("[red]消息内容不能为空[/red]")
        raise SystemExit(1)

    meta = _resolve_recruiter_target(cred, target)
    to_uid = meta.get("uid") or meta.get("friendId")
    to_enc = str(meta.get("encryptGeekId") or "")
    name = meta.get("name") or str(to_uid)
    if not to_uid:
        console.print("[red]该会话缺少 uid，无法发送。请先运行 uv run boss recruiter inbox[/red]")
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
            lambda c: c.send_boss_message(to_uid=int(to_uid), to_encrypt_uid=to_enc, text=text),
        )
    except BossApiError as exc:
        console.print(f"[red]发送失败: {exc}[/red]")
        raise SystemExit(1) from None
    except Exception as exc:
        console.print(f"[red]发送失败: {exc}[/red]")
        raise SystemExit(1) from None

    console.print(f"[green]已发送给 {name}[/green]")
    console.print("[dim]可用 uv run boss recruiter messages 查看是否出现在记录里[/dim]")


@recruiter.command("listen")
@click.option("-t", "--timeout", "duration", default=0, type=int, help="监听秒数，0 表示直到 Ctrl+C")
@click.option("--poll", "poll_seconds", default=0, type=int, help="额外按秒轮询沟通列表，0 关闭")
@click.option("--all", "show_all", is_flag=True, help="也显示自己发出的消息")
@click.option("--backlog", is_flag=True, help="也显示连上时补推的历史消息")
@click.option("--json-lines", is_flag=True, help="每条消息输出一行 JSON")
def recruiter_listen(duration: int, poll_seconds: int, show_all: bool, backlog: bool, json_lines: bool) -> None:
    """持续接听候选人发来的私信（MQTT），仅监听不自动回复。按 Ctrl+C 结束。

    需要自动回复/自动加微信时，改用 ``boss recruiter auto-wechat``
    或网页版 ``boss recruiter web``（--no-auto-wechat 可关闭自动回复）。
    """
    from ..index_cache import find_recruiter_by_uid, load_recruiter_items
    from ..mqtt_chat import IDENTITY_BOSS, format_listen_time, run_mqtt_listen

    cred = require_auth()
    console.print("[dim]正在获取认证并连接 MQTT...[/dim]")
    try:
        if not load_recruiter_items():
            run_client_action(cred, _load_recruiter_inbox)
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
        stamp = payload.get("time") or format_listen_time(0)
        style = "green" if direction == "对方" else "blue"
        console.print(f"[dim]{stamp}[/dim] [{style}]{direction}[/{style}] {name}: {text}")

    def _lookup(uid: int) -> str | None:
        item = find_recruiter_by_uid(uid)
        return (item or {}).get("name") or None

    def _refresh() -> None:
        run_client_action(cred, _load_recruiter_inbox)

    def _poll() -> None:
        try:
            data = run_client_action(cred, lambda c: c.get_boss_friend_list())
        except BossApiError as exc:
            logger.debug("recruiter listen poll failed: %s", exc)
            return
        friends = data.get("result") or []
        first = not seen_poll
        for i, friend in enumerate(friends, 1):
            key = str(friend.get("friendId") or friend.get("uid") or i)
            last_msg = str(friend.get("lastMsg") or friend.get("lastText") or "")
            if first:
                seen_poll[key] = last_msg
                continue
            if last_msg and seen_poll.get(key) != last_msg:
                _emit({
                    "time": format_listen_time(0),
                    "direction": "对方",
                    "name": friend.get("name") or key,
                    "uid": friend.get("uid") or friend.get("friendId"),
                    "mid": None,
                    "text": last_msg,
                    "source": "poll",
                })
            seen_poll[key] = last_msg

    def _status(text: str) -> None:
        if "连接中断" in text:
            console.print(f"[yellow]{text}[/yellow]")
            return
        console.print(f"[dim]{text}[/dim]")

    def _reconnect():
        token, secret, info, jar = run_client_action(
            cred,
            lambda c: (*c.get_ws_auth(), c.session_cookies()),
        )
        return token, secret, jar, info.get("userId") or my_uid

    console.print("[green]已连接，正在接听私信。[/green] [dim]Ctrl+C 结束[/dim]")
    if poll_seconds > 0:
        console.print(f"[dim]额外每 {poll_seconds}s 轮询沟通列表[/dim]")

    try:
        run_mqtt_listen(
            page_token=page_token,
            wt2=wt2,
            cookies=cookies,
            my_uid=my_uid,
            identity=IDENTITY_BOSS,
            duration=duration,
            poll_seconds=poll_seconds,
            show_all=show_all,
            backlog=backlog,
            on_message=_emit,
            lookup_peer=_lookup,
            refresh_peers=_refresh,
            poll_once=_poll if poll_seconds > 0 else None,
            on_status=_status,
            on_reconnect=_reconnect,
        )
    except KeyboardInterrupt:
        console.print("\n[dim]已停止接听[/dim]")


@recruiter.command("auto-wechat")
@click.option("-t", "--timeout", "duration", default=0, type=int, help="监听秒数，0 表示直到 Ctrl+C")
@click.option(
    "--greeting", default="还在看工作吗？方便聊聊吗？", show_default=True,
    help="首条自动问候文案",
)
@click.option(
    "--text", "contact_text",
    default="我们通过平台交换下联系方式，方便后续沟通", show_default=True,
    help="第二步换联系方式文案（随后自动发起交换微信）",
)
@click.option("--reset", is_flag=True, help="清空自动加微信状态，重新对所有会话执行")
def recruiter_auto_wechat(
    duration: int,
    greeting: str,
    contact_text: str,
    reset: bool,
) -> None:
    """监听候选人消息，自动两步加微信（问候→换联系方式+交换微信），每会话只走一遍。

    收到候选人新消息后：
      第一步 回复「{greeting}」；
      对方再回复后，第二步 发送「{contact_text}」并自动发起交换微信；
    每步随机等待 5–8 秒；每个会话只走一遍（状态记录在
    recruiter_auto_wechat.json）。--reset 可清空状态重新执行。
    需扫码登录招聘者账号（boss login --qrcode）。Ctrl+C 结束。
    """
    import random
    import threading

    from ..index_cache import find_recruiter_by_uid, load_recruiter_items
    from ..mqtt_chat import IDENTITY_BOSS, format_listen_time, run_mqtt_listen
    from ..webchat.server import (
        _is_system_peer,
        _load_auto_wechat_state,
        _save_auto_wechat_state,
    )

    cred = require_auth()

    console.print("[dim]正在获取认证并连接 MQTT...[/dim]")
    try:
        if not load_recruiter_items():
            run_client_action(cred, _load_recruiter_inbox)
        page_token, wt2, user_info, cookies = run_client_action(
            cred,
            lambda c: (*c.get_ws_auth(), c.session_cookies()),
        )
    except BossApiError as exc:
        console.print(f"[red]连接失败: {exc}[/red]")
        raise SystemExit(1) from None

    my_uid = user_info.get("userId")
    # 状态按登录账号分桶，多账号互不干扰
    account_key = str(int(my_uid or 0))

    if reset:
        _save_auto_wechat_state({}, account_key)
        console.print(f"[green]已清空当前账号的自动加微信状态，之后将重新对所有会话执行[/green]")

    state = _load_auto_wechat_state(account_key)
    busy: set[str] = set()
    lock = threading.RLock()

    def _save() -> None:
        with lock:
            _save_auto_wechat_state(dict(state), account_key)

    def _lookup(uid: int) -> str | None:
        item = find_recruiter_by_uid(uid)
        return (item or {}).get("name") or None

    def _refresh() -> None:
        run_client_action(cred, _load_recruiter_inbox)

    def _run_step(friend_id: int, name: str, key: str, step: str, prev: str) -> None:
        try:
            delay = random.uniform(5.0, 8.0)
            time.sleep(delay)
            text = greeting if step == "greeting" else contact_text
            sent = run_client_action(cred, lambda c: c.boss_send_message(friend_id, text))
            if not (sent or {}).get("ok", True):
                err = ((sent or {}).get("error") or {}).get("message") or "发送失败"
                logger.warning("auto-wechat 发送失败 friendId=%s: %s", friend_id, err)
                with lock:
                    state[key] = "skip"
                _save()
                return
            console.print(f"[blue]自动回复 {name or friend_id}[/blue]: {text}")
            if step == "contact":
                def _exchange(c: BossClient) -> dict:
                    details = c.get_boss_friend_details([friend_id])
                    fl = (details.get("friendList") or [{}])
                    friend = fl[0] if fl else {}
                    sid = str(friend.get("securityId") or "")
                    uid = int(friend.get("uid") or friend_id)
                    fs = int(friend.get("friendSource") or 0)
                    nm = str(friend.get("name") or "")
                    return c.boss_exchange_request(
                        security_id=sid, unique_id=f"{uid}-{fs}", exchange_type=2, name=nm,
                    )
                run_client_action(cred, _exchange)
                console.print(f"[green]已向 {name or friend_id} 发起交换微信[/green]")
        except Exception as exc:
            logger.warning("auto-wechat 失败 friendId=%s: %s", friend_id, exc)
            with lock:
                state[key] = "skip"
            _save()
        finally:
            with lock:
                busy.discard(key)

    def _schedule(friend_id: int, name: str) -> None:
        key = str(friend_id)
        if key in {"0", ""}:
            return
        if _is_system_peer(friend_id):
            return
        with lock:
            prev = state.get(key, "")
            if prev in {"done", "skip"} or key in busy:
                return
            if prev == "greeted":
                step, next_state = "contact", "done"
            else:
                step, next_state = "greeting", "greeted"
            busy.add(key)
            state[key] = next_state
        _save()
        threading.Thread(
            target=_run_step, args=(int(friend_id), name, key, step, prev), daemon=True,
        ).start()

    def _emit(payload: dict) -> None:
        direction = payload.get("direction") or "对方"
        stamp = payload.get("time") or format_listen_time(0)
        name = payload.get("name") or ""
        text = payload.get("text") or ""
        style = "green" if direction == "对方" else "blue"
        console.print(f"[dim]{stamp}[/dim] [{style}]{direction}[/{style}] {name}: {text}")
        if direction == "对方":
            friend_id = int(payload.get("uid") or 0)
            if friend_id:
                _schedule(friend_id, name)

    def _status(text: str) -> None:
        if "连接中断" in text:
            console.print(f"[yellow]{text}[/yellow]")
            return
        console.print(f"[dim]{text}[/dim]")

    def _reconnect():
        token, secret, info, jar = run_client_action(
            cred,
            lambda c: (*c.get_ws_auth(), c.session_cookies()),
        )
        return token, secret, jar, info.get("userId") or my_uid

    console.print(
        "[green]已连接，自动加微信已开启[/green][dim]：收到候选人消息后，首条回复「"
        f"{greeting}」，对方再回后发送「{contact_text}」并交换微信；"
        "每步随机等待 5–8 秒；每会话只走一遍。Ctrl+C 结束[/dim]"
    )
    try:
        run_mqtt_listen(
            page_token=page_token,
            wt2=wt2,
            cookies=cookies,
            my_uid=my_uid,
            identity=IDENTITY_BOSS,
            duration=duration,
            poll_seconds=0,
            show_all=False,
            backlog=False,
            on_message=_emit,
            lookup_peer=_lookup,
            refresh_peers=_refresh,
            poll_once=None,
            on_status=_status,
            on_reconnect=_reconnect,
        )
    except KeyboardInterrupt:
        console.print("\n[dim]已停止自动加微信[/dim]")


@recruiter.command("web")
@click.option("--host", default="127.0.0.1", show_default=True, help="监听地址，默认仅本机")
@click.option("--port", default=8765, type=int, show_default=True, help="端口")
@click.option("--no-open", is_flag=True, help="不自动打开浏览器")
@click.option(
    "--auto-wechat/--no-auto-wechat",
    default=True,
    show_default=True,
    help="来新消息时自动两步招呼并交换微信（每个会话只走一遍）；--no-auto-wechat 关闭自动回复",
)
@click.option(
    "--auto-wechat-greeting",
    default=None,
    help="首条自动问候文案（默认「还在看工作吗？方便聊聊吗？」）",
)
@click.option(
    "--auto-wechat-text",
    default="我们通过平台交换下联系方式，方便后续沟通",
    show_default=True,
    help="第二步换联系方式文案",
)
def recruiter_web(
    host: str,
    port: int,
    no_open: bool,
    auto_wechat: bool,
    auto_wechat_greeting: str | None,
    auto_wechat_text: str,
) -> None:
    """打开本机网页版沟通：头像、昵称、气泡会话，可收发消息。

    默认开启自动加微信；用 --no-auto-wechat 可关闭（仅人工收发，不自动回复）。
    """
    import webbrowser

    cred = require_auth()
    if host not in {"127.0.0.1", "localhost", "::1"}:
        console.print("[yellow]监听非本机地址会把当前登录会话暴露到局域网。[/yellow]")
        if not click.confirm("仍然继续?"):
            return

    from ..webchat import serve_recruiter_web

    server = serve_recruiter_web(
        cred,
        host,
        port,
        auto_wechat=auto_wechat,
        auto_wechat_text=auto_wechat_text,
        auto_wechat_greeting=auto_wechat_greeting or "",
    )
    url = f"http://{host}:{port}/"
    console.print(f"[green]网页版沟通已启动[/green]  {url}")
    console.print("[dim]左侧会话列表，右侧聊天。Ctrl+C 结束。[/dim]")
    if auto_wechat:
        console.print(
            "[cyan]自动加微信已开启[/cyan][dim]：首条消息回复「"
            f"{auto_wechat_greeting or '还在看工作吗？方便聊聊吗？'}」，"
            f"对方再回后发送「{auto_wechat_text}」并交换微信；每步随机等待 5–8 秒；每会话只走一遍。"
            "关闭: --no-auto-wechat[/dim]"
        )
    else:
        console.print("[dim]自动回复已关闭（--no-auto-wechat）：仅人工收发，不自动加微信[/dim]")
    if not no_open:
        try:
            webbrowser.open(url)
        except Exception:
            logger.debug("open browser failed", exc_info=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        console.print("\n[dim]已关闭网页版沟通[/dim]")
    finally:
        app = getattr(server, "web_app", None)
        if app is not None:
            app.stop()
        server.shutdown()
        server.server_close()


# ── recruiter export ──────────────────────────────────────────────


@recruiter.command("export")
@click.option("--job", "enc_job_id", default="", help="按职位 encryptJobId 筛选")
@click.option("-o", "--output", "output_file", default=None, help="输出文件路径")
@click.option("--format", "fmt", type=click.Choice(["csv", "json"]), default="csv", help="输出格式")
def recruiter_export(enc_job_id: str, output_file: str | None, fmt: str) -> None:
    """导出候选人列表为 CSV 或 JSON"""
    cred = require_auth()

    try:
        def _collect(c: BossClient) -> list[dict]:
            friend_data = c.get_boss_friend_list(enc_job_id=enc_job_id)
            friend_list = friend_data.get("result", [])

            if not friend_list:
                return []

            friend_ids = [f["friendId"] for f in friend_list if f.get("friendId")]
            details = c.get_boss_friend_details(friend_ids)
            return details.get("friendList", [])

        all_candidates = run_client_action(cred, _collect)

        if not all_candidates:
            console.print("[yellow]暂无候选人数据[/yellow]")
            return

        if fmt == "json":
            output_text = json.dumps(all_candidates, indent=2, ensure_ascii=False)
        else:
            buf = io.StringIO()
            fieldnames = ["姓名", "关联职位", "来源", "最近时间", "新牛人", "encryptUid", "securityId"]
            writer = csv.DictWriter(buf, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            for f in all_candidates:
                source_map = {1: "搜索", 2: "推荐", 3: "打招呼", 5: "主动沟通"}
                writer.writerow({
                    "姓名": f.get("name", ""),
                    "关联职位": f.get("jobName", ""),
                    "来源": source_map.get(f.get("sourceType"), str(f.get("sourceType", ""))),
                    "最近时间": f.get("lastTime", ""),
                    "新牛人": "是" if f.get("newGeek") else "",
                    "encryptUid": f.get("encryptUid", f.get("encryptFriendId", "")),
                    "securityId": f.get("securityId", ""),
                })
            output_text = buf.getvalue()

        if output_file:
            with open(output_file, "w", encoding="utf-8-sig" if fmt == "csv" else "utf-8") as fh:
                fh.write(output_text)
            console.print(f"\n[green]已导出 {len(all_candidates)} 个候选人到 {output_file}[/green]")
        else:
            click.echo(output_text)

    except BossApiError as exc:
        console.print(f"[red]导出失败: {exc}[/red]")
        raise SystemExit(1) from None


@recruiter.command("export-messages")
@click.option("-n", "--limit", "conv_limit", default=20, type=int, help="本批导出会话数，0=从 offset 起到 inbox 末尾")
@click.option("--offset", default=0, type=int, help="跳过 inbox 前 N 个会话，用于分批")
@click.option("--all", "full_history", is_flag=True, help="每个会话自动翻页拉完整记录")
@click.option("-o", "--output", "output_file", required=True, help="输出 JSON 文件路径")
@click.option("--page-size", default=50, type=int, help="每个会话每页条数")
@click.option("-y", "--yes", is_flag=True, help="会话很多时跳过确认")
def recruiter_export_messages(
    conv_limit: int, offset: int, full_history: bool, output_file: str, page_size: int, yes: bool,
) -> None:
    """分批导出候选人聊天记录为 JSON。默认导出 inbox 前 20 个会话。

    例:
      boss recruiter export-messages -n 50 --offset 0 --all -o batch-1.json
      boss recruiter export-messages -n 50 --offset 50 --all -o batch-2.json
    """
    cred = require_auth()
    if conv_limit < 0:
        console.print("[red]--limit 不能为负数[/red]")
        raise SystemExit(1)
    if offset < 0:
        console.print("[red]--offset 不能为负数[/red]")
        raise SystemExit(1)
    if not yes and (conv_limit == 0 or conv_limit > 50):
        label = "剩余全部会话" if conv_limit == 0 else f"{conv_limit} 个会话"
        extra = "，且每个会话翻完全部页" if full_history else ""
        start = f"从第 {offset + 1} 个起" if offset else ""
        if not click.confirm(f"将导出{start}{label}{extra}，可能较慢并触发限流。继续?"):
            console.print("[dim]已取消[/dim]")
            return

    def _collect(c: BossClient) -> tuple[list[dict], int]:
        items = _load_recruiter_inbox(c)
        inbox_total = len(items)
        sliced = items[offset:] if offset else items
        if conv_limit > 0:
            sliced = sliced[:conv_limit]
        chats = []
        total = len(sliced)
        for i, friend in enumerate(sliced, 1):
            gid = int(friend.get("friendId") or friend.get("uid") or 0)
            if not gid:
                continue
            inbox_index = offset + i
            console.print(f"[dim]{i}/{total} (inbox #{inbox_index}) 正在拉取会话 {gid}[/dim]")
            if full_history:
                history = c.get_boss_chat_history_all(gid=gid, page_size=max(page_size, 20))
            else:
                history = c.get_boss_chat_history(gid=gid, count=max(page_size, 20))
            chats.append({
                "index": inbox_index,
                "friendId": gid,
                "uid": friend.get("uid") or gid,
                "name": friend.get("name") or "",
                "job": friend.get("jobName") or friend.get("job") or "",
                "count": history.get("count", len(history.get("messages") or [])),
                "hasMore": history.get("hasMore", False),
                "pages": history.get("pages"),
                "messages": history.get("messages") or [],
            })
        return chats, inbox_total

    try:
        chats, inbox_total = run_client_action(cred, _collect)
    except BossApiError as exc:
        console.print(f"[red]导出失败: {exc}[/red]")
        raise SystemExit(1) from None

    next_offset = offset + len(chats)
    payload = {
        "ok": True,
        "schema_version": "1",
        "count": len(chats),
        "offset": offset,
        "limit": conv_limit,
        "inboxTotal": inbox_total,
        "nextOffset": next_offset if next_offset < inbox_total else None,
        "fullHistory": full_history,
        "conversations": chats,
    }
    path = Path(output_file)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    console.print(f"[green]已导出 {len(chats)} 个会话到 {path.resolve()}[/green]")
    if next_offset < inbox_total:
        remain = inbox_total - next_offset
        console.print(
            f"[dim]还剩 {remain} 个。下一批: "
            f"boss recruiter export-messages -n {conv_limit or 20} --offset {next_offset} "
            f"{'--all ' if full_history else ''}-o batch-next.json[/dim]"
        )
    else:
        console.print("[dim]inbox 已全部覆盖[/dim]")


# ── recruiter resume ──────────────────────────────────────────────


@recruiter.command("resume")
@click.argument("encrypt_geek_id")
@click.option("--job", "encrypt_job_id", default="", help="关联职位 encryptJobId")
@click.option("--security-id", default="", help="候选人 securityId")
@structured_output_options
def recruiter_resume(
    encrypt_geek_id: str, encrypt_job_id: str, security_id: str,
    as_json: bool, as_yaml: bool,
) -> None:
    """查看候选人完整简历 (View candidate full resume)"""
    cred = require_auth()

    def _action(c: BossClient) -> dict:
        nonlocal encrypt_job_id, security_id
        if not encrypt_job_id:
            jobs = c.get_boss_chatted_jobs()
            if jobs:
                encrypt_job_id = jobs[0].get("encryptJobId", "")

        if not encrypt_job_id:
            return {"error": "未找到关联职位, 请通过 --job 指定 encryptJobId"}

        # Auto-fetch securityId from friend list if not provided
        if not security_id:
            friend_data = c.get_boss_friend_list()
            for f in friend_data.get("result", []):
                if f.get("encryptFriendId") == encrypt_geek_id:
                    friend_ids = [f["friendId"]]
                    details = c.get_boss_friend_details(friend_ids)
                    for fd in details.get("friendList", []):
                        security_id = fd.get("securityId", "")
                        break
                    break

        return c.get_boss_view_geek(
            encrypt_geek_id=encrypt_geek_id,
            encrypt_job_id=encrypt_job_id,
            security_id=security_id,
        )

    def _render(data: dict) -> None:
        if data.get("error"):
            console.print(f"[red]{data['error']}[/red]")
            return

        # Navigate the nested response structure
        geek_detail = data.get("geekDetailInfo", data)
        base_info = geek_detail.get("geekBaseInfo", geek_detail)

        name = base_info.get("name", base_info.get("geekName", "-"))
        gender_val = base_info.get("gender", 0)
        gender = "男" if gender_val == 1 else "女" if gender_val == 2 else "-"
        degree = base_info.get("degreeCategory", base_info.get("degree", "-"))
        work_year = base_info.get("workYearDesc", base_info.get("workYear", "-"))
        age = base_info.get("ageDesc", base_info.get("age", "-"))
        apply_status = base_info.get("applyStatusContent", base_info.get("applyStatus", "-"))
        expect_position = base_info.get("expectPosition", "-")
        expect_city = base_info.get("expectCity", "-")
        expect_salary = base_info.get("expectSalary", base_info.get("salaryDesc", "-"))

        panel_text = (
            f"[bold cyan]{name}[/bold cyan]  {gender}  {age}\n"
            f"学历: {degree} | 工作年限: {work_year}\n"
            f"求职状态: {apply_status}\n"
            f"\n"
            f"[bold yellow]期望:[/bold yellow] {expect_position} | {expect_city} | {expect_salary}\n"
        )

        # Work experience
        work_exp = geek_detail.get("geekWorkExpList", base_info.get("workExpList", []))
        if work_exp:
            panel_text += "\n[bold green]工作经历:[/bold green]\n"
            for w in work_exp[:6]:
                company = w.get("company", w.get("companyName", ""))
                position = w.get("positionName", w.get("position", ""))
                time_desc = w.get("timeDesc", w.get("workTime", ""))
                industry = w.get("industry", "")
                desc = w.get("description", w.get("workDesc", ""))
                panel_text += f"  {time_desc}  [cyan]{company}[/cyan]"
                if industry:
                    panel_text += f" ({industry})"
                panel_text += f"\n    {position}\n"
                if desc:
                    panel_text += f"    [dim]{desc[:80]}[/dim]\n"

        # Education
        edu_exp = geek_detail.get("geekEduExpList", base_info.get("eduExpList", []))
        if edu_exp:
            panel_text += "\n[bold magenta]教育经历:[/bold magenta]\n"
            for e in edu_exp[:4]:
                school = e.get("school", e.get("schoolName", ""))
                major_name = e.get("major", e.get("majorName", ""))
                degree_name = e.get("degree", e.get("degreeName", ""))
                time_desc = e.get("timeDesc", e.get("eduTime", ""))
                panel_text += f"  {time_desc}  [cyan]{school}[/cyan]  {degree_name}\n"
                if major_name:
                    panel_text += f"    {major_name}\n"

        # Projects
        project_exp = geek_detail.get("geekProjectExpList", base_info.get("projectExpList", []))
        if project_exp:
            panel_text += "\n[bold blue]项目经历:[/bold blue]\n"
            for p in project_exp[:4]:
                proj_name = p.get("projectName", p.get("name", ""))
                role = p.get("roleName", p.get("role", ""))
                time_desc = p.get("timeDesc", p.get("projectTime", ""))
                desc = p.get("description", p.get("projectDesc", ""))
                panel_text += f"  {time_desc}  [cyan]{proj_name}[/cyan]  ({role})\n"
                if desc:
                    panel_text += f"    [dim]{desc[:100]}[/dim]\n"

        panel = Panel(panel_text.rstrip(), title="候选人简历", border_style="cyan")
        console.print(panel)

    handle_command(cred, action=_action, render=_render, as_json=as_json, as_yaml=as_yaml)


# ── recruiter labels ──────────────────────────────────────────────


@recruiter.command("labels")
@structured_output_options
def recruiter_labels(as_json: bool, as_yaml: bool) -> None:
    """查看候选人标签列表"""
    cred = require_auth()

    def _render(data: dict) -> None:
        labels = data.get("labels", data.get("labelList", data.get("result", [])))
        if isinstance(data, list):
            labels = data

        if not labels:
            console.print("[yellow]暂无标签[/yellow]")
            return

        table = Table(title="标签列表", show_lines=False)
        table.add_column("ID", style="dim", width=6)
        table.add_column("名称", style="cyan", max_width=20)

        for label in labels:
            table.add_row(
                str(label.get("labelId", label.get("id", "-"))),
                label.get("label", label.get("name", label.get("labelName", "-"))),
            )

        console.print(table)

    handle_command(
        cred, action=lambda c: c.get_boss_friend_labels(),
        render=_render, as_json=as_json, as_yaml=as_yaml,
    )


# ── recruiter chat (history) ──────────────────────────────────────


@recruiter.command("chat")
@click.argument("target")
@click.option("-n", "--count", default=20, type=int, help="每页消息数量 (默认: 20)")
@click.option("--all", "fetch_all", is_flag=True, help="自动翻页拉取该会话全部记录")
@click.option("--max-msg-id", default=0, type=int, help="翻页游标，传上一页最小 mid")
@click.option("-o", "--output", "output_path", default=None, help="写入 JSON 文件")
@structured_output_options
def recruiter_chat(
    target: str, count: int, fetch_all: bool, max_msg_id: int,
    output_path: str | None, as_json: bool, as_yaml: bool,
) -> None:
    """查看与候选人的聊天记录。TARGET 为 inbox 序号或 friendId。"""
    _recruiter_show_history(
        target, count, as_json, as_yaml,
        fetch_all=fetch_all, max_msg_id=max_msg_id, output_path=output_path,
    )


@recruiter.command("messages")
@click.argument("target")
@click.option("-n", "--count", default=20, type=int, help="每页消息数量 (默认: 20)")
@click.option("--all", "fetch_all", is_flag=True, help="自动翻页拉取该会话全部记录")
@click.option("--max-msg-id", default=0, type=int, help="翻页游标，传上一页最小 mid")
@click.option("-o", "--output", "output_path", default=None, help="写入 JSON 文件")
@structured_output_options
def recruiter_messages(
    target: str, count: int, fetch_all: bool, max_msg_id: int,
    output_path: str | None, as_json: bool, as_yaml: bool,
) -> None:
    """查看与候选人的聊天记录（同 recruiter chat）。"""
    _recruiter_show_history(
        target, count, as_json, as_yaml,
        fetch_all=fetch_all, max_msg_id=max_msg_id, output_path=output_path,
    )


def _clean_message_text(text: str) -> str:
    """清理 BOSS 消息文本中的 HTML 实体与可复制标签。

    BOSS 会在微信号、手机号等可复制内容外包一层
    ``<copy>...</copy>`` / ``<phone>...</phone>`` 等标签，
    部分场景下又被转义成 ``&lt;copy&gt;``/``&lt;/copy&gt;``。
    此函数统一反转义 + 移除标签，返回干净文本。
    """
    if not text:
        return ""
    t = html.unescape(str(text))
    # 移除 BOSS 消息模板标签（微信号/手机号/职位等可复制区域）
    t = re.sub(
        r"</?(?:copy|phone|job|company|encrypt|tel|span)\b[^>]*>",
        "",
        t,
        flags=re.IGNORECASE,
    )
    return t.strip()


def _clean_history_messages(messages: list[dict]) -> list[dict]:
    """就地清理聊天记录里所有含文本的字段（body.text/showText/pushText 等）。"""
    for msg in messages:
        body = msg.get("body")
        if isinstance(body, dict):
            for key in ("text", "showText", "pushText", "content"):
                if isinstance(body.get(key), str):
                    body[key] = _clean_message_text(body[key])
        elif isinstance(body, str):
            msg["body"] = _clean_message_text(body)
        if isinstance(msg.get("pushText"), str):
            msg["pushText"] = _clean_message_text(msg["pushText"])
    return messages


def _recruiter_show_history(
    target: str, count: int, as_json: bool, as_yaml: bool,
    *,
    fetch_all: bool = False,
    max_msg_id: int = 0,
    output_path: str | None = None,
) -> None:
    cred = require_auth()
    meta = _resolve_recruiter_target(cred, target)
    friend_id = int(meta.get("friendId") or meta.get("uid") or 0)
    if not friend_id:
        console.print("[red]该会话缺少 friendId[/red]")
        raise SystemExit(1)
    page_size = count if count > 0 else 20

    def _action(c: BossClient) -> dict:
        if fetch_all:
            history = c.get_boss_chat_history_all(
                gid=friend_id, page_size=max(page_size, 20), start_msg_id=max_msg_id,
            )
        else:
            history = c.get_boss_chat_history(
                gid=friend_id, count=page_size, max_msg_id=max_msg_id,
            )
        messages = _clean_history_messages(history.get("messages") or [])
        return {"peer": meta, "friendId": friend_id, **history, "messages": messages}

    def _render(data: dict) -> None:
        messages = data.get("messages", [])
        title = meta.get("name") or str(friend_id)
        if not messages:
            console.print(f"[yellow]暂无聊天记录[/yellow] ({title})")
            return

        table = Table(title=f"与 {title} 的聊天记录 ({len(messages)} 条)", show_lines=True)
        table.add_column("#", style="dim", width=3)
        table.add_column("方向", max_width=6)
        table.add_column("内容", max_width=50)
        table.add_column("类型", style="dim", max_width=6)

        for i, msg in enumerate(messages, 1):
            direction = "[cyan]<-[/cyan]" if msg.get("received", True) else "[green]->[/green]"

            body = msg.get("body", {})
            if isinstance(body, str):
                text = _clean_message_text(body[:48])
            elif isinstance(body, dict):
                text = body.get("text", body.get("showText", ""))
                if not text and body.get("resume"):
                    resume = body["resume"]
                    text = f"[简历] {resume.get('user', {}).get('name', '')} {resume.get('positionCategory', '')}"
                text = _clean_message_text(text)[:48] if text else "[多媒体消息]"
            else:
                text = str(body)[:48]

            msg_type = str(msg.get("type", "-"))
            table.add_row(str(i), direction, text, msg_type)

        console.print(table)
        if data.get("hasMore") and not fetch_all:
            mids = [m.get("mid") or m.get("msgId") for m in messages if m.get("mid") or m.get("msgId")]
            nxt = min(int(x) for x in mids) if mids else 0
            console.print(f"  [dim]更多: boss recruiter messages {target} --all[/dim]")
            console.print(f"  [dim]或: boss recruiter messages {target} --max-msg-id {nxt} -n {page_size}[/dim]")
        elif data.get("hasMore"):
            console.print("[yellow]已达翻页上限，可能还有更早的记录[/yellow]")
        console.print(f'  [dim]回复: boss recruiter reply {target} "正文"[/dim]')

    if output_path:
        try:
            data = run_client_action(cred, _action)
        except BossApiError as exc:
            console.print(f"[red]{exc}[/red]")
            raise SystemExit(1) from None
        payload = {"ok": True, "schema_version": "1", **data}
        path = Path(output_path)
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        console.print(f"[green]已写入[/green] {path.resolve()}  ({data.get('count', len(data.get('messages') or []))} 条)")
        if as_json:
            click.echo(json.dumps(payload, indent=2, ensure_ascii=False))
        elif not as_yaml:
            _render(data)
        return

    handle_command(cred, action=_action, render=_render, as_json=as_json, as_yaml=as_yaml)


# ── recruiter geek (legacy - kept as alias for resume) ────────────


@recruiter.command("geek")
@click.argument("encrypt_geek_id")
@click.option("--security-id", default="", help="候选人 securityId")
@click.option("--job-id", default=0, type=int, help="关联职位 ID")
@structured_output_options
def recruiter_geek(
    encrypt_geek_id: str, security_id: str, job_id: int,
    as_json: bool, as_yaml: bool,
) -> None:
    """查看候选人详细信息 (需要 encryptGeekId)"""
    cred = require_auth()

    def _action(c: BossClient) -> dict:
        nonlocal job_id, security_id
        if not job_id:
            jobs = c.get_boss_chatted_jobs()
            if jobs:
                job_id = jobs[0].get("jobId", 0)

        if not security_id:
            friend_data = c.get_boss_friend_list()
            for f in friend_data.get("result", []):
                if f.get("encryptFriendId") == encrypt_geek_id:
                    friend_details = c.get_boss_friend_details([f["friendId"]])
                    for fd in friend_details.get("friendList", []):
                        security_id = fd.get("securityId", "")
                        break
                    break

        return c.get_boss_chat_geek_info(
            encrypt_geek_id=encrypt_geek_id,
            security_id=security_id,
            job_id=job_id,
        )

    def _render(data: dict) -> None:
        geek = data.get("data", data)

        name = geek.get("name", "-")
        age = geek.get("ageDesc", "-")
        gender = "男" if geek.get("gender") == 1 else "女" if geek.get("gender") == 2 else "-"
        edu = geek.get("edu", "-")
        city = geek.get("city", "-")
        salary = geek.get("salaryDesc", "-")
        expect_salary = geek.get("price", "-")
        position = geek.get("positionName", geek.get("toPosition", "-"))
        status = geek.get("positionStatus", "-")
        last_company = geek.get("lastCompany", "-")
        last_position = geek.get("lastPosition", "-")
        school = geek.get("school", "-")
        major = geek.get("major", "-")
        work_year = geek.get("year", "-")

        work_exp = geek.get("workExpList", [])
        work_lines = []
        for w in work_exp[:5]:
            work_lines.append(
                f"  {w.get('timeDesc', '')}  {w.get('company', '')} · {w.get('positionName', '')}"
            )

        panel_text = (
            f"[bold cyan]{name}[/bold cyan]  {gender}  {age}\n"
            f"学历: {edu} | 工作年限: {work_year}\n"
            f"城市: {city} | 求职状态: {status}\n"
            f"\n"
            f"[bold yellow]期望薪资:[/bold yellow] {expect_salary}\n"
            f"[bold yellow]当前薪资:[/bold yellow] {salary}\n"
            f"期望职位: {position}\n"
            f"\n"
            f"[bold green]当前/最近:[/bold green] {last_company}\n"
            f"职位: {last_position}\n"
            f"学校: {school} | {major}\n"
        )

        if work_lines:
            panel_text += "\n[bold magenta]工作经历:[/bold magenta]\n" + "\n".join(work_lines)

        panel = Panel(panel_text, title="候选人详情", border_style="cyan")
        console.print(panel)

    handle_command(cred, action=_action, render=_render, as_json=as_json, as_yaml=as_yaml)


# ── recruiter resume-download ─────────────────────────────────────


@recruiter.command("resume-download")
@click.argument("encrypt_geek_id")
@click.option("--job", "encrypt_job_id", default="", help="关联职位 encryptJobId")
@click.option("--security-id", default="", help="候选人 securityId")
@click.option("-o", "--output", "output_file", default=None, help="输出文件路径 (默认: <姓名>_resume.md)")
def recruiter_resume_download(
    encrypt_geek_id: str, encrypt_job_id: str, security_id: str, output_file: str | None,
) -> None:
    """导出候选人简历为 Markdown 文件"""
    cred = require_auth()

    try:
        def _fetch(c: BossClient) -> dict:
            nonlocal encrypt_job_id, security_id
            if not encrypt_job_id:
                jobs = c.get_boss_chatted_jobs()
                if jobs:
                    encrypt_job_id = jobs[0].get("encryptJobId", "")

            if not encrypt_job_id:
                return {"error": "未找到关联职位, 请通过 --job 指定 encryptJobId"}

            # Auto-fetch securityId from friend list if not provided
            if not security_id:
                friend_data = c.get_boss_friend_list()
                for f in friend_data.get("result", []):
                    if f.get("encryptFriendId") == encrypt_geek_id:
                        friend_ids = [f["friendId"]]
                        details = c.get_boss_friend_details(friend_ids)
                        for fd in details.get("friendList", []):
                            security_id = fd.get("securityId", "")
                            break
                        break

            return c.get_boss_view_geek(
                encrypt_geek_id=encrypt_geek_id,
                encrypt_job_id=encrypt_job_id,
                security_id=security_id,
            )

        data = run_client_action(cred, _fetch)

        if data.get("error"):
            console.print(f"[red]{data['error']}[/red]")
            return

        # Build markdown
        geek_detail = data.get("geekDetailInfo", data)
        base_info = geek_detail.get("geekBaseInfo", geek_detail)

        name = base_info.get("name", base_info.get("geekName", "candidate"))
        gender_val = base_info.get("gender", 0)
        gender = "男" if gender_val == 1 else "女" if gender_val == 2 else ""
        degree = base_info.get("degreeCategory", base_info.get("degree", ""))
        work_year = base_info.get("workYearDesc", base_info.get("workYear", ""))
        age = base_info.get("ageDesc", base_info.get("age", ""))
        apply_status = base_info.get("applyStatusContent", base_info.get("applyStatus", ""))
        expect_position = base_info.get("expectPosition", "")
        expect_city = base_info.get("expectCity", "")
        expect_salary = base_info.get("expectSalary", base_info.get("salaryDesc", ""))

        lines: list[str] = []
        lines.append(f"# {name}")
        lines.append("")

        info_parts = [p for p in [gender, age, degree, work_year] if p]
        if info_parts:
            lines.append(" | ".join(info_parts))
            lines.append("")

        if apply_status:
            lines.append(f"**求职状态:** {apply_status}")
            lines.append("")

        expect_parts = [p for p in [expect_position, expect_city, expect_salary] if p]
        if expect_parts:
            lines.append("## 求职期望")
            lines.append("")
            lines.append(" | ".join(expect_parts))
            lines.append("")

        # Work experience
        work_exp = geek_detail.get("geekWorkExpList", base_info.get("workExpList", []))
        if work_exp:
            lines.append("## 工作经历")
            lines.append("")
            for w in work_exp:
                company = w.get("company", w.get("companyName", ""))
                position = w.get("positionName", w.get("position", ""))
                time_desc = w.get("timeDesc", w.get("workTime", ""))
                industry = w.get("industry", "")
                desc = w.get("description", w.get("workDesc", ""))
                header = f"### {company}"
                if industry:
                    header += f" ({industry})"
                lines.append(header)
                lines.append("")
                if time_desc:
                    lines.append(f"**{time_desc}** - {position}")
                elif position:
                    lines.append(f"**{position}**")
                lines.append("")
                if desc:
                    lines.append(desc)
                    lines.append("")

        # Education
        edu_exp = geek_detail.get("geekEduExpList", base_info.get("eduExpList", []))
        if edu_exp:
            lines.append("## 教育经历")
            lines.append("")
            for e in edu_exp:
                school = e.get("school", e.get("schoolName", ""))
                major_name = e.get("major", e.get("majorName", ""))
                degree_name = e.get("degree", e.get("degreeName", ""))
                time_desc = e.get("timeDesc", e.get("eduTime", ""))
                header = f"### {school}"
                if degree_name:
                    header += f" - {degree_name}"
                lines.append(header)
                lines.append("")
                parts = [p for p in [time_desc, major_name] if p]
                if parts:
                    lines.append(" | ".join(parts))
                    lines.append("")

        # Projects
        project_exp = geek_detail.get("geekProjectExpList", base_info.get("projectExpList", []))
        if project_exp:
            lines.append("## 项目经历")
            lines.append("")
            for p in project_exp:
                proj_name = p.get("projectName", p.get("name", ""))
                role = p.get("roleName", p.get("role", ""))
                time_desc = p.get("timeDesc", p.get("projectTime", ""))
                desc = p.get("description", p.get("projectDesc", ""))
                header = f"### {proj_name}"
                if role:
                    header += f" ({role})"
                lines.append(header)
                lines.append("")
                if time_desc:
                    lines.append(f"**{time_desc}**")
                    lines.append("")
                if desc:
                    lines.append(desc)
                    lines.append("")

        md_content = "\n".join(lines).rstrip() + "\n"

        # Write to file or stdout
        if output_file is None:
            safe_name = name.replace("/", "_").replace(" ", "_")
            output_file = f"{safe_name}_resume.md"

        if output_file == "-":
            click.echo(md_content)
        else:
            with open(output_file, "w", encoding="utf-8") as fh:
                fh.write(md_content)
            console.print(f"[green]简历已导出到 {output_file}[/green]")

    except BossApiError as exc:
        console.print(f"[red]导出失败: {exc}[/red]")
        raise SystemExit(1) from None


# ── recruiter job-close ─────────────────────────────────────────────


@recruiter.command("job-close")
@click.argument("encrypt_job_id")
@click.option("-y", "--yes", is_flag=True, help="跳过确认提示")
def recruiter_job_close(encrypt_job_id: str, yes: bool) -> None:
    """关闭/下线职位 (Take job offline)"""
    cred = require_auth()

    if not yes:
        confirm = click.confirm(f"确定关闭职位 {encrypt_job_id}?")
        if not confirm:
            console.print("[dim]已取消[/dim]")
            return

    try:
        result = run_client_action(cred, lambda c: c.boss_job_offline(encrypt_job_id))
        console.print(f"[green]职位已关闭: {encrypt_job_id}[/green]")
        if result:
            console.print(f"  [dim]{json.dumps(result, ensure_ascii=False)[:200]}[/dim]")
    except BossApiError as exc:
        msg = str(exc)
        console.print(f"[red]关闭职位失败: {msg}[/red]")
        if "缺少必要参数" in msg or "stoken" in msg.lower():
            console.print(
                "  [yellow]提示: 该操作可能需要浏览器端 __zp_stoken__ 验证。\n"
                "  请尝试在浏览器中操作, 或重新登录后重试: boss logout && boss login[/yellow]"
            )
        raise SystemExit(1) from None


# ── recruiter job-reopen ────────────────────────────────────────────


@recruiter.command("job-reopen")
@click.argument("encrypt_job_id")
@click.option("-y", "--yes", is_flag=True, help="跳过确认提示")
def recruiter_job_reopen(encrypt_job_id: str, yes: bool) -> None:
    """重新开启/上线职位 (Bring job online)"""
    cred = require_auth()

    if not yes:
        confirm = click.confirm(f"确定重新开启职位 {encrypt_job_id}?")
        if not confirm:
            console.print("[dim]已取消[/dim]")
            return

    try:
        result = run_client_action(cred, lambda c: c.boss_job_online(encrypt_job_id))
        console.print(f"[green]职位已开启: {encrypt_job_id}[/green]")
        if result:
            console.print(f"  [dim]{json.dumps(result, ensure_ascii=False)[:200]}[/dim]")
    except BossApiError as exc:
        msg = str(exc)
        console.print(f"[red]开启职位失败: {msg}[/red]")
        if "缺少必要参数" in msg or "stoken" in msg.lower():
            console.print(
                "  [yellow]提示: 该操作可能需要浏览器端 __zp_stoken__ 验证。\n"
                "  请尝试在浏览器中操作, 或重新登录后重试: boss logout && boss login[/yellow]"
            )
        raise SystemExit(1) from None


# ── Recruiter Chat Actions ──────────────────────────────────────────

_STOKEN_HINT = (
    "[yellow]\u26a0\ufe0f 此操作需要 __zp_stoken__ (由浏览器 JS 生成)。"
    "请先在浏览器登录后执行 boss login 补全 Cookie。[/yellow]"
)


def _chat_action_hint(exc: BossApiError) -> None:
    """Print an extra stoken recovery hint to stderr if the error looks
    like it was caused by a missing __zp_stoken__ cookie. Intended to be
    passed to ``handle_command(..., error_hint=...)`` so it runs AFTER the
    standard error is printed."""
    msg = str(exc)
    if "缺少必要参数" in msg or "stoken" in msg.lower() or "<" in msg[:5]:
        console.print(f"  {_STOKEN_HINT}")


def _resolve_friend_uid_and_job(cred, target: str) -> tuple[int, int, int]:
    """Resolve (uid, jobId, friendSource, securityId, name) from a friendId OR nickname.

    - numeric ``target`` is treated as a friendId directly;
    - otherwise it is matched by nickname through the recruiter index
      (refreshing the inbox first when no cached match is found).

    The matched friendId is then used to fetch the full detail so we can
    reliably get ``uid``, ``jobId``, ``friendSource``, ``securityId`` and
    ``name`` for the exchange request.  ``securityId`` is fetched live every
    time because BOSS rotates it between sessions.
    """
    friend_id: int | None = None
    cached: dict[str, Any] | None = None

    if target.isdigit():
        friend_id = int(target)
    else:
        from ..index_cache import find_recruiter, save_recruiter_index

        cached = find_recruiter(target)
        if not (cached and (cached.get("friendId") or cached.get("uid"))):
            details = run_client_action(cred, _load_recruiter_inbox)
            save_recruiter_index(details)
            cached = find_recruiter(target)
        if cached and (cached.get("friendId") or cached.get("uid")):
            friend_id = int(cached.get("friendId") or cached.get("uid"))

    if friend_id is None:
        console.print(f"[red]未找到昵称为「{target}」的候选人，请先运行 uv run boss recruiter inbox[/red]")
        raise SystemExit(1)

    # 详情必须实时拉取：exchange 需要最新 securityId（BOSS 会轮换）
    data = run_client_action(
        cred,
        lambda c: c.get_boss_friend_details([friend_id]),
    )
    friend_list = data.get("friendList", [])
    if not friend_list:
        console.print(f"[red]未找到 friendId={friend_id} 的候选人信息[/red]")
        raise SystemExit(1)
    friend = friend_list[0]
    uid = friend.get("uid", 0)
    job_id = friend.get("jobId", 0)
    friend_source = int(friend.get("friendSource", 0) or 0)
    security_id = friend.get("securityId", "") or ""
    name = friend.get("name", "") or ""
    if not uid:
        console.print(f"[red]无法获取候选人 uid (friendId={friend_id})[/red]")
        raise SystemExit(1)
    if not security_id:
        console.print(f"[red]无法获取候选人 securityId (friendId={friend_id})[/red]")
        raise SystemExit(1)
    return uid, job_id, friend_source, security_id, name


@recruiter.command("request-resume")
@click.argument("friend_id", type=str)
@click.option("-y", "--yes", is_flag=True, help="跳过确认提示")
@structured_output_options
def recruiter_request_resume(friend_id: str, yes: bool, as_json: bool, as_yaml: bool) -> None:
    """向候选人请求简历 (Request resume from candidate). FRIEND_ID 可为 friendId 或候选人昵称."""
    cred = require_auth()

    if not yes:
        console.print(f"[cyan]将向 {friend_id} 请求简历[/cyan]")
        confirm = click.confirm("确认请求?")
        if not confirm:
            console.print("[dim]已取消[/dim]")
            return

    uid, job_id, friend_source, security_id, name = _resolve_friend_uid_and_job(cred, friend_id)
    unique_id = f"{uid}-{friend_source}"

    def _action(c: BossClient) -> dict:
        # 简历交换 type=4（前端 exchangeObj.resume.type），参数无 name
        return c.boss_exchange_request(security_id=security_id, unique_id=unique_id, exchange_type=4)

    def _render(data: dict) -> None:
        console.print(f"[green]已向候选人请求简历 (friendId={friend_id}, uid={uid})[/green]")

    handle_command(
        cred, action=_action, render=_render,
        as_json=as_json, as_yaml=as_yaml,
        error_hint=_chat_action_hint,
    )


@recruiter.command("exchange-phone")
@click.argument("friend_id", type=str)
@click.option("-y", "--yes", is_flag=True, help="跳过确认提示")
@structured_output_options
def recruiter_exchange_phone(friend_id: str, yes: bool, as_json: bool, as_yaml: bool) -> None:
    """交换候选人手机号 (Exchange phone number with candidate). FRIEND_ID 可为 friendId 或候选人昵称."""
    cred = require_auth()

    if not yes:
        console.print(f"[cyan]将与 {friend_id} 交换手机号[/cyan]")
        confirm = click.confirm("确认交换?")
        if not confirm:
            console.print("[dim]已取消[/dim]")
            return

    uid, job_id, friend_source, security_id, name = _resolve_friend_uid_and_job(cred, friend_id)
    unique_id = f"{uid}-{friend_source}"

    def _action(c: BossClient) -> dict:
        return c.boss_exchange_request(security_id=security_id, unique_id=unique_id, exchange_type=1, name=name)

    def _render(data: dict) -> None:
        console.print(f"[green]已向候选人请求交换手机号 (friendId={friend_id}, uid={uid})[/green]")

    handle_command(
        cred, action=_action, render=_render,
        as_json=as_json, as_yaml=as_yaml,
        error_hint=_chat_action_hint,
    )


@recruiter.command("exchange-wechat")
@click.argument("friend_id", type=str)
@click.option("-y", "--yes", is_flag=True, help="跳过确认提示")
@structured_output_options
def recruiter_exchange_wechat(friend_id: str, yes: bool, as_json: bool, as_yaml: bool) -> None:
    """交换候选人微信 (Exchange WeChat with candidate). FRIEND_ID 可为 friendId 或候选人昵称."""
    cred = require_auth()

    if not yes:
        console.print(f"[cyan]将与 {friend_id} 交换微信[/cyan]")
        confirm = click.confirm("确认交换?")
        if not confirm:
            console.print("[dim]已取消[/dim]")
            return

    uid, job_id, friend_source, security_id, name = _resolve_friend_uid_and_job(cred, friend_id)
    unique_id = f"{uid}-{friend_source}"

    def _action(c: BossClient) -> dict:
        return c.boss_exchange_request(security_id=security_id, unique_id=unique_id, exchange_type=2, name=name)

    def _render(data: dict) -> None:
        console.print(f"[green]已向候选人请求交换微信 (friendId={friend_id}, uid={uid})[/green]")

    handle_command(
        cred, action=_action, render=_render,
        as_json=as_json, as_yaml=as_yaml,
        error_hint=_chat_action_hint,
    )


@recruiter.command("accept-exchange")
@click.argument("friend_id", type=str)
@click.option("--type", "etype", type=click.Choice(["wechat", "phone", "resume"]), default=None,
              help="指定同意类型；默认从对方发来的请求消息自动识别")
@click.option("-y", "--yes", is_flag=True, help="跳过确认提示")
@structured_output_options
def recruiter_accept_exchange(friend_id: str, etype: str, yes: bool, as_json: bool, as_yaml: bool) -> None:
    """同意候选人发起的交换请求 (Accept candidate's exchange request).

    BOSS 前端逆向: 收到交换请求时, 调 ``POST /wapi/zpchat/exchange/accept``
    参数 ``{securityId, mid, type}``, 其中 type 按请求类型映射
    (手机号=1, 微信=2, 简历=3)。本命令自动在聊天记录里定位「对方发起、
    待同意」的交换请求消息(``from.uid == 候选人uid`` 且文案含"请求与您交换")。
    """
    cred = require_auth()

    uid, job_id, friend_source, security_id, name = _resolve_friend_uid_and_job(cred, friend_id)

    type_map = {"wechat": 2, "phone": 1, "resume": 3}
    text_type_map = (
        (("交换微信",), 2, "微信"),
        (("交换联系方式", "交换手机号"), 1, "手机号"),
        (("交换简历",), 3, "简历"),
    )

    def _find_request(c: BossClient) -> dict:
        """在会话记录里找对方发起的待同意交换请求消息。"""
        history = c.get_boss_chat_history(gid=uid, count=50)
        messages = history.get("messages") or []
        for m in messages:
            frm = m.get("from")
            frm_uid = frm.get("uid") if isinstance(frm, dict) else m.get("fromUid")
            push = str(m.get("pushText") or "")
            if frm_uid != uid or "请求与您交换" not in push:
                continue
            mid = m.get("mid")
            if not mid:
                continue
            chosen = type_map.get(etype, 0)
            desc = etype
            for keywords, t, label in text_type_map:
                if any(k in push for k in keywords):
                    chosen, desc = t, label
                    break
            if not chosen:
                continue
            return {"mid": mid, "type": chosen, "desc": desc, "push": push}
        return {}

    def _find_verbal_request(c: BossClient) -> dict:
        """找对方口头提出的交换请求（普通文本消息, 如"我想和您交换微信"）。

        仅匹配对方发来、且明确包含交换诉求的文本, 排除系统交换卡片消息。
        """
        history = c.get_boss_chat_history(gid=uid, count=50)
        messages = history.get("messages") or []
        candidates = []
        for m in messages:
            frm = m.get("from")
            frm_uid = frm.get("uid") if isinstance(frm, dict) else m.get("fromUid")
            if frm_uid != uid:
                continue
            push = str(m.get("pushText") or "")
            body = m.get("body") or {}
            # 排除系统交换卡片(action)消息
            if isinstance(body, dict) and (body.get("type") == 4 or body.get("action")):
                continue
            if any(k in push for k in ("交换微信", "交换联系方式", "交换手机号", "交换个微信", "加个微信")):
                candidates.append((m.get("time") or 0, push, m.get("mid")))
        if not candidates:
            return {}
        # 取最近一条
        candidates.sort(key=lambda x: x[0])
        _, push, mid = candidates[-1]
        chosen, desc = type_map.get(etype, 0), etype
        for keywords, t, label in text_type_map:
            if any(k in push for k in keywords):
                chosen, desc = t, label
                break
        if not chosen:
            return {}
        return {"mid": mid, "type": chosen, "desc": desc, "push": push, "verbal": True}

    def _action(c: BossClient) -> dict:
        req = _find_request(c)
        if req:
            result = c.boss_exchange_accept(
                security_id=security_id, mid=req["mid"], exchange_type=req["type"],
            )
            return {"peer": {"name": name, "friendId": friend_id, "uid": uid}, "request": req, "mode": "accept", **result}
        # 无系统请求 → 兜底: 对方口头提出交换, 代为发起正式交换请求
        verbal = _find_verbal_request(c)
        if verbal:
            unique_id = f"{uid}-{friend_source}"
            result = c.boss_exchange_request(
                security_id=security_id, unique_id=unique_id, exchange_type=verbal["type"], name=name,
            )
            return {"peer": {"name": name, "friendId": friend_id, "uid": uid}, "request": verbal, "mode": "verbal", **result}
        raise BossApiError(f"未找到 {name or friend_id} 发起的待同意交换请求（可能已处理或不存在）")

    def _render(data: dict) -> None:
        req = data.get("request", {})
        mode = data.get("mode")
        if mode == "accept":
            console.print(
                f"[green]已同意 {name} 的交换{req.get('desc', '')}请求[/green] "
                f"(mid={req.get('mid')})"
            )
        else:
            console.print(
                f"[green]检测到 {name} 口头提出交换{req.get('desc', '')}, 已代为发起正式交换请求[/green] "
                f"等待对方在系统卡片上确认"
            )

    handle_command(
        cred, action=_action, render=_render,
        as_json=as_json, as_yaml=as_yaml,
        error_hint=_chat_action_hint,
    )


@recruiter.command("invite-interview")
@click.argument("encrypt_geek_id")
@click.option("--job", "encrypt_job_id", required=True, help="关联职位 encryptJobId")
@click.option("--address", default="", help="面试地点")
@click.option("--time", "start_time", default="", help="面试开始时间")
@click.option("--desc", "description", default="", help="面试说明")
@click.option("-y", "--yes", is_flag=True, help="跳过确认提示")
@structured_output_options
def recruiter_invite_interview(
    encrypt_geek_id: str, encrypt_job_id: str, address: str,
    start_time: str, description: str, yes: bool,
    as_json: bool, as_yaml: bool,
) -> None:
    """邀请候选人面试 (Invite candidate for interview)"""
    cred = require_auth()

    if not yes:
        console.print(f"[cyan]将邀请候选人面试: {encrypt_geek_id}[/cyan]")
        if address:
            console.print(f"  地点: {address}")
        if start_time:
            console.print(f"  时间: {start_time}")
        confirm = click.confirm("确认邀请?")
        if not confirm:
            console.print("[dim]已取消[/dim]")
            return

    # securityId is derived from the friend list; try to look it up
    security_id = ""
    try:
        friend_data = run_client_action(cred, lambda c: c.get_boss_friend_list())
        for f in friend_data.get("result", []):
            if f.get("encryptFriendId") == encrypt_geek_id:
                detail = run_client_action(
                    cred,
                    lambda c, fid=f["friendId"]: c.get_boss_friend_details([fid]),
                )
                for fd in detail.get("friendList", []):
                    security_id = fd.get("securityId", "")
                    break
                break
    except BossApiError:
        pass  # proceed without securityId; API may still accept it

    def _action(c: BossClient) -> dict:
        return c.boss_interview_invite(
            encrypt_geek_id=encrypt_geek_id,
            encrypt_job_id=encrypt_job_id,
            security_id=security_id,
            address=address,
            start_time=start_time,
            description=description,
        )

    def _render(data: dict) -> None:
        console.print(f"[green]已发送面试邀请 -> {encrypt_geek_id}[/green]")

    handle_command(
        cred, action=_action, render=_render,
        as_json=as_json, as_yaml=as_yaml,
        error_hint=_chat_action_hint,
    )


@recruiter.command("mark-unsuitable")
@click.argument("encrypt_geek_id")
@click.option("--job", "encrypt_job_id", required=True, help="关联职位 encryptJobId")
@click.option("-y", "--yes", is_flag=True, help="跳过确认提示")
@structured_output_options
def recruiter_mark_unsuitable(
    encrypt_geek_id: str, encrypt_job_id: str, yes: bool,
    as_json: bool, as_yaml: bool,
) -> None:
    """标记候选人不合适 (Mark candidate as unsuitable)"""
    cred = require_auth()

    if not yes:
        console.print(f"[cyan]将标记候选人为不合适: {encrypt_geek_id}[/cyan]")
        confirm = click.confirm("确认标记?")
        if not confirm:
            console.print("[dim]已取消[/dim]")
            return

    def _action(c: BossClient) -> dict:
        return c.boss_mark_unsuitable(
            encrypt_geek_id=encrypt_geek_id,
            encrypt_job_id=encrypt_job_id,
        )

    def _render(data: dict) -> None:
        console.print(f"[green]已标记候选人为不合适 -> {encrypt_geek_id}[/green]")

    handle_command(
        cred, action=_action, render=_render,
        as_json=as_json, as_yaml=as_yaml,
        error_hint=_chat_action_hint,
    )
