#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if ! command -v conda >/dev/null 2>&1; then
  echo "错误：未找到 conda。" >&2
  exit 1
fi

if ! conda run --no-capture-output -n starx python -c 'import browser_cookie3' >/dev/null 2>&1; then
  echo "错误：starx 环境缺少 browser-cookie3。请先执行：" >&2
  echo "conda run --no-capture-output -n starx pip install browser-cookie3" >&2
  exit 1
fi

cd "$SCRIPT_DIR"
exec conda run --no-capture-output -n starx python -m scripts.sync_browser_cookies "$@"
