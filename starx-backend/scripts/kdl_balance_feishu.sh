#!/usr/bin/env bash
# 定时推送快代理 IP 余量到飞书
#
# 推荐合并入口每 2 小时: scripts/patrol_feishu.sh
# 单独跑:
#   0 */2 * * * /path/to/starx-backend/scripts/kdl_balance_feishu.sh >> /path/to/starx-backend/var/log/kdl_balance.log 2>&1
#
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
mkdir -p "$ROOT/var/log"

# shellcheck source=scripts/_feishu_python.sh
source "$ROOT/scripts/_feishu_python.sh"
_feishu_resolve_python || exit $?

# 只抽取相关配置，避免 source 整份 .env 时因未引号值报错
if [[ -f "$ROOT/.env" ]]; then
  while IFS= read -r line || [[ -n "$line" ]]; do
    case "$line" in
      FEISHU_KDL_WEBHOOK=*|FEISHU_KDL_SECRET=*|FEISHU_SSL_VERIFY=*|KDL_SECERT_ID=*|KDL_SIGNATURE=*|KDL_PROXY_REUSE_SECONDS=*|STARX_KDL_SECERT_ID=*|STARX_KDL_SIGNATURE=*|STARX_KDL_PROXY_REUSE_SECONDS=*)
        key="${line%%=*}"
        val="${line#*=}"
        export "$key=$val"
        ;;
    esac
  done < "$ROOT/.env"
fi

export FEISHU_KDL_WEBHOOK="${FEISHU_KDL_WEBHOOK:-}"
export FEISHU_KDL_SECRET="${FEISHU_KDL_SECRET:-}"

if [[ -z "${FEISHU_KDL_WEBHOOK}" ]]; then
  echo "[$(date '+%F %T')] FEISHU_KDL_WEBHOOK 未配置" >&2
  exit 1
fi

exec "$PYTHON" "$ROOT/scripts/kdl_balance_feishu.py"
