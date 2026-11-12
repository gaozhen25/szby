# StarX 后端

StarX 后端基于 FastAPI、SQLAlchemy、PostgreSQL 与 Alembic。本仓库内嵌了经过裁剪的 MediaSpider 运行时，用于小红书、抖音和快手的公开内容采集，并通过 `account_report` workflow 生成账号报告。

## 1. 环境要求

- Python 3.12，统一使用名为 `starx` 的 conda 环境。
- PostgreSQL 与 Redis。
- Playwright Chromium，或支持 CDP 的本地 Chromium/Chrome。
- 前端需要 Node.js；后端安装、迁移、测试、启动和浏览器安装不得使用其他 Python 虚拟环境。

```bash
conda create -n starx python=3.12
conda activate starx
pip install -r requirements.txt
playwright install chromium
```

也可以不激活环境，统一使用：

```bash
conda run -n starx pip install -r requirements.txt
conda run -n starx playwright install chromium
```

若部署系统缺少 Chromium 系统库，请按 Playwright 对应操作系统文档安装依赖。该步骤可能需要系统管理员权限。

## 2. 环境变量

复制空值模板，并在部署系统的秘密管理服务或本机 `.env` 中填写实际值：

```bash
cp .env.example .env
```

`.env.example` 不包含真实凭证。生产环境至少需要配置数据库、Redis、对象存储和 AI 服务；爬虫 Cookie 使用下述独立 JSON 文件。

### 2.1 三个平台 Cookie 池

Cookie 不写入 `.env`。后端在每次账号报告 workflow 启动时读取 `cookies/cookies.json`：

```json
{
  "xhs": ["cookie-a", "cookie-b"],
  "dy": ["cookie-c"],
  "ks": []
}
```

每个平台对应一个 Cookie 字符串数组。真实文件只保存在部署环境，并由 `.gitignore` 排除；前端不读取、不提交也不展示 Cookie。每次爬取按平台轮询选择 Cookie，认证失效时自动尝试池内下一条。API、workflow payload、日志和测试快照同样不得包含 Cookie。

账号报告 workflow 与 `scripts/media_spider.py` 直接爬取脚本共用这套 Cookie 池和认证失效轮换策略。

### 2.2 浏览器模式

默认使用 Playwright 管理的 Chromium：

```dotenv
STARX_MEDIASPIDER_HEADLESS=true
STARX_MEDIASPIDER_ENABLE_CDP_MODE=false
```

- 服务端建议保持 `HEADLESS=true`。
- 本地排查登录或页面兼容问题时可临时设为 `false`，但仍不得把凭证写入仓库。
- `STARX_MEDIASPIDER_CUSTOM_BROWSER_PATH` 可指定 Chrome/Chromium 可执行文件绝对路径；留空时使用 Playwright 浏览器。

需要连接现有浏览器时启用 CDP：

```dotenv
STARX_MEDIASPIDER_ENABLE_CDP_MODE=true
STARX_MEDIASPIDER_CDP_CONNECT_EXISTING=true
STARX_MEDIASPIDER_CDP_DEBUG_PORT=9222
STARX_MEDIASPIDER_CUSTOM_BROWSER_PATH=
```

连接现有浏览器前，应由运维以对应调试端口启动浏览器，并限制端口只对可信网络开放。`CDP_CONNECT_EXISTING=false` 时由运行时按配置启动 CDP 浏览器。

### 2.3 代理与采集上限

```dotenv
STARX_MEDIASPIDER_ENABLE_IP_PROXY=false
STARX_MEDIASPIDER_IP_PROXY_PROVIDER=kuaidaili
STARX_MEDIASPIDER_STATIC_PROXY_URL=
STARX_MEDIASPIDER_MAX_NOTES_COUNT=30
STARX_MEDIASPIDER_MAX_COMMENTS_COUNT=10
STARX_MEDIASPIDER_MAX_CONCURRENCY=1
STARX_MEDIASPIDER_ENABLE_COMMENTS=true
STARX_MEDIASPIDER_ENABLE_SUB_COMMENTS=false
```

- 固定代理写入 `STATIC_PROXY_URL`；代理地址中如含认证信息，也必须按秘密处理。
- 未配置代理时保持 `ENABLE_IP_PROXY=false`。
- 内容数、评论数和并发上限用于控制平台压力、提示词体积与内存占用，不建议在未压测时提高。
- MediaSpider 会临时修改进程级配置，因此爬虫调用在同一进程内串行；该锁不阻塞其他 AI workflow。

## 3. 数据库迁移

应用启动前执行迁移：

```bash
conda run -n starx alembic upgrade head
```

迁移 `20260714_000020` 会检查 PostgreSQL 中 `reports.generated_at` 的实际类型；若旧数据库仍为无时区时间戳，会把已有值按 UTC 解释并安全转换为 `TIMESTAMPTZ`。运行时使用 asyncpg URL 时，Alembic 会转换为 psycopg 同步 URL。

初始化演示数据仅用于本地环境：

```bash
conda run -n starx python -m app.db.init_db
```

## 4. 启动与验证

```bash
conda run -n starx uvicorn app.main:app --reload
```

默认 API 地址为 `http://127.0.0.1:8000/api/v1`。完整测试：

```bash
conda run -n starx pytest tests -q
```

MediaSpider 导入冒烟检查：

```bash
conda run -n starx python -c "from app.services.mediaspider import MediaCrawlerService; print(MediaCrawlerService.__name__)"
```

## 5. 账号报告 API 与 workflow

账号创建成功后会异步提交唯一的 `account_report` workflow，接口不会等待爬取完成。报告完成后也不会自动生成选题；用户在选题中心主动生成时，选题 workflow 才读取最新版账号报告。

- `GET /api/v1/accounts/{account_id}/report`：读取兼容摘要与结构化报告。
- `POST /api/v1/accounts/{account_id}/report/workflows`：创建或复用正在运行的报告 workflow。
- `POST /api/v1/accounts/{account_id}/report/similar-accounts/workflows`：生成相似账号板块。
- `POST /api/v1/accounts/{account_id}/report/compliance-rules/workflows`：生成行业合规提醒板块。
- `POST /api/v1/accounts/{account_id}/report/target-user-profile/workflows`：生成目标用户画像板块。
- `POST /api/v1/accounts/{account_id}/report/hot-contents/workflows`：生成爆款内容板块。
- `GET /api/v1/accounts/{account_id}/report/workflows/latest`：读取最新 workflow。
- `GET /api/v1/accounts/{account_id}/report/workflows/{workflow_id}`：读取指定 workflow。

workflow 依次执行账号上下文、关键词规划、博主采集、关键词采集、证据归一化、报告分析和原子持久化。部分平台失败时保留成功平台证据并在 `sourceMeta` 中说明；所有受支持平台均失败时 workflow 失败，旧报告不会被覆盖。

## 6. 视频号降级

当前只集成小红书、抖音和快手爬虫。视频号不会启动 MediaSpider：

- 仅选择视频号时，系统使用账号档案与知识库生成无外部采集的降级报告。
- 视频号与受支持平台并存时，视频号写入 `sourceMeta.unsupportedPlatforms`，其他平台正常采集。
- 页面会展示来源限制，不会把降级报告伪装成平台采集结果。

## 7. 竞品账号与视频监控

竞品监控支持添加、删除和刷新小红书、抖音、快手的公开账号主页与内容详情链接。添加后立即执行首次采集；前端可以刷新单个对象或当前类型的全部对象。后台扫描器默认每分钟检查一次到期对象，每个对象默认每 6 小时自动刷新。

```dotenv
STARX_COMPETITOR_REFRESH_INTERVAL_SECONDS=21600
STARX_COMPETITOR_SCHEDULER_SCAN_SECONDS=60
STARX_COMPETITOR_SCHEDULER_BATCH_SIZE=20
STARX_COMPETITOR_WORKFLOW_STALE_SECONDS=7200
STARX_COMPETITOR_WORKFLOW_HEARTBEAT_SECONDS=60
STARX_COMPETITOR_CRAWL_MAX_ATTEMPTS=3
STARX_COMPETITOR_CRAWL_RETRY_BACKOFF_SECONDS=1.0
```

手动刷新和后台定时刷新共用 `competitor_refresh` workflow。临时平台错误默认最多尝试 3 次，并按 1、2 秒指数退避；账号基本信息已经采集成功但作品列表持续失败时，会保留可用的账号数据。成功刷新会保存指标快照并计算增量；失败时保留最后一次成功数据。接口、状态和多实例调度说明见 [竞品监控 API 与调度说明](docs/competitor-monitoring-api.md)。

## 8. 隐私与数据最小化

- 只采集生成报告所需的公开内容，并遵守目标平台规则和适用法律。
- Cookie 只由后端进程从环境变量或秘密管理服务读取，并在调用时传给爬虫；不写数据库、文件、workflow 记录或日志。
- 创作者标识在报告前进行稳定哈希；不保存联系方式、登录凭证、IP 属地或性别等非必要信息。
- 完整帖子、评论集合和媒体文件不长期入库；数据库只保存结构化报告与有限精选证据。
- 报告中的公开链接只供溯源，前端仅允许 `http/https` 链接跳转。
- 生产日志不得记录完整 AI 提示词、评论原文、Cookie 或含认证信息的代理 URL。

## 9. 认证

核心认证接口：

- `POST /api/v1/auth/login`
- `GET /api/v1/auth/me`

演示账号只应用于本地初始化数据，不应在生产环境沿用。
