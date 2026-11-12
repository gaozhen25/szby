#!/usr/bin/env bash
# 小红书扫码 / 手机号登录 → cookies/cookies.json（纯 HTTP，无浏览器）
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
exec python scripts/xhs_login_to_pool.py "$@"
