#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""查询快代理私密代理订单剩余 IP 提取额度。

用法:
  python scripts/kdl_ip_balance.py
"""

from __future__ import annotations

import sys
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


def main() -> int:
    try:
        balance = fetch_kuaidaili_ip_balance_sync()
    except Exception as exc:  # noqa: BLE001
        print(f"查询失败: {exc}", file=sys.stderr)
        return 1
    print(balance)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
