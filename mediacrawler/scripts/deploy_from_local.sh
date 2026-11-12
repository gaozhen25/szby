#!/usr/bin/env bash
# 从本机 (Mac/Linux) 同步代码到远程 Linux 并执行部署
#
# 用法:
#   export DEPLOY_HOST=root@1.2.3.4
#   export DEPLOY_PATH=/opt/MediaCrawler
#   ./scripts/deploy_from_local.sh
#
# 可选:
#   DEPLOY_WITH_API=1     远程安装 systemd API
#   DEPLOY_PACK_LOGIN=1   打包本机 browser_data 一并上传（默认开启）
#   XHS_COOKIES='...'     传给远程验证（不写进文件）

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "${PROJECT_ROOT}"

DEPLOY_HOST="${DEPLOY_HOST:-}"
DEPLOY_PATH="${DEPLOY_PATH:-/opt/MediaCrawler}"
DEPLOY_WITH_API="${DEPLOY_WITH_API:-0}"
DEPLOY_PACK_LOGIN="${DEPLOY_PACK_LOGIN:-1}"
RSYNC_EXCLUDE=(
  --exclude '.git'
  --exclude '__pycache__'
  --exclude '.venv'
  --exclude 'data/'
  --exclude '.DS_Store'
  --exclude 'browser_data/cdp_dy_user_data_dir'
)

log() { echo "[deploy-from-local] $*"; }

if [[ -z "${DEPLOY_HOST}" ]]; then
  echo "错误: 请设置 DEPLOY_HOST，例如:"
  echo "  export DEPLOY_HOST=ubuntu@your-server-ip"
  echo "  ./scripts/deploy_from_local.sh"
  exit 1
fi

log "目标: ${DEPLOY_HOST}:${DEPLOY_PATH}"

if [[ "${DEPLOY_PACK_LOGIN}" -eq 1 ]] && [[ -d browser_data/cdp_xhs_user_data_dir ]]; then
  log "打包本机小红书登录态..."
  tar czf "${PROJECT_ROOT}/browser_data_login.tar.gz" \
    -C "${PROJECT_ROOT}" \
    browser_data/cdp_xhs_user_data_dir \
    browser_data/cdp_xhs_storage_state.json 2>/dev/null || \
  tar czf "${PROJECT_ROOT}/browser_data_login.tar.gz" \
    -C "${PROJECT_ROOT}" browser_data/cdp_xhs_user_data_dir
  log "  -> browser_data_login.tar.gz"
else
  log "跳过登录态打包 (无 cdp_xhs_user_data_dir 或 DEPLOY_PACK_LOGIN=0)"
fi

log "同步代码到服务器..."
ssh "${DEPLOY_HOST}" "sudo mkdir -p '${DEPLOY_PATH}' && sudo chown -R \$(whoami):\$(whoami) '${DEPLOY_PATH}'"
rsync -avz --delete "${RSYNC_EXCLUDE[@]}" \
  "${PROJECT_ROOT}/" "${DEPLOY_HOST}:${DEPLOY_PATH}/"

if [[ -f browser_data_login.tar.gz ]]; then
  rsync -avz browser_data_login.tar.gz "${DEPLOY_HOST}:${DEPLOY_PATH}/"
fi

REMOTE_ENV=""
if [[ -n "${XHS_COOKIES:-}" ]]; then
  REMOTE_ENV="export XHS_COOKIES=$(printf %q "${XHS_COOKIES}") && "
fi

API_FLAG=""
if [[ "${DEPLOY_WITH_API}" -eq 1 ]]; then
  API_FLAG="--with-api"
fi

log "远程执行 linux_server_deploy.sh ..."
ssh -t "${DEPLOY_HOST}" "cd '${DEPLOY_PATH}' && chmod +x scripts/*.sh && ${REMOTE_ENV} ./scripts/linux_server_deploy.sh ${API_FLAG}"

log "完成。远程 API: ssh ${DEPLOY_HOST} curl -s http://127.0.0.1:8080/api/health"
