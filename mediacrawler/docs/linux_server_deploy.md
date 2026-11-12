# Linux 服务器部署指南

> 适用：Ubuntu 22.04 / 24.04（amd64）。小红书 CDP 模式 + 可选 FastAPI 服务。  
> 开源版无官方 Docker，需本机安装 Google Chrome。

---

## 0. 部署架构选型

| 方案 | 服务器组件 | 适用 |
|------|------------|------|
| **A. 仅爬虫** | Chrome + Python | 定时 `./mc search`，结果写 `data/xhs/json/` |
| **B. 爬虫 + API** | Chrome + Python + uvicorn | 后端 `XhsBackendClient.live()` 实时爬 |
| **C. 仅 API/读数据** | 仅 Python | 爬虫在别的机器，本机只读 JSON（无需 Chrome） |

下文以 **方案 B** 为主（最常见），方案 A/C 见文末差异说明。

---

## 1. 服务器要求

| 项目 | 建议 |
|------|------|
| 系统 | Ubuntu 22.04+ LTS |
| CPU | 2 核+ |
| 内存 | 4GB+（Chrome 单实例约 0.5～1GB） |
| 磁盘 | 20GB+ |
| 网络 | 可访问小红书；**不要**把 CDP 9222 端口暴露公网 |

---

## 2. 一键安装依赖（Ubuntu）

在项目根目录执行（需 sudo）：

```bash
chmod +x scripts/linux_server_setup.sh
sudo ./scripts/linux_server_setup.sh
```

脚本会安装：系统库、Google Chrome、uv、Node.js 20，并执行 `uv sync`。

---

## 3. 手动安装（逐步）

### 3.1 系统依赖 + Chrome

```bash
sudo apt update
sudo apt install -y git curl ca-certificates fonts-liberation \
  libasound2t64 libatk-bridge2.0-0t64 libatk1.0-0t64 libcups2t64 \
  libdrm2 libgbm1 libgtk-3-0t64 libnspr4 libnss3 libx11-xcb1 \
  libxcomposite1 libxdamage1 libxfixes3 libxrandr2 xdg-utils wget gpg

wget -q -O - https://dl.google.com/linux/linux_signing_key.pub | \
  sudo gpg --dearmor -o /usr/share/keyrings/google-chrome.gpg
echo "deb [arch=amd64 signed-by=/usr/share/keyrings/google-chrome.gpg] http://dl.google.com/linux/chrome/deb/ stable main" | \
  sudo tee /etc/apt/sources.list.d/google-chrome.list
sudo apt update
sudo apt install -y google-chrome-stable
google-chrome-stable --version
```

### 3.2 uv + 项目依赖

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
source "$HOME/.local/bin/env"   # 或 source ~/.bashrc

cd /opt
sudo git clone https://github.com/NanmiCoder/MediaCrawler.git
sudo chown -R "$USER:$USER" MediaCrawler
cd MediaCrawler

uv sync
uv run playwright install chromium
```

### 3.3 Node.js（爬抖音/知乎时需要）

```bash
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt install -y nodejs
node -v
```

---

## 4. 生产配置

编辑 `config/base_config.py`（或通过命令行参数覆盖）：

```python
PLATFORM = "xhs"
LOGIN_TYPE = "cookie"          # 服务器推荐 cookie，见第 5 节
HEADLESS = True
CDP_HEADLESS = True
ENABLE_CDP_MODE = True
SAVE_LOGIN_STATE = True
SAVE_DATA_OPTION = "json"      # SDK / mc 默认写 JSON
CUSTOM_BROWSER_PATH = "/usr/bin/google-chrome-stable"
MAX_CONCURRENCY_NUM = 1
```

---

## 5. 登录态（必做）

Linux 无桌面，**不要用 qrcode**（除非自研飞书推码）。任选其一：

### 方式 A：Cookie 文件（服务器最推荐）

不要把 Cookie 写进命令行（会进 bash 历史）。落到 `secrets/`（已 gitignore）：

```bash
cd /opt/MediaCrawler
mkdir -p secrets && chmod 700 secrets

# 本机浏览器登录后 F12 → Network → 复制 Cookie，写入对应文件：
#   secrets/xhs.cookies    ← 小红书（需含 web_session）
#   secrets/dy.cookies     ← 抖音搜索
#   secrets/dyhot.cookies  ← 热点宝（从 https://douhot.douyin.com 复制）
nano secrets/dyhot.cookies
chmod 600 secrets/*.cookies

# 从示例生成 Cookie 文件后粘贴真实内容
cp secrets/xhs.cookies.example secrets/xhs.cookies
cp secrets/dy.cookies.example secrets/dy.cookies
cp secrets/dyhot.cookies.example secrets/dyhot.cookies
# nano secrets/*.cookies  → 删掉 # 注释行与 REPLACE_ME，粘贴整段 Cookie
chmod 600 secrets/*.cookies

# 日常运行（自动读 secrets/<平台>.cookies，可用 --max-notes 控条数）
uv run python scripts/run_with_cookies.py dyhot --max-notes 50
uv run python scripts/run_with_cookies.py dyhot --max-notes 100 --search-top-n 5 --notes-per-keyword 10
uv run python scripts/run_with_cookies.py dy --keywords 世界杯 --max-notes 30
uv run python scripts/run_with_cookies.py xhs --keywords 猫咪 --max-notes 40 --max-comments 20

# 定时任务示例（每天 8:00）
# crontab -e
# 0 8 * * * cd /opt/MediaCrawler && /home/deploy/.local/bin/uv run python scripts/run_with_cookies.py dyhot --max-notes 100 >> /var/log/dyhot.log 2>&1
```

条数参数说明：

| 参数 | xhs / dy | dyhot |
|------|----------|--------|
| `--max-notes N` | 搜索笔记/视频数 | 热点榜最大条数 |
| `--max-comments N` | 每条一级评论上限（会自动开评论） | 跟搜时每视频评论上限 |
| `--search-top-n N` | — | 跟搜关键词个数（0=整榜） |
| `--notes-per-keyword N` | — | 每个热词搜几条视频 |


**替换 Cookie**：本机重新登录 → 复制新 Cookie → 覆盖同名文件即可，命令不用改：

```bash
# 本机 scp 覆盖
scp ./dyhot.cookies user@server:/opt/MediaCrawler/secrets/dyhot.cookies

# 或服务器上直接粘贴
nano /opt/MediaCrawler/secrets/dyhot.cookies
```

失效时通常表现为榜单/搜索返回空或跳登录页；换文件后再跑同一条命令。

也可用 `--cookies-file /path/to.cookies` 指定路径。首次注入成功后，`browser_data/cdp_*_user_data_dir` 会保留登录态；Cookie 过期后以文件覆盖为准重新注入即可。

### 方式 B：从本机拷贝登录目录

本机（Mac）爬通一次后，打包上传到服务器项目根目录：

```bash
# 本机
tar czf browser_data_xhs.tgz browser_data/cdp_xhs_user_data_dir browser_data/cdp_xhs_storage_state.json

# 服务器
cd /opt/MediaCrawler
tar xzf browser_data_xhs.tgz
```

---

## 6. 验证爬虫

```bash
cd /opt/MediaCrawler

# 方式 1：SDK 快捷命令
chmod +x mc
./mc search 测试 -n 5

# 方式 2：demo 脚本
uv run python scripts/direct_dict_demo.py 测试 5

# 方式 3：main.py
uv run main.py --platform xhs --type search --lt cookie \
  --keywords "测试" --save_data_option json --headless true
```

成功标志：

- 日志无 `Browser failed to start`
- 存在 `data/xhs/json/测试_YYYY-MM-DD.json`
- 或终端打印 `note_count > 0`

---

## 7. 启动 API 服务

### 7.1 前台试跑

```bash
cd /opt/MediaCrawler
uv run uvicorn api.main:app --host 127.0.0.1 --port 8080
```

另开终端测试：

```bash
curl http://127.0.0.1:8080/api/health
# {"status":"ok"}

curl "http://127.0.0.1:8080/api/data/search-json?platform=xhs&keyword=测试"
```

### 7.2 systemd 常驻

```bash
sudo cp deploy/mediacrawler-api.service.example /etc/systemd/system/mediacrawler-api.service
# 编辑 User、WorkingDirectory、uv 路径
sudo nano /etc/systemd/system/mediacrawler-api.service

sudo systemctl daemon-reload
sudo systemctl enable mediacrawler-api
sudo systemctl start mediacrawler-api
sudo systemctl status mediacrawler-api
journalctl -u mediacrawler-api -f
```

### 7.3 Nginx 反代（可选，仅内网/加鉴权后对外）

```nginx
server {
    listen 80;
    server_name crawler.internal.example.com;

    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_read_timeout 600s;   # 实时爬取可能较慢
        proxy_connect_timeout 60s;
    }
}
```

---

## 8. 后端接入

### 读已落盘 JSON（爬虫与 API 同机）

```python
from sdk import XhsBackendClient

client = XhsBackendClient.archive.local(json_dir="/opt/MediaCrawler/data/xhs/json")
result = client.search("测试")
```

### 实时爬（调服务器 API）

```python
client = XhsBackendClient.live("http://127.0.0.1:8080", timeout=600)
result = client.search("测试", max_notes_count=20)
```

### 同进程直传 dict（爬虫与后端同一 Python 进程）

见 [xhs_direct_dict_integration.md](./xhs_direct_dict_integration.md)。

---

## 9. 定时任务（方案 A）

```bash
crontab -e
```

```cron
# 每天 8:00 爬取关键词「美食」
0 8 * * * cd /opt/MediaCrawler && /home/deploy/.local/bin/uv run ./mc search 美食 -n 20 >> /var/log/mediacrawler.log 2>&1
```

---

## 10. 目录与备份

| 路径 | 说明 |
|------|------|
| `browser_data/cdp_xhs_user_data_dir/` | Chrome 用户目录 / 登录态 |
| `browser_data/cdp_xhs_storage_state.json` | Cookie 备份 |
| `data/xhs/json/` | 爬取结果 JSON |
| `/var/log/mediacrawler.log` | 自建 cron 日志 |

定期备份 `browser_data/` 和 `data/`。

---

## 11. 故障排查

| 现象 | 处理 |
|------|------|
| `Browser failed to start within 60 seconds` | 检查 `google-chrome-stable --version`；设置 `CUSTOM_BROWSER_PATH` |
| `No available browser found` | 未安装 Chrome 或路径不对 |
| 反复登录 | 用 Cookie 或重新拷贝 `browser_data/` |
| 无头被风控 | 换 Cookie；降低频率；本机登录后拷登录态 |
| API 502 / timeout | 加大 `proxy_read_timeout`；`live()` 设 `timeout=600` |
| 内存 OOM | 增大 swap；保持 `MAX_CONCURRENCY_NUM=1` |

---

## 12. 方案差异速查

**方案 A（仅爬虫）**：完成第 2～6、9 节即可，不需要第 7 节。

**方案 C（仅读 JSON）**：

```bash
uv sync   # 无需 Chrome
uv run uvicorn api.main:app --host 127.0.0.1 --port 8080
# 仅使用 GET /api/data/search-json，不要调 POST /api/data/crawl/*
```

从别的机器 rsync JSON：

```bash
rsync -avz deploy@爬虫机:/opt/MediaCrawler/data/xhs/json/ /opt/MediaCrawler/data/xhs/json/
```

---

## 13. 部署检查清单

- [ ] Chrome 已安装且 `google-chrome-stable --version` 正常
- [ ] `uv sync` 成功
- [ ] `HEADLESS=True` / `CDP_HEADLESS=True`
- [ ] 登录态已配置（Cookie 或 browser_data）
- [ ] `./mc search 测试 -n 3` 成功
- [ ] （可选）systemd API 服务 running
- [ ] （可选）防火墙未暴露 9222；8080 仅内网或反代
- [ ] `browser_data/`、`data/` 已纳入备份
