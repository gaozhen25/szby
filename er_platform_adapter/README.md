# 多平台消息 Adapter

本项目把 BOSS 直聘、抖音和小红书私信接入上游 IM。一台电脑的每个平台固定承载一个平台 UID。消息数据面直接连接 RabbitMQ；Actor/Audience 控制面通过公网 `adapter-gateway` 转发到内网 IM gRPC，不依赖也不包含 qkserver。

当前能力：

- BOSS、抖音、小红书文本消息双向转换与收发。
- BOSS 双方各发送至少 3 条文本后自动发起一次微信交换，并按 Actor/Audience UID 防重。
- “轻回桌面连接器”把激活码作为本地账号，展示 BOSS、抖音、小红书、微信和企业微信状态，并提供登录、切换工作区、归档重置和诊断下载。
- `adapter-gateway` 接入多台 PC，签发设备 Token，并以受限接口代理 IM Actor/Audience gRPC。
- `adapter serve` 在一个本地进程内独立监督 BOSS、抖音、小红书三个消息 Worker；只登录其中一个平台也可以正常运行。微信和企业微信通过本机客户端日志发现账号，不在此进程内收发消息。
- RabbitMQ 手动 ACK、publisher confirm、断线重连与平台/UID 过滤。
- SQLite WAL 持久化游标、事务 outbox、下行幂等与回声抑制。
- IM 下行先持久化排队，再按平台执行最小间隔、随机抖动和分钟/小时硬限流。
- 首次启动只建立历史基线；抖音和小红书重启后不自动拉取历史，避免批量请求触发平台风控。
- 小红书（平台标识 `rednote`）私信与 BOSS、抖音一样走扫码登录。上行文本、图片、语音、视频使用同一套 contentType，后台下发仍只发送文本。

## 安装与配置

```bash
uv sync --extra dev --extra browser
cp .env.example .env
```

扫码登录要求本机已安装 Google Chrome；无需安装 Playwright 自带的 Chromium。Adapter 不读取日常 Chrome 用户目录。每个激活码拥有随机 ID 的独立工作区，三个消息平台的 Chrome Profile 位于 `adapter_data/workspaces/<workspace_id>/profiles/<platform>/device`。同一 Profile 有进程锁，不能被两个进程同时占用。

在 `.env` 中填写 RabbitMQ 连接和拓扑。`.env` 已被 Git 忽略，请勿提交账号凭证，也不要通过 `BOSS_COOKIES`、`DY_COOKIE` 或 `REDNOTE_COOKIE` 注入平台 Cookie；这类全局变量无法随工作区隔离。平台状态、登录凭证、媒体缓存和日志全部保存在当前工作区内，不再生成 JSON 副本。

同时配置公网控制服务地址：

```dotenv
ADAPTER_GATEWAY_URL=https://adapter.example.com
ADAPTER_GATEWAY_TIMEOUT_SECONDS=15
```

默认要求 HTTPS；如果确定使用远程明文 HTTP，必须同时配置 `ADAPTER_GATEWAY_ALLOW_INSECURE_HTTP=true`。这会让激活码和设备 Token 以明文经过网络，只适合受控网络环境。

## 启动轻回桌面连接器

```bash
# 启动后会自动打开浏览器
uv run adapter serve --health-host 127.0.0.1 --health-port 8765 --dotenv .env
```

浏览器会打开 `http://127.0.0.1:8765/`。之后用户只在网页中操作：

1. 在页面顶部输入激活码，登录本地账号。未知激活码必须再次确认后才会创建新工作区。
2. 登录实际需要的平台；没有登录的平台保持离线，不会阻塞其他平台。
3. 平台登录后，连接器会在后台向 Gateway 提交当前工作区的完整平台账号集合并查询或创建 IM Actor。
4. Gateway 暂时不可用时，本地账号和平台连接保持运行，上行消息继续留在当前工作区的事务 outbox；恢复后可自动重试或点击“重试同步”。

页面和控制接口只监听本机回环地址。激活码以明文保存在权限为 `0600` 的 `adapter_data/workspaces.sqlite3` 中并持续显示在页面，但不会写入目录名、日志或浏览器 Web Storage。程序重启会恢复上次仍处于登录状态的工作区。“切换激活码”只停止 Worker 并卸载当前工作区，数据完整保留；再次输入同一码即可恢复。“重置当前工作区”会归档整套 Profile、凭证、消息库和日志，保留稳定的 `device_id`，然后创建空白工作区。Cookie、ticket、设备 Token 和 MQ 密码不会显示在页面。

同一时间只运行一个工作区。目录结构如下：

```text
adapter_data/
├── workspaces.sqlite3                  # 本地账号注册库，0600
├── workspaces/<workspace_id>/
│   ├── credentials.sqlite3
│   ├── boss.sqlite3
│   ├── douyin.sqlite3
│   ├── rednote.sqlite3
│   ├── profiles/
│   ├── douyin_media/
│   └── logs/
└── archive/                            # 工作区或单平台的可恢复归档
```

## 部署控制 Gateway

Gateway 部署在能够访问 IM gRPC 内网地址的服务器上：

```bash
cp .env.server.example .env.server
uv sync --extra server
uv run --extra server adapter-gateway --dotenv .env.server
```

关键服务端配置：

```dotenv
ADAPTER_GATEWAY_HOST=127.0.0.1
ADAPTER_GATEWAY_PORT=8080
ADAPTER_GATEWAY_DB=adapter_gateway_data/gateway.sqlite3
IM_GRPC_TARGET=8.216.34.9:30500
IM_GRPC_TLS=false
```

建议 Gateway 仅监听服务器回环地址，由 nginx/Caddy 提供公网 HTTPS。不要把 IM gRPC 端口直接暴露给 PC。Gateway 的公开接口只有健康检查、设备激活和 Audience 确保，不提供任意 gRPC 方法代理。详细说明见 [控制 Gateway](docs/control-gateway.md)。

以下命令只保留给开发、诊断和故障恢复，不是日常用户流程。除 `serve`、`mq-watch` 和 `doctor --skip-platform` 外，平台命令使用网页当前登录的工作区；没有活动工作区时会明确要求先在网页登录激活码。

```bash
# 只读检查本地配置、凭证、SQLite 与平台能力
uv run adapter doctor --platform douyin

# 调试时也可只启动一个平台；与 serve 共用平台锁，不能重复运行
uv run adapter run --platform douyin
uv run adapter run --platform boss

curl http://127.0.0.1:8765/health/live
curl http://127.0.0.1:8765/health/ready

# 使用独占临时队列观察 MQ；不会与现有消费者竞争
uv run adapter mq-watch --platform douyin --seconds 60
uv run adapter mq-watch --platform douyin --all-platforms --seconds 60

# BOSS/小红书可显式历史回灌，默认先 dry-run；抖音历史访问已禁用
uv run adapter backfill \
  --platform boss \
  --since 2026-09-01T00:00:00+08:00 \
  --limit 50 \
  --dry-run
```

开发 CLI 中 BOSS 和抖音保留相同的登录与私信命令。`messages` 和 `send` 都接收
`conversations` 返回的稳定 `conversation_id`，不使用列表序号：

```bash
# 将 PLATFORM 换成 boss 或 douyin；小红书日常登录使用连接器网页
uv run adapter PLATFORM login
uv run adapter PLATFORM logout
uv run adapter PLATFORM status --json
uv run adapter PLATFORM conversations --limit 20 --json
uv run adapter PLATFORM messages CONVERSATION_ID --limit 30 --json
uv run adapter PLATFORM send CONVERSATION_ID "你好" --json
```

用户不输入账号名；扫码后取得的平台 UID 是当前工作区槽位的唯一身份。昵称和头像仅作展示信息。网页“重新登录”只允许同一 UID；单个平台换号必须点击“更换账号”并输入当前 UID，或使用诊断命令：

```bash
uv run adapter reset --platform douyin --confirm-uid 1234567890
```

`reset` 会先取得当前工作区中的 Worker 和 Profile 锁，再把该平台状态、凭证和 Chrome Profile 移入当前工作区的 `archive/`，不会影响激活码或其他平台。`logout` 清除凭证库条目，不解除状态库的 UID 绑定；抖音退出时还会清除对应 Chrome Profile，且每次抖音扫码登录前也会先清 Profile 再拉起全新 Chrome。

启动且尚未登录本地账号时，日志写入 `adapter_data/logs/adapter.jsonl`；登录后切换到当前工作区的 `logs/adapter.jsonl`。单文件 10 MB、保留 5 个轮转文件。网页诊断包只包含当前工作区日志和脱敏状态，不会混入其他激活码的数据，也不包含数据库、Cookie、激活码或 `.env` 原值。

默认每次 IM 下行平台操作间隔为随机 `4~8` 秒，同时限制为每分钟最多 8 次、每小时最多 120 次。可用 `ADAPTER_SEND_MIN_INTERVAL_SECONDS`、`ADAPTER_SEND_JITTER_SECONDS`、`ADAPTER_SEND_MAX_PER_MINUTE`、`ADAPTER_SEND_MAX_PER_HOUR` 调整全局默认值；也可用 `BOSS_SEND_*`、`DOUYIN_SEND_*` 对单个平台覆盖。限流时任务保留在 SQLite 中排队，不会向 IM 上报伪失败；发送时隙同样持久化，重启不会清空配额或打乱队列。间隔和抖动都必须为正数，不能通过配置完全关闭保护。

BOSS 搜索/推荐/候选人管理、平台调试命令、浏览器 Cookie 读取、旧本地自动回复及 BOSS/抖音 Web UI 已移除。回滚基线为 Git 标签 `pre-refactor-20260909`。

## 消息约定

- 上行文本使用 `func=push_message_v2`、`contentType=101`。
- `direction=0` 表示 Audience → Actor，`direction=1` 表示 Actor → Audience。
- `platform_actor_id` / `actorPlatformID` 是平台真实 UID；IM 内部 ID 使用 `actor_id`，两者不可混用。
- 下行以 `client_msg_id` 幂等；重复投递不会重复调用平台发送接口。
- 非文本下行不会调用平台 API，会持久化并上报失败状态。
- MQ 发送结果固定为 `status=0` 成功、`status=1` 失败。
- BOSS 双方各有 3 条文本后会自动发起一次微信交换。
- RabbitMQ confirm 仅表示 Broker 已接收，不代表 IM 业务 ACK；上行稳定事件 ID支持上游去重。

Actor、Audience 的 IM 实体由 `adapter-gateway` 根据 `im.proto` 查询或创建。激活码由 PC 端工作区注册库持久化，并在后台同步时传递给 `ActorAddAccount`；Gateway 数据库不保存激活码。每个工作区拥有稳定且唯一的 `device_id`，重置工作区时也不会改变。

详细边界和恢复语义见 [Adapter 架构说明](docs/adapter-architecture.md)。

## 项目结构

```text
message_adapter/
├── core/                  # 平台无关模型与 Adapter 接口
├── gateway/               # RabbitMQ 连接和投递语义
├── storage/               # SQLite WAL、outbox、幂等与游标
├── services/              # 上下行、双 Worker、健康服务与归档重置
├── platforms/
│   ├── boss/              # BOSS Adapter、鉴权、HTTP、MQTT
│   ├── douyin/            # 抖音 Adapter、鉴权、protobuf、WebSocket
│   └── rednote/           # 小红书私信
├── cli.py                 # 唯一命令入口
├── config.py              # 环境和拓扑配置
├── browser_profiles.py    # 每平台单一的持久化 Chrome Profile
adapter_gateway/
├── app.py                 # 公网受限 HTTP API、设备鉴权和限流
├── grpc_client.py         # 内网 IM gRPC 调用及字段映射
├── store.py               # 多设备绑定与 Token 哈希
└── proto/                 # im.proto 与生成的 Python 绑定
```

仓库发布 PC 端 `message_adapter` 和服务端 `adapter_gateway` 两个边界清晰的包，对应 `adapter`、`adapter-gateway` 两个入口。平台之间不互相嵌套，也不能跨目录引用协议实现。

## 开发验证

```bash
uv run --extra dev pytest -q
uv run --extra dev ruff check .
```

涉及真实平台和 MQ 的联调命令需要有效账号与网络环境；单元测试不会连接外部服务。
