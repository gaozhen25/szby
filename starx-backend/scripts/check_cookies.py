#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""轮询检查 cookies/cookies.json，可选推送到飞书群机器人。

小红书：GET /api/sns/web/v2/user/me
抖音：profile/self

环境变量:
  FEISHU_COOKIE_WEBHOOK   群机器人 Webhook URL
  FEISHU_COOKIE_SECRET    可选，机器人签名校验密钥

用法:
  python scripts/check_cookies.py                  # 检查并删失效 cookie，不推飞书
  python scripts/check_cookies.py --feishu          # 检查、删失效、推飞书
  python scripts/check_cookies.py --keep-invalid    # 只检查不删除
  python scripts/check_cookies.py --platform xhs --feishu
  # 定时推送请用 scripts/cookie_check_feishu.sh（crontab 已配 --feishu）
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import os
import ssl
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

try:
    from dotenv import load_dotenv

    load_dotenv(BACKEND_ROOT / ".env")
except ImportError:
    pass

from app.services.mediaspider.http_platforms.common.cookies import (  # noqa: E402
    load_accounts,
    remove_platform_cookies,
)

# 明确鉴权失效（可安全删除）；网络/代理错误不删
_AUTH_INVALID_MARKERS = (
    "登录已过期",
    "登录失效",
    "未登录",
    "请登录",
    "guest or empty user_id",
    "profile/self empty",
    '"code": -100',
    '"code":-100',
)

# 服务器多为 UTC；飞书通知按中国时区展示
_CN_TZ = timezone(timedelta(hours=8))


def _now() -> str:
    return datetime.now(_CN_TZ).strftime("%Y-%m-%d %H:%M:%S")


def _mask(cookie: str) -> str:
    jar: dict[str, str] = {}
    for part in cookie.split(";"):
        part = part.strip()
        if "=" in part:
            k, v = part.split("=", 1)
            jar[k.strip()] = v.strip()
    token = jar.get("web_session") or jar.get("sessionid") or jar.get("a1") or ""
    if len(token) <= 8:
        return token or "(empty)"
    return f"{token[:4]}…{token[-4:]}"


def _is_auth_invalid(row: dict[str, Any]) -> bool:
    """是否为登录凭证失效（可从池中删除）。网络/代理错误返回 False。"""
    if row.get("ok"):
        return False
    if row.get("raw_code") in (-100, "-100"):
        return True
    err = str(row.get("error") or "")
    return any(marker in err for marker in _AUTH_INVALID_MARKERS)


def check_xhs(cookie: str) -> dict[str, Any]:
    from app.services.mediaspider.http_platforms.common.proxy import (
        resolve_requests_proxies,
    )
    from app.services.mediaspider.http_platforms.xhs import XhsClient

    client = XhsClient(cookie=cookie, proxies=resolve_requests_proxies())
    try:
        me = client.user_me() or {}
    except Exception as exc:
        err = str(exc)
        row: dict[str, Any] = {"ok": False, "error": err}
        if '"code": -100' in err or '"code":-100' in err or "登录已过期" in err:
            row["raw_code"] = -100
        return row
    data = me.get("data") if isinstance(me, dict) else None
    if data is None and isinstance(me, dict):
        data = me
    if not isinstance(data, dict):
        return {"ok": False, "error": f"unexpected response: {me!r}"[:200]}
    if me.get("success") is False or me.get("code") not in (None, 0, "0"):
        return {
            "ok": False,
            "error": me.get("msg") or f"code={me.get('code')}",
            "raw_code": me.get("code"),
        }
    user_id = data.get("user_id") or data.get("userid") or ""
    guest = data.get("guest")
    if not user_id or guest is True:
        return {"ok": False, "error": "guest or empty user_id", "guest": guest}
    return {
        "ok": True,
        "user_id": user_id,
        "nickname": data.get("nickname") or "",
        "red_id": data.get("red_id") or data.get("redId") or "",
    }


def check_dy(cookie: str) -> dict[str, Any]:
    from app.services.mediaspider.http_platforms.common.proxy import (
        resolve_requests_proxies,
    )
    from app.services.mediaspider.http_platforms.douyin import DouyinClient

    client = DouyinClient(cookie=cookie, proxies=resolve_requests_proxies())
    try:
        user = client.get_self_profile()
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
    if not user:
        return {"ok": False, "error": "profile/self empty"}
    return {
        "ok": True,
        "sec_uid": user.get("sec_uid") or "",
        "nickname": user.get("nickname") or "",
        "unique_id": user.get("unique_id") or user.get("short_id") or "",
    }


def check_one(platform: str, name: str, cookie: str) -> dict[str, Any]:
    started = time.perf_counter()
    if platform == "xhs":
        result = check_xhs(cookie)
    elif platform == "dy":
        result = check_dy(cookie)
    else:
        result = {"ok": False, "error": f"unsupported platform: {platform}"}
    result.update(
        {
            "platform": platform,
            "account": name,
            "cookie_id": _mask(cookie),
            "checked_at": _now(),
            "elapsed_ms": int((time.perf_counter() - started) * 1000),
            "_cookie": cookie,
        }
    )
    return result


def run_once(platforms: list[str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for platform in platforms:
        try:
            accounts = load_accounts(platform)
        except Exception as exc:
            rows.append(
                {
                    "platform": platform,
                    "account": "-",
                    "ok": False,
                    "error": str(exc),
                    "checked_at": _now(),
                }
            )
            continue
        for acc in accounts:
            rows.append(check_one(platform, acc.name, acc.cookie))
    return rows


def purge_invalid_cookies(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """从 cookies.json 删除明确鉴权失效的条目，返回已删除摘要。"""
    by_platform: dict[str, list[str]] = {}
    victims: list[dict[str, Any]] = []
    for row in rows:
        if not _is_auth_invalid(row):
            continue
        cookie = row.get("_cookie")
        platform = row.get("platform")
        if not cookie or not platform or platform == "-":
            continue
        by_platform.setdefault(str(platform), []).append(str(cookie))
        victims.append(row)

    removed_summary: list[dict[str, Any]] = []
    for platform, cookies in by_platform.items():
        path, n = remove_platform_cookies(platform, cookies)
        if n:
            removed_summary.append(
                {
                    "platform": platform,
                    "removed": n,
                    "path": str(path),
                    "accounts": [
                        r.get("account")
                        for r in victims
                        if r.get("platform") == platform
                    ],
                }
            )
    return removed_summary


def format_report(
    rows: list[dict[str, Any]],
    *,
    proxy_balance: int | None = None,
    proxy_balance_error: str = "",
    purged: list[dict[str, Any]] | None = None,
) -> str:
    ok_n = sum(1 for r in rows if r.get("ok"))
    lines = [
        f"Cookie 巡检 {_now()}",
        f"结果: {ok_n}/{len(rows)} 有效",
    ]
    if proxy_balance is not None:
        lines.append(f"快代理 IP 余量: {proxy_balance}")
    elif proxy_balance_error:
        lines.append(f"快代理 IP 余量: 查询失败（{proxy_balance_error}）")
    lines.append("")
    for r in rows:
        status = "✅" if r.get("ok") else "❌"
        detail = (
            r.get("nickname")
            or r.get("red_id")
            or r.get("unique_id")
            or r.get("error")
            or ""
        )
        if len(str(detail)) > 80:
            detail = str(detail)[:77] + "..."
        lines.append(
            f"{status} {r.get('platform')}:{r.get('account')} "
            f"{r.get('cookie_id') or '-'}  {detail}"
        )
    fail_n = len(rows) - ok_n
    if fail_n:
        lines.append("")
        lines.append(f"⚠️ 有 {fail_n} 条失效，请及时补号")
    else:
        lines.append("")
        lines.append("全部可用")
    if purged:
        lines.append("")
        for item in purged:
            accounts = ",".join(str(a) for a in item.get("accounts") or [])
            lines.append(
                f"🗑 已从池中删除 {item['platform']} "
                f"{item['removed']} 条失效 cookie（{accounts}）"
            )
    return "\n".join(lines)


def _feishu_sign(secret: str) -> tuple[str, str]:
    timestamp = str(int(time.time()))
    string_to_sign = f"{timestamp}\n{secret}"
    digest = hmac.new(
        string_to_sign.encode("utf-8"),
        digestmod=hashlib.sha256,
    ).digest()
    return timestamp, base64.b64encode(digest).decode("utf-8")


def _feishu_ssl_context() -> ssl.SSLContext | None:
    """FEISHU_SSL_VERIFY=false 时关闭校验证书（本机中间人/自签代理）。"""
    raw = (os.environ.get("FEISHU_SSL_VERIFY") or "true").strip().lower()
    if raw in {"0", "false", "no", "off"}:
        return ssl._create_unverified_context()
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return None


def send_feishu(
    text: str,
    webhook: str,
    *,
    secret: str = "",
) -> None:
    webhook = (webhook or "").strip()
    if not webhook:
        raise ValueError("未配置飞书 Webhook（FEISHU_COOKIE_WEBHOOK / --webhook）")

    payload: dict[str, Any] = {
        "msg_type": "text",
        "content": {"text": text},
    }
    secret = (secret or "").strip()
    if secret:
        timestamp, sign = _feishu_sign(secret)
        payload["timestamp"] = timestamp
        payload["sign"] = sign

    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        webhook,
        data=body,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    context = _feishu_ssl_context()
    try:
        with urllib.request.urlopen(req, timeout=20, context=context) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"飞书推送 HTTP {exc.code}: {raw[:300]}") from exc
    except Exception as exc:
        raise RuntimeError(f"飞书推送失败: {exc}") from exc

    try:
        data = json.loads(raw) if raw else {}
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"飞书推送响应非 JSON: {raw[:300]}") from exc
    if not isinstance(data, dict):
        raise RuntimeError(f"飞书推送响应异常: {raw[:300]}")
    # 自定义机器人成功: {"StatusCode":0,"StatusMessage":"success"} 或 {"code":0}
    status_code = data.get("StatusCode", data.get("code"))
    if status_code not in (0, "0", None):
        raise RuntimeError(f"飞书推送失败: {raw[:300]}")
    # StatusCode 缺失但明确失败
    if str(data.get("msg") or "").lower() in {"error", "failed"}:
        raise RuntimeError(f"飞书推送失败: {raw[:300]}")


def print_report(rows: list[dict[str, Any]]) -> None:
    ok_n = sum(1 for r in rows if r.get("ok"))
    print(f"[{_now()}] cookie 检查 {ok_n}/{len(rows)} 有效")
    for r in rows:
        status = "OK" if r.get("ok") else "FAIL"
        detail = (
            r.get("nickname")
            or r.get("red_id")
            or r.get("unique_id")
            or r.get("error")
            or ""
        )
        print(
            f"  [{status}] {r.get('platform')}:{r.get('account')} "
            f"{r.get('cookie_id')}  {detail}"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--platform",
        choices=("xhs", "dy", "all"),
        default="all",
        help="检查平台，默认 all",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=0,
        help="轮询间隔秒数；例如 21600=每6小时。0 表示只查一次",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="只检查一次（有 --interval 时默认会循环）",
    )
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    parser.add_argument(
        "--feishu",
        action="store_true",
        help="推送到飞书；不加此参数只本地打印（即便 .env 已配 Webhook）",
    )
    parser.add_argument(
        "--webhook",
        default="",
        help="飞书 Webhook（需同时加 --feishu）；默认读 FEISHU_COOKIE_WEBHOOK",
    )
    parser.add_argument(
        "--feishu-secret",
        default="",
        help="飞书机器人签名密钥；默认读 FEISHU_COOKIE_SECRET",
    )
    parser.add_argument(
        "--feishu-only-fail",
        action="store_true",
        help="仅在有失效 cookie 时推送飞书（仍需 --feishu）",
    )
    parser.add_argument(
        "--keep-invalid",
        action="store_true",
        help="保留失效 cookie 不删除（默认会从 cookies.json 删掉鉴权失效项）",
    )
    args = parser.parse_args()

    platforms = ["xhs", "dy"] if args.platform == "all" else [args.platform]
    loop = args.interval and args.interval > 0 and not args.once
    # 只有显式 --feishu 才推送；.env 里的 Webhook 只提供地址，不自动开启推送
    want_feishu = bool(args.feishu)
    webhook = (args.webhook or os.environ.get("FEISHU_COOKIE_WEBHOOK") or "").strip()
    secret = (
        args.feishu_secret or os.environ.get("FEISHU_COOKIE_SECRET") or ""
    ).strip()

    while True:
        rows = run_once(platforms)
        purged: list[dict[str, Any]] = []
        if not args.keep_invalid:
            purged = purge_invalid_cookies(rows)
            for item in purged:
                accounts = ",".join(str(a) for a in item.get("accounts") or [])
                print(
                    f"[{_now()}] 已删除 {item['platform']} "
                    f"{item['removed']} 条失效 cookie（{accounts}）→ {item['path']}",
                    file=sys.stderr,
                )

        proxy_balance: int | None = None
        proxy_balance_error = ""
        # 仅在 --feishu / --json 时查余量，避免普通本地巡检多余请求
        if want_feishu or args.json:
            try:
                from app.services.mediaspider.vendor.proxy import (  # noqa: WPS433
                    fetch_kuaidaili_ip_balance_sync,
                )

                proxy_balance = fetch_kuaidaili_ip_balance_sync()
            except Exception as exc:  # noqa: BLE001
                proxy_balance_error = str(exc)[:120]

        if args.json:
            payload = {
                "cookies": [
                    {k: v for k, v in r.items() if k != "_cookie"} for r in rows
                ],
                "purged": purged,
                "kdl_ip_balance": proxy_balance,
                "kdl_ip_balance_error": proxy_balance_error or None,
            }
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print_report(rows)
            if want_feishu:
                if proxy_balance is not None:
                    print(f"快代理 IP 余量: {proxy_balance}")
                elif proxy_balance_error:
                    print(
                        f"快代理 IP 余量查询失败: {proxy_balance_error}",
                        file=sys.stderr,
                    )

        if want_feishu:
            ok_n = sum(1 for r in rows if r.get("ok"))
            should_send = (not args.feishu_only_fail) or (ok_n < len(rows))
            if should_send:
                try:
                    send_feishu(
                        format_report(
                            rows,
                            proxy_balance=proxy_balance,
                            proxy_balance_error=proxy_balance_error,
                            purged=purged,
                        ),
                        webhook,
                        secret=secret,
                    )
                    print(f"[{_now()}] 已推送飞书", file=sys.stderr)
                except Exception as exc:
                    print(f"[{_now()}] 飞书推送失败: {exc}", file=sys.stderr)

        if not loop:
            return 0 if all(r.get("ok") for r in rows) else 1
        try:
            time.sleep(float(args.interval))
        except KeyboardInterrupt:
            print("\n已停止轮询", file=sys.stderr)
            return 0


if __name__ == "__main__":
    raise SystemExit(main())
