#!/bin/sh
# Web 静态资源发布后处理：首屏 loading 样式 + gzip 预压缩（配合 nginx gzip_static）
set -e

DIST="${1:-dist}"
INDEX_HTML="$DIST/index.html"

if [ ! -f "$INDEX_HTML" ]; then
  echo "[postbuild-web] skip: $INDEX_HTML not found"
  exit 0
fi

node "$(dirname "$0")/postbuild-web-html.js" "$DIST"

find "$DIST" -type f \( -name '*.js' -o -name '*.css' \) ! -name '*.gz' -size +512c -print0 \
  | while IFS= read -r -d '' file; do
    gzip -k -9 -f "$file"
  done

entry_js=$(find "$DIST/_expo/static/js/web" -name 'entry-*.js' ! -name '*.gz' 2>/dev/null | head -1)
common_js=$(find "$DIST/_expo/static/js/web" -name '__common-*.js' ! -name '*.gz' 2>/dev/null | head -1)
if [ -n "$entry_js" ] && [ -f "$entry_js" ]; then
  raw_kb=$(du -k "$entry_js" | awk '{print $1}')
  gz_file="${entry_js}.gz"
  if [ -f "$gz_file" ]; then
    gz_kb=$(du -k "$gz_file" | awk '{print $1}')
    echo "[postbuild-web] entry: ${raw_kb}KB raw → ${gz_kb}KB gzip"
  else
    echo "[postbuild-web] WARN: entry gzip missing: $gz_file"
  fi
fi
if [ -n "$common_js" ] && [ -f "$common_js" ]; then
  common_raw_kb=$(du -k "$common_js" | awk '{print $1}')
  common_gz_file="${common_js}.gz"
  if [ -f "$common_gz_file" ]; then
    common_gz_kb=$(du -k "$common_gz_file" | awk '{print $1}')
    echo "[postbuild-web] __common: ${common_raw_kb}KB raw → ${common_gz_kb}KB gzip（index.html 首屏同步加载 entry + __common）"
    if [ -n "$gz_kb" ] && [ -n "$common_gz_kb" ]; then
      total_gz=$((gz_kb + common_gz_kb))
      echo "[postbuild-web] 首屏 JS 合计 gzip ≈ ${total_gz}KB（路由页另按需加载 async chunk）"
    fi
  fi
fi
if [ -n "$entry_js" ] && [ -f "$entry_js" ]; then
  if [ -f "${entry_js}.gz" ]; then
    echo "[postbuild-web] 部署后须启用 nginx gzip_static，否则首访仍下载 ${raw_kb}KB entry（未含 __common）"
  fi
fi

echo "[postbuild-web] 发版后请执行: sh scripts/verify-web-gzip.sh https://你的域名"
echo "[postbuild-web] done"
