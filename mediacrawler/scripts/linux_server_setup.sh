#!/usr/bin/env bash
# MediaCrawler Linux 服务器依赖安装脚本（Ubuntu 22.04/24.04 amd64）
# 用法: sudo ./scripts/linux_server_setup.sh
# 在项目根目录执行；安装 Chrome、uv、Node.js 并 uv sync

set -euo pipefail

if [[ "${EUID:-$(id -u)}" -ne 0 ]]; then
  echo "请使用 sudo 运行: sudo $0"
  exit 1
fi

DEPLOY_USER="${SUDO_USER:-$USER}"
PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

echo "==> [1/5] 安装系统依赖..."
apt-get update -qq
apt-get install -y -qq \
  git curl ca-certificates wget gpg \
  fonts-liberation libasound2t64 libatk-bridge2.0-0t64 libatk1.0-0t64 \
  libcups2t64 libdrm2 libgbm1 libgtk-3-0t64 libnspr4 libnss3 \
  libx11-xcb1 libxcomposite1 libxdamage1 libxfixes3 libxrandr2 xdg-utils \
  2>/dev/null || apt-get install -y -qq \
  git curl ca-certificates wget gpg fonts-liberation \
  libasound2 libatk-bridge2.0-0 libatk1.0-0 libcups2 libdrm2 libgbm1 \
  libgtk-3-0 libnspr4 libnss3 libx11-xcb1 libxcomposite1 libxdamage1 \
  libxfixes3 libxrandr2 xdg-utils

echo "==> [2/5] 安装 Google Chrome..."
if ! command -v google-chrome-stable >/dev/null 2>&1; then
  wget -q -O - https://dl.google.com/linux/linux_signing_key.pub | \
    gpg --dearmor -o /usr/share/keyrings/google-chrome.gpg
  echo "deb [arch=amd64 signed-by=/usr/share/keyrings/google-chrome.gpg] http://dl.google.com/linux/chrome/deb/ stable main" \
    > /etc/apt/sources.list.d/google-chrome.list
  apt-get update -qq
  apt-get install -y -qq google-chrome-stable
fi
google-chrome-stable --version

echo "==> [3/5] 安装 Node.js 20（抖音/知乎平台需要）..."
if ! command -v node >/dev/null 2>&1; then
  curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
  apt-get install -y -qq nodejs
fi
node -v

echo "==> [4/5] 为 ${DEPLOY_USER} 安装 uv..."
UV_BIN="/home/${DEPLOY_USER}/.local/bin/uv"
if [[ ! -x "${UV_BIN}" ]]; then
  sudo -u "${DEPLOY_USER}" bash -c 'curl -LsSf https://astral.sh/uv/install.sh | sh'
fi

echo "==> [5/5] 同步 Python 依赖 (uv sync)..."
sudo -u "${DEPLOY_USER}" bash -c "
  cd '${PROJECT_ROOT}'
  export PATH=\"/home/${DEPLOY_USER}/.local/bin:\$PATH\"
  uv sync
  uv run playwright install chromium
"

echo ""
echo "=========================================="
echo "  安装完成"
echo "=========================================="
echo "项目目录: ${PROJECT_ROOT}"
echo ""
echo "下一步:"
echo "  1. 编辑 config/base_config.py"
echo "     HEADLESS=True, CDP_HEADLESS=True"
echo "     CUSTOM_BROWSER_PATH=/usr/bin/google-chrome-stable"
echo "     LOGIN_TYPE=cookie"
echo ""
echo "  2. 配置登录态（Cookie 或拷贝 browser_data/）"
echo "     见 docs/linux_server_deploy.md 第 5 节"
echo ""
echo "  3. 验证:"
echo "     cd ${PROJECT_ROOT}"
echo "     ./mc search 测试 -n 3"
echo ""
echo "  4. 启动 API:"
echo "     uv run uvicorn api.main:app --host 127.0.0.1 --port 8080"
echo "=========================================="
