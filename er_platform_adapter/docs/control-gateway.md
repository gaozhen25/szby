# Adapter Control Gateway

## 职责边界

`adapter-gateway` 是 PC Adapter 与内网 IM gRPC 之间的控制面网关。它不转发聊天消息，也不提供通用 gRPC 代理：

```text
PC Adapter ──HTTPS──► adapter-gateway ──gRPC──► openim.cs.cs
PC Adapter ──AMQP────────────────────────────► RabbitMQ
```

当前公开接口：

- `GET /health/live`：进程存活。
- `GET /health/ready`：IM gRPC channel 是否可用。
- `POST /v1/activate`：按激活码查询或创建一个或两个平台 Actor，并签发设备 Token。
- `POST /v1/audiences/ensure`：Bearer Token 鉴权后查询或创建 Audience。

## Actor 激活

PC 为每次安装生成稳定 UUID。用户提交激活码时，PC 发送当前已在线的平台 UID、昵称、头像和 profile。Gateway 先调用 `ActorGetAccount`；gRPC 返回 `NOT_FOUND` 或空响应时调用 `ActorAddAccount`：

```json
{
  "actorID": "<platform_actor_id>",
  "shopName": "",
  "BusinessDomain": "default",
  "activationCode": "<本次激活码>",
  "platform": "douyin",
  "openIMID": "",
  "nickname": "<平台昵称或平台UID>",
  "avatarURL": "<平台头像>",
  "profile": "{}",
  "status": "enable"
}
```

全部 Actor 操作成功后，Gateway 才在一个 SQLite 事务中绑定设备与平台 UID，并轮换设备 Token。原始 Token 只返回一次；数据库只保存 SHA-256 摘要。一个平台 UID 不能同时归属两台设备。

## Audience 创建与消息可靠性

PC 收到平台消息后先把 RabbitMQ payload 写入本地 SQLite outbox。发布前使用设备 Token 调用 Gateway；Gateway 校验请求中的 `platform + platform_actor_id` 属于该设备，然后调用 `AudienceGetAccount`，不存在时调用 `AudienceAddAccount`：

```json
{
  "actorPlatformID": "<platform_actor_id>",
  "audiencePlatformID": "<platform_audience_id>",
  "platform": "douyin",
  "nickname": "<联系人昵称或平台UID>",
  "avatarURL": "<联系人头像>",
  "profile": "{}",
  "status": "enable"
}
```

标准契约以 `AudienceGetAccount=NOT_FOUND` 表示账号不存在。当前部署的 IM 对部分不存在账号返回 `INVALID_ARGUMENT`；Gateway 仅对 `AudienceGetAccount + INVALID_ARGUMENT` 这一精确组合兼容为继续调用 `AudienceAddAccount`。其它 gRPC 错误不会降级，仍保留 outbox 并重试或等待人工处理。

Gateway 或 IM 暂时不可用时，PC 只更新 outbox 的下一次尝试时间。RabbitMQ publisher confirm 成功以前，事件不会从本机删除。进程重启后仍从同一 outbox 恢复。

## 安全与部署

- Gateway 默认监听 `127.0.0.1:8080`，生产环境由 nginx/Caddy 终止 TLS并暴露 HTTPS 域名。
- Uvicorn 只信任来自 `127.0.0.1`、`::1` 的代理头；边缘 Nginx 必须覆盖而不是透传客户端提供的 `X-Forwarded-For`。
- `IM_GRPC_TLS=false` 只能用于服务器内网；不要把 gRPC 地址暴露到公网。
- 激活接口按来源 IP 滚动限流。反向代理层仍应增加连接数、请求体和速率限制。
- Gateway 不信任 PC 提供的 `operationid`，每次 gRPC 调用生成新的追踪 ID。
- 激活码、设备 Token、Cookie、ticket 不进入访问日志或错误响应。激活码只在 PC 端凭证库持久化，Gateway 数据库不保存。
- Gateway 数据库和 WAL/SHM 文件权限设置为 `0600`。

服务端：

```bash
cp .env.server.example .env.server
uv sync --extra server
uv run --extra server adapter-gateway --dotenv .env.server
```

PC 端：

```dotenv
ADAPTER_GATEWAY_URL=https://adapter.example.com
ADAPTER_GATEWAY_TIMEOUT_SECONDS=15
```

如果明确接受明文传输，也可以配置：

```dotenv
ADAPTER_GATEWAY_URL=http://adapter.example.com:10030
ADAPTER_GATEWAY_ALLOW_INSECURE_HTTP=true
```
