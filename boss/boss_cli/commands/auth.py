"""Authentication commands: login, logout, status, me."""

from __future__ import annotations

import json
import logging

import click
from rich.panel import Panel

from ._common import (
    console,
    handle_command,
    require_auth,
    structured_output_options,
)

logger = logging.getLogger(__name__)


@click.command()
@click.option("--force", is_flag=True, help="即使已有 __zp_stoken__ 也强制重新生成")
def refresh_stoken(force: bool) -> None:
    """用无头浏览器(Playwright)基于当前会话补全 __zp_stoken__。

    使用前提: 已扫码登录(boss login)且会话 cookie 有效(wt2/wbg/zp_at 都在)，
    但缺少 __zp_stoken__（该值由 Boss 直聘前端 JS 生成，QR 扫码流程拿不到）。
    本命令启动无头 Playwright 浏览器访问 zhipin.com，让 JS 生成
    __zp_stoken__ 后回写凭证（与 exchange 命令共用同一套 gen_stoken）。
    """
    from ..auth import Credential, get_credential, save_credential
    from .._stoken_gen import gen_stoken

    cred = get_credential()
    if not cred or not cred.has_session_cookies:
        console.print("[red]未登录或会话不完整，请先执行 boss login[/red]")
        raise SystemExit(1)

    if "__zp_stoken__" in cred.cookies and not force:
        console.print("[green]已存在 __zp_stoken__，无需补全（--force 可强制重新生成）[/green]")
        return

    console.print("[cyan]正在通过无头浏览器访问 zhipin.com 生成 __zp_stoken__（约 5-15s，不弹窗）...[/cyan]")
    stoken = gen_stoken(cookies=dict(cred.cookies), headless=True)

    if stoken:
        merged = {**cred.cookies, "__zp_stoken__": stoken}
        save_credential(Credential(cookies=merged))
        console.print(f"[green]✅ __zp_stoken__ 补全成功！凭证共 {len(merged)} cookies[/green]")
        console.print("[dim]接下来可正常使用 recruiter exchange / search 等 stoken 敏感接口[/dim]")
    else:
        console.print("[yellow]⚠️ 浏览器未能生成 __zp_stoken__（可能触发反爬检测）[/yellow]")
        console.print("[yellow]备选方案: 用 Chrome 登录同一账号后执行 boss login --cookie-source chrome[/yellow]")
        raise SystemExit(1)


@click.command()
@click.option("--qrcode", is_flag=True, help="扫码登录（默认就是扫码，可省略）")
@click.option("--cookie-source", default=None, help="改为从浏览器提取 Cookie（chrome/firefox/edge 等）")
def login(qrcode: bool, cookie_source: str | None) -> None:
    """扫码登录。任意求职账号用 Boss 直聘 APP 扫一下即可使用沟通和私信。"""
    from ..auth import clear_credential, qr_login, verify_credential
    import asyncio

    def _finalize_login(cred, *, from_qr: bool = False) -> None:
        authenticated, message = verify_credential(cred, force_refresh=True)
        if authenticated:
            console.print(f"[green]✅ 登录成功！[/green] ({len(cred.cookies)} cookies)")
            console.print("[dim]接下来: uv run boss chat  ·  boss listen  ·  boss reply 1 \"正文\"[/dim]")
            if from_qr and "__zp_stoken__" not in cred.cookies:
                console.print(
                    "[dim]搜索/推荐若提示「环境异常」，用 Chrome 登录网站后执行 "
                    "boss login --cookie-source chrome[/dim]"
                )
            return
        # QR session can still chat even if search health check fails.
        if from_qr and cred.has_session_cookies:
            console.print(f"[green]✅ 扫码登录成功！[/green] ({len(cred.cookies)} cookies)")
            console.print("[dim]沟通/私信可用: uv run boss chat  ·  boss listen  ·  boss reply 1 \"正文\"[/dim]")
            if message:
                console.print(f"[dim]{message}[/dim]")
            return
        clear_credential()
        console.print("[red]❌ 登录失败：凭证未通过校验[/red]")
        if message:
            console.print(f"[dim]{message}[/dim]")
        raise SystemExit(1)

    def _run_qr() -> None:
        import asyncio

        from ..auth import Credential, qr_login, save_credential
        from .._stoken_gen import gen_stoken

        # 1) 纯 HTTP 扫码登录（不依赖任何本地浏览器/Chrome）
        cred = asyncio.run(qr_login())

        # 2) 扫码流程拿不到 __zp_stoken__（由前端 JS 生成）→ 用无头 Playwright 补全
        if "__zp_stoken__" not in cred.cookies:
            console.print("[cyan]🔧 正在通过无头浏览器补全 __zp_stoken__（约 5-15s，不弹窗）...[/cyan]")
            try:
                stoken = gen_stoken(cookies=dict(cred.cookies), headless=True)
            except Exception as exc:
                logger.warning("无头补全 __zp_stoken__ 异常: %s", exc)
                stoken = ""
            if stoken:
                merged = {**cred.cookies, "__zp_stoken__": stoken}
                cred = Credential(cookies=merged)
                save_credential(cred)
                console.print("[green]✅ __zp_stoken__ 补全成功！所有接口可正常使用[/green]")
            else:
                console.print("[yellow]⚠️ 无头浏览器未能生成 __zp_stoken__（可能触发反爬检测）[/yellow]")
                console.print("[dim]沟通/私信不受影响；搜索等 stoken 敏感接口稍后可再执行 boss refresh-stoken[/dim]")
        _finalize_login(cred, from_qr=True)

    if cookie_source and not qrcode:
        from ..auth import (
            Credential,
            extract_browser_credential,
            _diagnose_extraction_issues,
            save_credential,
        )
        from .._stoken_gen import gen_stoken

        cred, diagnostics = extract_browser_credential(
            cookie_source=cookie_source,
            allow_missing_stoken=True,
        )
        if cred:
            # Chrome 基础会话有效但缺 __zp_stoken__（前端 JS 动态生成）→
            # 直接无头补全，跳过扫码登录。
            if "__zp_stoken__" not in cred.cookies:
                console.print("[cyan]🔧 Chrome 会话有效，正在用无头浏览器补全 __zp_stoken__（约 5-15s，不弹窗）...[/cyan]")
                try:
                    stoken = gen_stoken(cookies=dict(cred.cookies), headless=True)
                except Exception as exc:
                    logger.warning("无头补全 __zp_stoken__ 异常: %s", exc)
                    stoken = ""
                if stoken:
                    cred = Credential(cookies={**cred.cookies, "__zp_stoken__": stoken})
                    console.print("[green]✅ __zp_stoken__ 补全成功！所有接口可正常使用[/green]")
                else:
                    console.print("[yellow]⚠️ 无头浏览器未能生成 __zp_stoken__，改用扫码登录...[/yellow]")
                    _run_qr()
                    return
            save_credential(cred)
            _finalize_login(cred)
            return
        hint = _diagnose_extraction_issues(diagnostics)
        if hint:
            console.print("[yellow]⚠️  Cookie 提取失败:[/yellow]")
            for line in hint.splitlines():
                console.print(f"  [dim]{line}[/dim]")
            console.print()
        console.print("[yellow]改为扫码登录...[/yellow]")
        _run_qr()
        return

    _run_qr()


@click.command()
def logout() -> None:
    """清除已保存的登录凭证"""
    from ..auth import clear_credential
    clear_credential()
    console.print("[green]✅ 已退出登录[/green]")


@click.command()
@structured_output_options
def status(as_json: bool, as_yaml: bool) -> None:
    """查看当前登录状态"""
    from ..auth import get_credential, verify_credential_details
    cred = get_credential()
    if cred:
        cookie_names = sorted(cred.cookies.keys())
        health = verify_credential_details(cred)
        authenticated = health["authenticated"]
        message = health.get("reason")
        data = {
            "credential_present": True,
            "cookie_count": len(cred.cookies),
            "cookies": cookie_names,
            **health,
        }
        if as_json:
            click.echo(json.dumps(data, indent=2, ensure_ascii=False))
        elif as_yaml:
            try:
                import yaml
                click.echo(yaml.dump(data, allow_unicode=True))
            except ImportError:
                click.echo(json.dumps(data, indent=2, ensure_ascii=False))
        else:
            n = len(cred.cookies)
            keys = ", ".join(cookie_names[:5])
            extra = f" (+{n - 5} more)" if n > 5 else ""
            if authenticated:
                console.print(f"[green]✅ 已登录[/green] ({n} cookies)")
                console.print(f"  [dim]{keys}{extra}[/dim]")
            else:
                console.print(f"[yellow]⚠️  本地存在凭证，但登录态无效[/yellow] ({n} cookies)")
                console.print(f"  [dim]{keys}{extra}[/dim]")
            console.print(
                "  [dim]"
                f"chat={'ok' if health.get('chat_authenticated') else 'fail'} · "
                f"search={'ok' if health['search_authenticated'] else 'fail'} · "
                f"recommend={'ok' if health['recommend_authenticated'] else 'fail'}"
                "[/dim]"
            )
            if message:
                console.print(f"  [dim]{message}[/dim]")
    else:
        if as_json:
            click.echo(json.dumps({"authenticated": False, "credential_present": False}))
        elif as_yaml:
            data = {"authenticated": False, "credential_present": False}
            try:
                import yaml
                click.echo(yaml.dump(data, allow_unicode=True))
            except ImportError:
                click.echo(json.dumps(data, indent=2, ensure_ascii=False))
        else:
            console.print("[yellow]⚠️  未登录[/yellow]，使用 [bold]boss login[/bold] 扫码登录")


@click.command()
@structured_output_options
def me(as_json: bool, as_yaml: bool) -> None:
    """查看个人资料和求职期望"""
    cred = require_auth()

    def _render(info: dict) -> None:
        name = info.get("name", info.get("nickName", "-"))
        age = info.get("age", "-")
        degree = info.get("degreeCategory", "-")
        account = info.get("account", "-")
        gender = "男" if info.get("gender") == 1 else "女" if info.get("gender") == 2 else "-"

        panel = Panel(
            f"[bold]{name}[/bold]  {gender}  {age}\n"
            f"学历: {degree}\n"
            f"账号: {account}",
            title="👤 个人资料",
            border_style="cyan",
        )
        console.print(panel)

    handle_command(
        cred,
        action=lambda c: c.get_resume_baseinfo(),
        render=_render,
        as_json=as_json,
        as_yaml=as_yaml,
    )
