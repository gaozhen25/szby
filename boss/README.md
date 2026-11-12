# boss-cli

多平台私信与招聘工具 CLI：**BOSS 直聘**、**抖音私信**、**小红书私信**，支持终端命令与本地网页沟通。

本地开发：

```bash
uv sync
uv run playwright install chromium   # 抖音 / 小红书扫码登录需要
uv run boss <命令>
```

更完整的命令说明见 [COMMANDS.md](./COMMANDS.md)。

---

## 功能一览

### BOSS 直聘

| 能力 | 说明 |
|------|------|
| 求职端 | 扫码/浏览器 Cookie 登录，搜职位、推荐、打招呼、MQTT 收发私信 |
| 招聘端 | 搜牛人、简历、职位管理、求简历/换微信电话、约面试 |
| 网页沟通 | `boss recruiter web` → http://127.0.0.1:8765/（可自动招呼+换微信） |

收发技术：MQTT over WSS。

### 抖音私信

| 能力 | 说明 |
|------|------|
| 多账号 | `douyin/cookies.json` + `im_cred.json`，`accounts` / `use` 切号 |
| 登录 | `boss douyin grab-ticket --qr`（推荐，一次写入 cookie + ticket） |
| 终端 | inbox / messages / reply / dump |
| 网页 | `boss douyin web` → http://127.0.0.1:8766/（可自动回复） |

收发技术：frontier-im WebSocket 收信；发信需 ticket。

### 小红书私信

| 能力 | 说明 |
|------|------|
| 多账号 | `xhs/cookies.json`，`accounts` / `use` 切号 |
| 登录 | `boss xhs login`（Playwright 有界面扫码） |
| 终端 | `im chats` / `dump` / `send` / `poll` / `listen` |
| 网页 | `boss xhs web` → http://127.0.0.1:8767/（可自动回复） |

收发技术：IM WebSocket + `xhshow` 签 HTTP。

### 本地网页端口

| 服务 | 地址 |
|------|------|
| BOSS 招聘沟通 | http://127.0.0.1:8765/ |
| 抖音私信 | http://127.0.0.1:8766/ |
| 小红书私信 | http://127.0.0.1:8767/ |

结束：对应终端 `Ctrl+C`。

---

## 快速开始

```bash
# 依赖
uv sync
uv run playwright install chromium

# ─── BOSS ───
boss login
boss status
boss search "Python" --city 杭州
boss recruiter web                  # 招聘号登录后

# ─── 抖音 ───
boss douyin grab-ticket --qr
boss douyin accounts
boss douyin web                     # 默认自动回复，关闭加 --no-auto-reply

# ─── 小红书 ───
boss xhs login
boss xhs accounts
boss xhs web                        # 默认自动回复，关闭加 --no-auto-reply
```

凭证默认写在项目根目录（已 `.gitignore`）：

- BOSS：`credential.json`
- 抖音：`douyin/`
- 小红书：`xhs/`

---

## 常用命令

### BOSS 求职

```bash
boss login / status / logout / me
boss search "golang" --city 杭州 --salary 20-30K
boss show 3
boss recommend
boss greet <securityId>
boss batch-greet "Python" --city 杭州 -n 5 --dry-run
boss chat / messages 1 / reply 1 "您好"
boss listen                         # MQTT 持续收信
```

### BOSS 招聘

```bash
boss recruiter jobs
boss recruiter search "golang" --city 深圳
boss recruiter recommend --job <jobId>
boss recruiter inbox / messages 1 / reply 1 "..."
boss recruiter web                  # 网页沟通（默认自动换微信，可用 --no-auto-wechat）
boss recruiter listen
boss recruiter request-resume / exchange-wechat / exchange-phone ...
```

### 抖音

```bash
boss douyin --account 账号名 <子命令>
boss douyin grab-ticket --qr [--name 备注]
boss douyin accounts / use 账号名 / status
boss douyin web [--port 8766] [--no-auto-reply]
boss douyin inbox / messages 1 / reply 1 "你好"
```

### 小红书

```bash
boss xhs --account 账号名 <子命令>
boss xhs login [--name 备注]
boss xhs accounts / use 账号名 / status
boss xhs web [--port 8767] [--no-auto-reply]
boss xhs im chats
boss xhs im send --to 对方昵称 --text "你好"
boss xhs im dump / poll / listen
```

---

## 目录结构（核心）

```text
boss_cli/
├── cli.py                 # 入口
├── mqtt_chat.py           # BOSS MQTT 私信
├── webchat/               # BOSS 招聘网页沟通
├── douyin/ + douyin_web/  # 抖音 IM + 网页
├── xhs/ + xhs_web/        # 小红书 IM + 网页
└── commands/              # auth / search / recruiter / douyin / xhs ...
```

---

## 开发

```bash
uv sync
uv run pytest tests/ -v
uv run ruff check .
```

可选依赖：`uv sync --extra yaml` / `--extra dev`。

---

## 说明

- 本工具通过逆向公开接口实现，仅供个人学习与自用账号管理，请遵守各平台服务条款。
- Agent 结构化输出见 [SCHEMA.md](./SCHEMA.md)；命令速查见 [COMMANDS.md](./COMMANDS.md)。

## License

Apache-2.0
