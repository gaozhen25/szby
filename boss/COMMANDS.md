# Boss CLI 常用运行命令

本地开发默认在项目根目录用：

```bash
uv run boss <命令>
```

若已 `uv tool install kabi-boss-cli`，可直接：

```bash
boss <命令>
```

下文统一写成 `boss …`。

---

## 一、BOSS 直聘 · 账号

| 命令 | 说明 |
|------|------|
| `boss status` | 查看登录态 |
| `boss status --json` | JSON 输出 |
| `boss login` | APP 扫码登录（求职/招聘账号均可） |
| `boss login --cookie-source chrome` | 从浏览器抽 cookie（利于搜索） |
| `boss logout` | 清除本地凭证 |
| `boss me` | 个人资料 / 求职期望 |

凭证文件一般在项目或用户目录的 `credential.json`（以 `boss status` 提示为准）。

---

## 二、BOSS 直聘 · 求职端

### 搜职位 / 浏览

```bash
boss search "Python" --city 北京 --salary 20-30K
boss search "golang" --city 杭州 --industry 互联网 -p 2
boss show 3                          # 上次搜索结果第 3 条详情
boss detail <securityId>
boss recommend -p 1
boss history
boss cities
boss export "Python" -n 50 -o jobs.csv
```

### 打招呼 / 投递

```bash
boss greet <securityId>
boss batch-greet "Python" --city 杭州 -n 5 --dry-run   # 只预览
boss batch-greet "Python" --city 杭州 -n 5 -y          # 实际发送
```

### 沟通 / 私信

```bash
uv run python -m boss_cli._stoken_gen stoken生成测试
boss chat                            # 沟通过的 Boss 列表
boss messages 1                      # 第 1 个会话消息
boss messages 1 --all -o chat.json
boss reply 1 "您好，我对这个职位很感兴趣"
boss listen                          # MQTT 持续收信，Ctrl+C 结束
boss listen --json-lines
```

### 个人中心

```bash
boss applied -p 1
boss interviews
```

---

## 三、BOSS 直聘 · 招聘端（`boss recruiter`）

需用**招聘者**账号扫码登录（`boss logout && boss login`）。

### 网页版沟通（最常用）

```bash
boss recruiter web                   # http://127.0.0.1:8765/（默认开启自动招呼+交换微信）
boss recruiter web --port 8765 --no-open
boss recruiter web --no-auto-wechat  # 关闭自动回复
boss recruiter web --auto-wechat-text "我们通过平台交换下联系方式，方便后续沟通"
```

开启后的流程（每会话只走一遍；每步随机等待 5–8 秒）：
1. 对方发来新消息 → 回复「还在看工作吗？方便聊聊吗？」
2. 对方再回任意内容 → 回复「我们通过平台交换下联系方式，方便后续沟通」并发起交换微信
3. 之后该会话不再自动发消息（状态保存在 `recruiter_auto_wechat.json`）

### 职位 / 候选人
uv run boss recruiter exchange-wechat "吴先生" -y
```bash
boss recruiter jobs
boss recruiter job-close <jobId>
boss recruiter job-reopen <jobId>
boss recruiter search "Java" --city 上海 -p 1
boss recruiter recommend --job <encryptJobId> -p 1
boss recruiter geek <encryptGeekId>
boss recruiter resume <encryptGeekId>
boss recruiter resume-download <encryptGeekId>
boss recruiter greet <…>
boss recruiter batch-view …          # 批量查看（触发「被查看」）
boss recruiter export … -o candidates.csv
```

### 沟通 / 私信

```bash
boss recruiter inbox
boss recruiter messages 1 --all
boss recruiter chat 1
boss recruiter reply 1 "您好，方便聊聊吗？"
boss recruiter listen
boss recruiter export-messages -n 20 -o batch.json
```

### 其它动作

```bash
boss recruiter exchange-phone …
boss recruiter exchange-wechat …
boss recruiter invite-interview …
boss recruiter request-resume …
boss recruiter mark-unsuitable …
boss recruiter labels
```

---

## 四、抖音私信（`boss douyin`）

凭据目录：`douyin/cookies.json`、`douyin/im_cred.json`（多账号 `accounts[]`）。

全局指定账号：

```bash
boss douyin --account 顾清寒 <子命令>
boss douyin --account 9277 <子命令>
```

### 账号管理

```bash
boss douyin accounts                 # 列表 + 当前 active + 发信是否就绪
boss douyin use 顾清寒                 # 切换当前账号
boss douyin use 9277
boss douyin status                   # 检查 cookie 是否可用
```

### 登录 / 追加账号 / ticket

推荐与 spider `dy_im_grab_ticket.py --qr` 相同：**同一次扫码同时追加 cookie + ticket**。

```bash
# 推荐：扫码追加（不覆盖其它账号）
boss douyin grab-ticket --qr
boss douyin grab-ticket --qr --name 新账号名

# 登录 / 加号（浏览器扫码，同样追加 cookie+ticket）
boss douyin login
boss douyin add-account
boss douyin add-account --name 小号

# 仅注入已有 cookie 抓 ticket（常失败，不推荐）
boss douyin grab-ticket --headed

# 手动写 cookie / 从 spider 导入 ticket
boss douyin set-cookie "sessionid=…; …" --name xxx
boss douyin import-cred
boss douyin import-cred --from ~/spider/js/cookies/dy_im_cred.json
```

依赖：有界面 Chromium（`uv sync --extra browser && uv run playwright install chromium`）。

### 网页版私信（最常用）

```bash
boss douyin web                      # 当前账号，http://127.0.0.1:8766/（默认开启自动回复）
boss douyin web --port 8766 --no-open
boss douyin web --no-auto-reply      # 关闭自动回复
```

网页版默认自动回复流程（每会话只走一遍；收到消息后随机等待 5–8 秒再发）：
1. 对方发来任意消息（文字/图片等）→ 回复「你好，是要了解私信聚合吗」
2. 对方再回任意内容 → 回复「+🌍180******」
3. 之后该会话不再自动发消息（状态保存在 `douyin/auto_reply_state.json`）

**新账号收不到私信 / 不自动回复？**
1. 必须先 `boss douyin grab-ticket --qr` 扫码，写入 **cookie + uid + ticket**（只 login 不够）
2. 启动时用 `--account 昵称` 指定账号，确认终端里 printed 的 uid 正确
3. 未互关陌生人会话可能没有头像昵称，侧栏会显示「用户xxxx」——这是正常的，不影响收信和自动回复
4. 改代码后需重启 `boss douyin web` 进程

**两个账号同时跑**（不同端口）：

```bash
# 终端 1
boss douyin --account 顾清寒 web --port 8766

# 终端 2
boss douyin --account 9277 web --port 8767
```

- 顾清寒 → http://127.0.0.1:8766/  
- 9277 → http://127.0.0.1:8767/  

发信需要对应账号在 `im_cred.json` 里有完整 ticket（`grab-ticket --qr`）。

### 终端收件箱 / 发信

```bash
boss douyin inbox
boss douyin inbox --limit 30
boss douyin messages 1               # inbox 第 1 个会话
boss douyin messages 1 --limit 40
boss douyin reply 1 "你好"
boss douyin dump 1 -o conv.json
```

---

## 五、小红书私信（`boss xhs`）

凭据目录：`xhs/cookies.json`（多账号 `accounts[]`）。发信依赖 `xhshow` 签名 + WebSocket。

指定账号：

```bash
boss xhs --account 账号名 <子命令>
```

### 账号 / 登录

```bash
boss xhs accounts                    # 列表 + 当前 active
boss xhs use 账号名                    # 切换当前账号
boss xhs status                      # 检查 cookie 是否可用
boss xhs login                       # Playwright 有界面扫码
boss xhs login --name 备注名 --timeout 180
```

Playwright 已在主依赖中；若缺浏览器内核：`uv run playwright install chromium`。

### 网页版（对齐 spider/js `web_im`）

```bash
boss xhs web                         # http://127.0.0.1:8767/（默认开启自动回复）
boss xhs web --port 8767 --no-open
boss xhs web --no-auto-reply         # 关闭自动回复
boss xhs --account 账号名 web
```

自动回复与抖音类似：对方首条任意消息 → 问候；再回一条 → 联系方式；之后该会话不再自动发。

### 私信（终端）

```bash
boss xhs im chats                    # 会话列表
boss xhs im dump                     # 拉会话 + 历史，默认写 data/xhs/im/<昵称>/
boss xhs im dump -o out.json -q
boss xhs im send --to 对方昵称 --text "你好"
boss xhs im send --to <chat_user_id> --text "你好" --headed   # 失败时浏览器兜底
boss xhs im poll --interval 3        # HTTP 轮询新消息
boss xhs im listen                   # WebSocket 实时收信，Ctrl+C 结束
```

---

## 六、常用组合速查

| 场景 | 命令 |
|------|------|
| BOSS 求职扫码 | `boss login` → `boss status` |
| BOSS 招聘网页沟通 | `boss logout && boss login`（招聘号）→ `boss recruiter web` |
| 抖音首次/加号 | `boss douyin grab-ticket --qr` |
| 抖音切号 | `boss douyin accounts` → `boss douyin use 账号名` → `boss douyin web` |
| 抖音双开 | `--account A web --port 8766` + `--account B web --port 8767` |
| 小红书首次登录 | `boss xhs login` → `boss xhs status` |
| 小红书切号 | `boss xhs accounts` → `boss xhs use 账号名` → `boss xhs web` |
| 小红书网页沟通 | `boss xhs web`（默认 8767） |
| 搜职位打招呼 | `boss search …` → `boss batch-greet … --dry-run` → `-y` |
| 求职收信 | `boss listen` 或网页端（求职端无独立 web；招聘用 `recruiter web`） |

---

## 七、端口一览

| 服务 | 默认地址 |
|------|----------|
| BOSS 招聘网页沟通 | http://127.0.0.1:8765/ |
| 抖音私信网页 | http://127.0.0.1:8766/ |
| 小红书私信网页 | http://127.0.0.1:8767/ |

结束进程：对应终端 `Ctrl+C`。

---

## 八、输出格式（多数列表类命令）

```bash
boss search "Python" --json
boss chat --yaml
boss douyin inbox   # 终端表格；部分子命令支持 --json（以 --help 为准）
```

机器可读时优先看 `--json`，管道示例：

```bash
boss search "golang" --city 杭州 --json | jq '.data'
```
