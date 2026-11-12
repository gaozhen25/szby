#!/usr/bin/env bash
# Cookie 巡检 + 快代理 IP 余量 → 飞书（合并入口，给 crontab 用）
#
# 每 2 小时整点（本机时区）:
#   0 */2 * * * /Users/gzbytech.tech/spider/starx-backend/scripts/patrol_feishu.sh >> /Users/gzbytech.tech/spider/starx-backend/var/log/patrol_feishu.log 2>&1
#
# 服务器示例:
#   0 */2 * * * /home/ubuntu/projects/starx-backend/scripts/patrol_feishu.sh >> /home/ubuntu/projects/starx-backend/var/log/patrol_feishu.log 2>&1
#
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
mkdir -p "$ROOT/var/log"

echo "[$(date '+%F %T')] patrol start"

set +e
"$ROOT/scripts/cookie_check_feishu.sh"
cookie_rc=$?
"$ROOT/scripts/kdl_balance_feishu.sh"
kdl_rc=$?
set -e

echo "[$(date '+%F %T')] patrol done cookie_rc=${cookie_rc} kdl_rc=${kdl_rc}"

if [[ "$cookie_rc" -ne 0 || "$kdl_rc" -ne 0 ]]; then
  exit 1
fi
