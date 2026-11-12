#!/usr/bin/env bash
# 打包本机小红书登录态，供上传到 Linux 服务器
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
OUT="${ROOT}/browser_data_login.tar.gz"
FILES=()
[[ -d browser_data/cdp_xhs_user_data_dir ]] && FILES+=("browser_data/cdp_xhs_user_data_dir")
[[ -f browser_data/cdp_xhs_storage_state.json ]] && FILES+=("browser_data/cdp_xhs_storage_state.json")
if [[ ${#FILES[@]} -eq 0 ]]; then
  echo "未找到 browser_data/cdp_xhs_* ，请先在本地扫码登录一次"
  exit 1
fi
tar czf "$OUT" "${FILES[@]}"
echo "已生成: $OUT"
echo "上传到服务器后: tar xzf browser_data_login.tar.gz"
