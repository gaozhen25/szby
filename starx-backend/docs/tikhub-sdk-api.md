# TikHub SDK 运行时

## 架构定位

StarX 直接使用官方 `AsyncTikHub`，不在其外层复制资源方法，也不提供 `call(resource, operation, params)` 反射代理。

`app/services/tikhub_service` 只包含两个基础设施组件：

- `TikHubRuntime`：延迟创建并关闭进程共享的 `AsyncTikHub`。
- `TikHubTransport`：在 HTTP 传输层统一执行 QPS 和连接池并发限制。

SDK 自带的超时、重试、异常类型、资源对象、方法签名和 IDE 补全全部保留。当前安装的 `tikhub==2.1.2` 暴露 52 个资源，覆盖抖音、TikTok、小红书、快手、微博、B 站、微信、知乎、YouTube、Instagram、X 等平台。

## 内部调用

FastAPI 依赖或领域服务直接获取官方 SDK 类型：

```python
from tikhub import AsyncTikHub

from app.api.deps import get_tikhub_sdk


async def load_video(sdk: AsyncTikHub) -> object:
    return await sdk.douyin_app_v3.fetch_one_video_v3(
        aweme_id="7251234567890123456"
    )
```

其他平台同样直接使用 SDK：

```python
result = await sdk.tiktok_web.fetch_search_video(
    keyword="skincare"
)
```

具体资源、方法和参数以官方 SDK 类型及 OpenAPI 为准。StarX 不维护平台白名单或重复的方法目录。

## 业务适配

`app/services/tikhub_service/provider.py` 是账号报告和竞品监控使用的业务适配器。它直接调用具体 SDK 方法，并把少量业务需要的响应转换为 `TikHubAccount`、`TikHubContent` 和分页模型。

适配器当前覆盖抖音、小红书和快手，但这不是 TikHub 的能力边界。其他业务可以直接依赖 `AsyncTikHub`，或者在需要稳定领域语义时新增独立领域服务。

## HTTP 治理

SDK 构造时注入 `TikHubTransport`：

- 每次真实 HTTP 尝试前执行本机和 Redis QPS 限制。
- `httpx.AsyncHTTPTransport` 连接池控制最大并发和 Keep-Alive 连接数。
- SDK 内部重试仍会经过同一个 Transport，因此每次重试都计入限流。
- `AsyncTikHub.aclose()` 会关闭内部 `httpx.AsyncClient`，继而关闭 Transport、连接池和 Redis 客户端。

## 配置

```dotenv
STARX_TIKHUB_BASE_URL=https://api.tikhub.dev
STARX_TIKHUB_API_KEY=
STARX_TIKHUB_TIMEOUT=45
STARX_TIKHUB_MAX_RETRIES=3
STARX_TIKHUB_QPS=8
STARX_TIKHUB_MAX_IN_FLIGHT=16
```

真实密钥只写入被 Git 忽略的 `.env` 或部署环境密钥管理系统。中国大陆部署使用 `.dev`，其他区域使用 `.io`。

## API 边界

StarX 不提供 `/api/v1/tikhub/call` 通用代理。通用代理会丢失 SDK 类型安全、扩大权限和成本风险，并要求调用方了解 Python SDK 的内部命名。

需要对外提供 TikHub 能力时，应设计有明确业务语义、权限、成本预算和响应模型的领域 API。
