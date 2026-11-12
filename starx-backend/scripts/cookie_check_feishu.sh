#!/usr/bin/env bash
# 定时 Cookie 巡检 + 飞书通知（给 crontab 用；会传 --feishu）
# 本地自查请直接: python scripts/check_cookies.py  （不加 --feishu，不推飞书）
#
# 推荐合并入口每 2 小时: scripts/patrol_feishu.sh
# 单独跑:
#   0 */2 * * * /path/to/starx-backend/scripts/cookie_check_feishu.sh >> /path/to/starx-backend/var/log/cookie_check.log 2>&1
#
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
mkdir -p "$ROOT/var/log"

# shellcheck source=scripts/_feishu_python.sh
source "$ROOT/scripts/_feishu_python.sh"
_feishu_resolve_python || exit $?

# 只抽取飞书相关配置，避免 source 整份 .env 时因未引号值报错
if [[ -f "$ROOT/.env" ]]; then
  while IFS= read -r line || [[ -n "$line" ]]; do
    case "$line" in
      FEISHU_COOKIE_WEBHOOK=*|FEISHU_COOKIE_SECRET=*|FEISHU_SSL_VERIFY=*)
        key="${line%%=*}"
        val="${line#*=}"
        export "$key=$val"
        ;;
    esac
  done < "$ROOT/.env"
fi

export FEISHU_COOKIE_WEBHOOK="${FEISHU_COOKIE_WEBHOOK:-}"
export FEISHU_COOKIE_SECRET="${FEISHU_COOKIE_SECRET:-}"

if [[ -z "${FEISHU_COOKIE_WEBHOOK}" ]]; then
  echo "[$(date '+%F %T')] FEISHU_COOKIE_WEBHOOK 未配置，跳过飞书推送仍执行检查" >&2
fi

exec "$PYTHON" "$ROOT/scripts/check_cookies.py" --platform all --feishu
