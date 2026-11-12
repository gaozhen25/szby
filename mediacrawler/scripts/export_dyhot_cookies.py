#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""登录抖音热点宝，导出 Cookie 到 secrets/dyhot.cookies.json（有头 CDP）。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from export_cookies_common import main

if __name__ == "__main__":
    raise SystemExit(main("dyhot"))
