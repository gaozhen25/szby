# Message Adapter 架构

## 运行链路

```text
BOSS / Douyin / Rednote
      │ 平台消息
      ▼
message_adapter
      ├── publish push_message_v2 / send status ─► RabbitMQ ──► 上游消息系统
      ├── consume 文本发送任务 ◄──────────────── RabbitMQ ◄── 上游消息系统
      │
      └── HTTPS ──► adapter_gateway ──► 内网 IM gRPC
```

Adapter 不连接 qkserver，也不直接访问内网 IM gRPC。公网 `adapter_gateway` 接入多台 PC，只代理明确允许的 Actor/Audience 控制操作；消息仍走 RabbitMQ。

## 代码边界

- `message_adapter/core`：平台无关的 Actor、Audience、Conversation、Message 和发送模型。
- `message_adapter/platforms`：平台字段转换与统一 Adapter 契约。
- `message_adapter/gateway`：RabbitMQ 拓扑、确认、手动 ACK、过滤和重连。
- `adapter_gateway`：公网设备鉴权、Actor/Audience API、设备绑定数据库和内网 gRPC 客户端。
- `message_adapter/storage`：SQLite schema migration、凭证库、WAL、outbox、inbox、游标、幂等与回声指纹。
- `message_adapter/services`：实时流、平台安全基线、三 Worker 守护、健康服务和归档重置。
- `message_adapter/platforms/boss`：BOSS Adapter、鉴权、HTTP 与 MQTT 协议引擎。
- `message_adapter/platforms/douyin`：抖音 Adapter、鉴权、protobuf HTTP 与 Frontier WebSocket 协议引擎。
- `message_adapter/platforms/rednote`：小红书 Adapter、签名 HTTP 与私信 WebSocket 协议引擎。

平台协议字段不得进入 `core`。`platform_actor_id` 是平台 UID；`actor_id` 专指 IM 内部 ID。

## 平台契约

每个平台实现：

- `authenticate()`：验证凭证并返回稳定 Actor。
- `validate_identity(actor)` / `persist_identity(actor)`：在接触 MQ/outbox 前校验并绑定平台 UID。
- `bootstrap()`：建立首次基线或准备持久化恢复。
- `stream_messages()`：输出统一实时消息。
- `catch_up(cursor)`：仅供声明支持的平台回灌；`automatic_catch_up` 单独控制运行时是否自动调用。
- `resolve_conversation(platform_audience_id)`：缓存未命中时按真实 Audience UID 查找或创建会话。
- `send_text(conversation, text)`：执行真实平台发送。
- `close()`：停止连接和后台任务。

BOSS 另外声明 `wechat_exchange` 平台能力。收消息只消费登录之后的 MQTT 实时帧，不读取 `historyMsg`。好友列表在实时收发和 RabbitMQ 连接之后后台加载，不挡住 MQTT 回调，也不挡住下行发送。连接器不本地自动回复，也不按收到的聊天条数交换微信。轻回 AI 的文本从下行发出，同一求职者成功发出两句后才发起一次交换微信，记入 `boss_wechat_exchanges`。计数保存在 `boss_ai_reply_counts`，进程重启后继续累计；已经记录过的 UID 不会再次发起。交换在后台执行，不占用实时收发。交换手机号的请求代码保留着，`BOSS_PHONE_EXCHANGE_ENABLED` 当前为关闭，运行时不会发起。打开后与微信使用同一时机，并单独记入 `boss_phone_exchanges`。

抖音运行模式只消费 Frontier WebSocket 实时事件：启动不读取消息历史、重启不补拉历史、后台不轮询历史，发送后也不通过历史接口二次确认。进程完全离线期间的平台消息因此不承诺补偿；已经进入 SQLite outbox 的消息仍由本地持久化保证投递。

小红书同样不执行启动时自动历史补偿，避免重启时批量扫描会话。其 `history_backfill` 只供人工执行带确认的 `adapter backfill`。

一个激活码对应一个本地工作区；同一时间只挂载一个工作区。本机当前工作区内每个平台只有一个设备槽位。`adapter serve` 同时提供本地网页并监督三个独立消息 Worker；没有凭证的平台保持 `offline`。已登录平台发生异常时按 2、5、10、30、60 秒加抖动重启，不影响其他平台。`adapter run` 与 `serve` 使用同一平台锁，禁止重复启动；`serve` 还持有全局工作区管理锁，避免两个进程同时切换或重置。

本地网页命名为“轻回桌面连接器”。网页只绑定回环地址，通过同源的短期进程控制令牌保护本地账号、平台登录和归档等写操作。页面可读取平台 UID、脱敏状态和当前激活码，但不返回 Cookie、ticket、设备 Token 或 MQ 密码。激活码以明文保存在权限为 `0600` 的全局工作区注册库中，工作区目录只使用随机 `workspace_id`。刷新页面或重启服务会恢复最后登录的工作区；显式退出仅清除活动指针，不删除工作区。激活码不会写入浏览器 Web Storage、Gateway SQLite 或日志。

每个工作区都有独立 SQLite 凭证库、平台状态库、Profile、媒体缓存和日志目录。协议实现只接收当前工作区已解析的凭证，不读取其他工作区、JSON 文件或历史项目目录。环境变量注入的平台 Cookie 无法满足隔离要求，因此存在这类变量时拒绝切换和重置工作区。

## 浏览器与 UID 绑定

- 每个平台对应当前工作区内一个固定 Chrome Profile：`adapter_data/workspaces/<workspace_id>/profiles/<platform>/device`。用户无需也不能输入账号名。
- 扫码始终启动本机 Google Chrome 的有界面模式，不使用临时上下文、Playwright 内置 Chromium 或用户的日常 Chrome Profile。
- Profile 目录与锁目录在 POSIX 系统上设为 `0700`，同一个 Profile 同时只允许一个进程操作。
- 扫码成功后，Profile 绝对路径与凭证一起记录。BOSS 微信交换等高风控操作会校验绑定关系，并在真实页面上下文内执行；旧凭证需要重新扫码建立绑定，不会静默降级到直接 HTTP。
- 普通消息收发仍使用既有 HTTP/MQTT/WebSocket 协议引擎，避免长期开着浏览器。平台 UID 与已绑定 UID 不一致时，在连接 MQ、恢复 outbox 或启动实时流前失败。
- 网页“重新登录”保留 UID 状态绑定并拒绝不同 UID；“更换账号”或显式 `reset --confirm-uid` 才会将状态、凭证和 Profile 移入私有归档。
- `logout` 删除凭证库条目；抖音还会清除 Chrome Profile，且每次抖音登录前也会先清 Profile 再扫码。状态库 UID 绑定保留，换号需 `reset`。

## 本地服务与健康状态

- `GET /health/live` 返回版本和运行时长。
- `GET /health/ready` 返回三个消息 Worker 的状态、平台 UID、重启次数、最后状态时间和脱敏错误。
- `GET /api/state` 返回网页所需的本机服务、平台与注册状态。Boss、抖音、小红书要等该平台注册成功、RabbitMQ 已连接且最近一次同步没有失败才显示在线；好友列表未完成不影响这个状态。同步失败时显示连接异常，不显示在线。满足该条件的 Boss、抖音、小红书账号会调用账号监控告警接口。在线时发送 `alert_type=online`、`source_service=adapter`，之后每 40 秒重发一次，供对方按 120 秒计时。账号过期、掉线或正常退出时发送 `offline`。超过 120 秒没有新的 `online`，对方显示掉线。小红书的 `platform` 固定为 `rednote`。
- `POST /api/local-account/login` 加载已有激活码工作区；未知激活码只有携带显式创建确认时才新建。
- `POST /api/local-account/logout` 停止所有 Worker 并卸载当前工作区，不删除任何数据。
- `POST /api/local-account/reset` 在确认后归档整套工作区，并以相同 `workspace_id`、激活码和 `device_id` 创建空白工作区。
- `POST /api/local-account/sync` 人工重试当前工作区到上游的完整账号集合。
- `POST /api/platforms/{platform}/login|logout` 触发扫码登录或退出。
- `POST /api/platforms/{platform}/reset` 校验当前 UID 并归档后允许换号。
- `POST /api/diagnostics/download` 下载脱敏日志与运行环境诊断包。
- `POST /api/shutdown` 使用本机控制令牌请求服务有序退出，供 Windows 启动器和构建冒烟测试使用。
- 三个平台均 ready 时为 `ready`；至少一个 ready 时为 `partial` 并返回 HTTP 200；均不可用时为 `unavailable` 并返回 HTTP 503。
- 健康服务只允许绑定 loopback 地址，不暴露凭证、MQ 密码或 Profile 内容。

## 投递与恢复不变量

1. 上行事件和稳定 UUID 先写入 SQLite outbox，再推进平台游标。
2. 只有 RabbitMQ publisher confirm 成功后才删除 outbox。
3. 配置控制 Gateway 后，上行 outbox 在 MQ 发布前确保 Audience 已存在；Gateway/IM 不可用只更新重试时间，不删除 outbox，也不断开 MQ consumer。
4. IM 下行先写入 SQLite inbox，再进行 RabbitMQ manual ACK。
5. 同一 `client_msg_id` 最多触发一次已确认的平台发送。
6. 发送结果 `{clientMsgID,status,actualSendTime}` 和对应 outbox 在同一事务中提交；`status=0` 成功、`status=1` 失败。
7. Adapter 下发产生的平台回声优先用平台消息 ID 抑制；缺失 ID 时使用 15 秒的一次性会话文本指纹。
8. 平台 App 内人工发送的普通消息仍以 `direction=1`、`is_task_message=false` 上报。
9. IM 下行在调用平台前取得持久化发送时隙；最小间隔加随机抖动，并受分钟/小时滚动硬上限约束。
10. 只有当前活动工作区创建 Worker；inactive 工作区的 outbox 和下行任务不会被读取，切回后才继续恢复。

平台认证成功会触发后台上游同步。每次同步都从当前凭证库重新收集全部已绑定平台账号，避免新增平台时覆盖已有归属。网络、gRPC 或 Gateway 暂时不可用不会卸载本地账号或停止平台实时流；需要 Audience 注册的 outbox 保留并退避重试。Gateway 明确返回不可重试的激活码或 IM 拒绝时停止自动重试，等待用户处理后点击“重试同步”。

切换激活码先完整停止实时连接、MQ、SQLite 和登录任务，再加载目标工作区。重置工作区先切回全局日志并关闭所有句柄，使用可回滚移动归档整个目录；归档失败会把原目录恢复到原位。归档清单只记录随机工作区 ID、稳定设备 ID和平台 UID，不记录激活码或凭证。

限流等待发生在 SQLite 队列中，不占用 asyncio Worker，也不提前标记为平台发送中。进程重启会保留未来时隙和最近发送记录，因此不能通过重启绕过配额。只有平台操作真正开始时任务才进入 `processing`；此前崩溃的 `claimed` 任务会安全回队，开始后崩溃的任务仍按 `previous_attempt_unconfirmed` 处理。

首次启动先打开实时流，再建立历史快照；快照消息和启动时刻以前的消息只作为基线。后续启动仅在平台声明 `automatic_catch_up` 时自动补偿；抖音和小红书均关闭该能力。

如果进程在平台发送期间崩溃，启动恢复会记录 `previous_attempt_unconfirmed`，不会盲目重复发送用户可见消息。

## 当前范围

- BOSS、抖音：文本双向链路。
- BOSS：对方新消息后自动回复两句，请对方加我们的微信，再发起一次微信交换。
- 打包后的 `adapter.exe` 在 `serve` 时拉起看守进程。进程一旦退出，约 2 秒后会再打开，不区分退出原因。`--no-restart` 可关闭这个行为。
- 小红书（平台标识 `rednote`）：私信与 BOSS、抖音同一套上行类型。文本是 `101`，图片是 `102`，语音是 `103`，视频和实况图是 `104`。后台下发仍只发送文本。
- 图片、音视频、文件：暂不向平台发送，明确返回 unsupported。
- IM gRPC Actor/Audience 注册：已通过公网 Gateway 接入；生产部署需要配置 HTTPS 域名和内网 `IM_GRPC_TARGET`。

旧 Web UI、自动回复、职位搜索、推荐、候选人管理和索引缓存已经移除。如需查阅或回滚，可使用 Git 标签 `pre-refactor-20260909`。
