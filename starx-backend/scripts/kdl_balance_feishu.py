#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""查询快代理 IP 余量并推送到飞书。

环境变量:
  FEISHU_KDL_WEBHOOK   飞书群机器人 Webhook
  FEISHU_KDL_SECRET    可选，签名密钥
  KDL_SECERT_ID / KDL_SIGNATURE

用法:
  python scripts/kdl_balance_feishu.py
  python scripts/kdl_balance_feishu.py --webhook 'https://open.feishu.cn/...'
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
from datetime import datetime, timedelta, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

try:
    from dotenv import load_dotenv

    load_dotenv(_ROOT / ".env")
except ImportError:
    pass

from app.services.mediaspider.vendor.proxy import (  # noqa: E402
    fetch_kuaidaili_ip_balance_sync,
)

_CN_TZ = timezone(timedelta(hours=8))


def _now() -> str:
    return datetime.now(_CN_TZ).strftime("%Y-%m-%d %H:%M:%S")


def _feishu_sign(secret: str) -> tuple[str, str]:
    timestamp = str(int(time.time()))
    string_to_sign = f"{timestamp}\n{secret}"
    digest = hmac.new(
        string_to_sign.encode("utf-8"),
        digestmod=hashlib.sha256,
    ).digest()
    return timestamp, base64.b64encode(digest).decode("utf-8")


def _feishu_ssl_context() -> ssl.SSLContext | None:
    raw = (os.environ.get("FEISHU_SSL_VERIFY") or "true").strip().lower()
    if raw in {"0", "false", "no", "off"}:
        return ssl._create_unverified_context()
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return None


def send_feishu(text: str, webhook: str, *, secret: str = "") -> None:
    webhook = (webhook or "").strip()
    if not webhook:
        raise ValueError("未配置飞书 Webhook（FEISHU_KDL_WEBHOOK / --webhook）")

    payload: dict = {
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
    except json.JSONDecodeError:
        data = {}
    if isinstance(data, dict) and data.get("code") not in (None, 0, "0"):
        raise RuntimeError(f"飞书推送失败: {raw[:300]}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="快代理 IP 余量推送飞书")
    parser.add_argument(
        "--webhook",
        default="",
        help="飞书 Webhook；默认读 FEISHU_KDL_WEBHOOK",
    )
    parser.add_argument(
        "--secret",
        default="",
        help="飞书签名密钥；默认读 FEISHU_KDL_SECRET",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只打印，不推送",
    )
    args = parser.parse_args(argv)

    webhook = (args.webhook or os.environ.get("FEISHU_KDL_WEBHOOK") or "").strip()
    secret = (args.secret or os.environ.get("FEISHU_KDL_SECRET") or "").strip()

    try:
        balance = fetch_kuaidaili_ip_balance_sync()
    except Exception as exc:  # noqa: BLE001
        text = f"快代理 IP 余量查询失败 {_now()}\n错误: {exc}"
        print(text, file=sys.stderr)
        if args.dry_run or not webhook:
            return 1
        try:
            send_feishu(text, webhook, secret=secret)
        except Exception as push_exc:  # noqa: BLE001
            print(f"飞书推送失败: {push_exc}", file=sys.stderr)
        return 1

    text = f"快代理 IP 余量 {_now()}\n剩余可提取: {balance}"
    print(text)
    if args.dry_run:
        return 0
    try:
        send_feishu(text, webhook, secret=secret)
    except Exception as exc:  # noqa: BLE001
        print(f"飞书推送失败: {exc}", file=sys.stderr)
        return 1
    print(f"[{_now()}] 已推送飞书", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
