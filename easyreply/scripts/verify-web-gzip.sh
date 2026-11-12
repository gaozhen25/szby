#!/bin/sh
# 验证 Web 部署是否启用 gzip（首包未压缩时首访极慢）
set -e

BASE="${1:-http://127.0.0.1:8765}"
INDEX="$BASE/index.html"

entry=$(curl -fsS "$INDEX" | sed -n 's/.*src="\(\/_expo\/static\/js\/web\/entry-[^"]*\.js\)".*/\1/p' | head -1)
if [ -z "$entry" ]; then
  echo "[verify-web-gzip] FAIL: cannot find entry script in index.html"
  exit 1
fi

url="$BASE$entry"
headers=$(curl -fsSI -H 'Accept-Encoding: gzip' "$url")
encoding=$(printf '%s\n' "$headers" | tr -d '\r' | awk -F': ' 'tolower($1)=="content-encoding" {print $2; exit}')
length=$(printf '%s\n' "$headers" | tr -d '\r' | awk -F': ' 'tolower($1)=="content-length" {print $2; exit}')

echo "[verify-web-gzip] entry: $entry"
echo "[verify-web-gzip] Content-Length: ${length:-unknown}"
echo "[verify-web-gzip] Content-Encoding: ${encoding:-none}"

if [ "$encoding" = "gzip" ] && [ -n "$length" ] && [ "$length" -lt 1500000 ]; then
  echo "[verify-web-gzip] OK (entry gzip ${length} bytes)"
  exit 0
fi

if [ -n "$length" ] && [ "$length" -gt 3000000 ]; then
  echo "[verify-web-gzip] FAIL: entry.js 未压缩 (~${length} bytes)，请检查 nginx gzip / gzip_static"
  exit 1
fi

echo "[verify-web-gzip] WARN: 无法确认 gzip，请人工检查 Network 面板"
exit 1
