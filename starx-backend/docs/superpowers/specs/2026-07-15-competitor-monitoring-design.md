# 竞品监控设计

## 1. 背景与目标

当前前端 `CompetitorMonitor` 页面仅使用组件内的演示数据，添加、删除和“生成同款”都没有真实后端能力。后端已经具备账号隔离、统一工作流、MediaSpider 内嵌爬虫和 PostgreSQL 持久化能力，但尚未建立竞品监控领域模型、精确内容爬取入口和周期刷新调度。

本次实现完整的竞品监控基础闭环：

1. 用户可为当前运营账号添加、查看和删除监控视频或监控账号。
2. 用户可在前台主动刷新单个监控对象或当前类型的全部监控对象。
3. 后台按持久化的到期时间定时认领监控对象，并执行爬取任务刷新数据。
4. 每次成功刷新保存快照并计算相对上次成功数据的增量。
5. 爬取失败时保留最后一次成功数据，同时向前台暴露安全、可操作的失败状态。

## 2. 范围

### 2.1 首期支持

- 监控视频：用户粘贴单条小红书笔记、抖音视频或快手视频链接。
- 监控账号：用户粘贴小红书、抖音或快手创作者主页链接。
- 添加成功后立即创建首次刷新任务，不用等待下一个周期。
- 默认每 6 小时自动刷新；可通过后端环境变量统一调整。
- 前台提供单项刷新和当前类型全部刷新。
- 展示对象基本信息、当前指标、相对上次成功刷新的增量、最后成功时间、刷新状态和公开失败原因。
- 所有读取和写入都按登录用户与当前运营账号隔离。

### 2.2 非目标

- 不实现用户自定义每个对象的刷新频率。
- 不引入 Celery、独立消息队列 worker 或新的微服务。
- 不实现复杂趋势图、告警通知、竞品分组和批量导入。
- 不在本次伪造“生成同款”结果；监控视频只提供打开原内容和进入已有内容解析入口，监控账号提供打开主页。
- 不保证平台未公开的指标可用；页面只展示本次爬取实际获得的字段。

## 3. 核心决策

采用“数据库持久化到期时间 + FastAPI 轻量扫描器 + 现有工作流调度器”的方案。

数据库是调度事实来源。扫描器只负责周期查找并原子认领 `next_refresh_at` 已到期的对象，实际爬取由现有 `WorkflowScheduler` 执行。手动刷新与定时刷新调用同一个刷新服务、创建同一种 `competitor_refresh` 工作流，避免两套业务逻辑产生不同结果。

不采用纯进程定时器，因为多 worker 会重复执行且重启后无法恢复；不采用 Celery，因为当前项目的部署体量不值得增加独立基础设施。

## 4. 架构与模块边界

### 4.1 后端模块

新增 `app/services/competitor_monitoring/` 领域包，各文件保持单一职责：

- `models.py`：领域输入、刷新结果和指标快照类型，不依赖 FastAPI。
- `repository.py`：监控对象查询、创建、删除、原子认领、快照和刷新状态持久化。
- `normalizers.py`：把三个平台的 MediaSpider 内容与创作者记录映射为稳定指标。
- `service.py`：新增/删除、手动刷新、批量刷新、任务去重和刷新结果落库的业务编排。
- `workflow.py`：注册 `competitor_refresh` 工作流，调用 MediaSpider 并交给服务完成成功或失败收尾。
- `periodic_scheduler.py`：FastAPI 生命周期内的周期扫描、认领和提交；不包含爬虫或指标映射逻辑。

新增 `app/api/routes/competitors.py` 作为薄路由层，负责鉴权、参数校验、状态码和 schema 转换。API schema 放在 `app/schemas/competitors.py`。

### 4.2 MediaSpider 扩展

现有服务只有 `search` 和 `creator` 两种公开模式，而内嵌的三个平台爬虫已经具备指定内容详情能力。本次把该能力以稳定接口暴露为：

```python
await MediaCrawlerService.crawl_by_detail(content_url=..., on_progress=..., **runtime_options)
```

`CrawlerRunConfig.crawl_type` 增加 `detail`，配置作用域根据平台写入相应的指定内容 URL 列表。结果仍通过现有内存 Collector 返回，Cookie 不进入日志、异常或持久化数据。

### 4.3 前端模块

- `src/api/starx.js`：增加竞品监控 REST 方法。
- `src/hooks/useCompetitorMonitoring.js`：管理当前账号的列表加载、账号切换防陈旧响应、刷新任务轮询和操作状态。
- `src/pages/CompetitorMonitor.jsx`：页面编排、类型切换、空状态和卡片列表。
- `src/components/competitors/`：拆分添加弹窗、视频卡、账号卡、指标和刷新状态组件，避免单页文件过长。

## 5. 数据模型

### 5.1 `competitor_accounts`

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | varchar(36) PK | 监控对象 ID |
| `account_id` | varchar(36) FK/index | 所属运营账号 |
| `user_id` | varchar(36) FK/index | 所属用户，用于双重隔离 |
| `platform` | varchar(16) | `xhs` / `dy` / `ks` |
| `profile_url` | text | 规范化主页链接 |
| `name` | varchar(128) | 最近一次成功抓取的公开名称 |
| `bio` | text | 公开简介；平台未提供时为空 |
| `avatar_url` | text | 公开头像地址；平台未提供时为空 |
| `followers` | bigint nullable | 粉丝数 |
| `following` | bigint nullable | 关注数 |
| `works` | bigint nullable | 作品数 |
| `liked` | bigint nullable | 获赞数 |
| `delta_metrics` | json | 相对上次成功快照的增量 |
| `refresh_status` | varchar(16) | `pending/running/succeeded/failed` |
| `refresh_error_code` | varchar(64) | 公开错误代码 |
| `refresh_error_message` | text | 安全文案，不含底层异常和凭证 |
| `active_workflow_id` | varchar(36) nullable | 当前刷新工作流 |
| `last_attempted_at` | timestamptz nullable | 最近尝试时间 |
| `last_refreshed_at` | timestamptz nullable | 最近成功时间 |
| `next_refresh_at` | timestamptz | 下次自动刷新时间 |
| `created_at/updated_at` | timestamptz | 审计时间 |

`(account_id, profile_url)` 唯一，禁止同一运营账号重复添加同一主页。

### 5.2 `competitor_videos`

公共调度字段与账号表一致，业务字段包括：

- `content_url`：规范化的原内容链接，和 `account_id` 组成唯一约束。
- `platform_content_id`：平台内容 ID；首次成功刷新后写入。
- `competitor_account_id`：可空，若能可靠匹配已监控账号则关联。
- `title`、`description`、`cover_url`、`author_name`、`author_profile_url`、`published_at`。
- `likes`、`comments`、`shares`、`plays`、`collects`，平台未提供时为 `NULL`。
- `delta_metrics`：只为本次和上次都存在的数值字段计算差值。

### 5.3 `competitor_snapshots`

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | bigint PK | 快照 ID |
| `target_type` | varchar(16) | `account` / `video` |
| `target_id` | varchar(36) index | 监控对象 ID |
| `workflow_id` | varchar(36) | 产生快照的工作流 |
| `metrics` | json | 白名单数值指标 |
| `captured_at` | timestamptz | 成功采集时间 |

同一工作流与目标只允许一个快照。删除监控对象时级联删除其快照。

### 5.4 工作流字段

复用 `workflows` 表，类型为 `competitor_refresh`。工作流 `result` 保存 `targetType`、`targetId`、触发来源和最终公开摘要；不保存 Cookie 或完整原始爬虫响应。上下文只在进程内传递依赖，持久化执行所需信息从目标表读取，因此服务重启后可重新创建任务。

## 6. API 设计

所有接口位于 `/api/v1/accounts/{account_id}/competitors`，并复用现有账号归属校验。

- `GET /videos`：返回当前账号的视频监控列表。
- `POST /videos`：请求体 `{ "contentUrl": "..." }`，创建对象并返回对象和首次刷新工作流。
- `DELETE /videos/{video_id}`：删除视频及快照；活动工作流后续写入必须安全忽略已删除对象。
- `POST /videos/{video_id}/refresh`：创建或复用活动工作流。
- `POST /videos/refresh-batch`：为没有活动工作流的全部视频创建任务，返回工作流列表。
- `GET /accounts`、`POST /accounts`、`DELETE /accounts/{competitor_id}`、`POST /accounts/{competitor_id}/refresh`、`POST /accounts/refresh-batch`：账号监控的对称接口。
- `GET /refresh-workflows/{workflow_id}`：只允许读取当前用户、当前运营账号下的 `competitor_refresh` 工作流。

新增接口使用 camelCase 响应字段，与现有前端 API 约定一致。新增对象返回 `201`；重复链接返回 `409`；非法或不支持的链接返回 `422`；不存在或越权统一返回 `404`。

## 7. 刷新与调度流程

### 7.1 手动刷新

1. 前端调用单项或批量刷新接口。
2. 服务在一个数据库事务内锁定目标行。
3. 若目标已有 `pending/running` 的活动工作流，直接返回该工作流。
4. 否则创建 `competitor_refresh` 工作流，把目标标记为 `pending` 并记录 `active_workflow_id`。
5. 事务提交后提交给 `WorkflowScheduler`，API 立即返回。
6. 前端每 2 秒轮询活动工作流；完成或失败后重新获取列表。切换运营账号或卸载页面时取消旧定时器，旧响应不得覆盖新账号。

### 7.2 自动刷新

1. FastAPI 启动时创建一个 `CompetitorPeriodicScheduler`，关闭时设置停止事件并等待扫描协程退出。
2. 扫描器按可配置间隔查询两张目标表中 `next_refresh_at <= now()` 且无活动工作流的记录。
3. repository 使用 `SELECT ... FOR UPDATE SKIP LOCKED` 分批认领，保证多个应用实例不会认领同一行。
4. 认领事务内先把 `next_refresh_at` 推进一个刷新周期，再创建工作流并记录活动 ID；提交后逐个提交工作流。
5. 提交过程异常时把目标标记为失败并清空活动 ID，但保留已推进的下次时间，避免紧密失败循环。
6. 应用重启时，启动恢复逻辑清理不存在或已终态的陈旧活动 ID；到期对象将在下一轮重新认领。

默认配置：

- `COMPETITOR_REFRESH_INTERVAL_SECONDS=21600`（6 小时）
- `COMPETITOR_SCHEDULER_SCAN_SECONDS=60`
- `COMPETITOR_SCHEDULER_BATCH_SIZE=20`

配置在 Settings 中做大于零的约束和合理下限归一化。

### 7.3 成功刷新

1. 账号目标调用 `crawl_by_creator`；视频目标调用 `crawl_by_detail`。
2. normalizer 仅从平台白名单字段生成稳定模型；缺失指标保存为 `NULL`，不猜测为零。
3. 在同一事务中读取上一成功快照、计算增量、插入新快照、更新当前数据。
4. 设置 `refresh_status=succeeded`，清除错误和活动 ID，更新成功/尝试/下次刷新时间。
5. 工作流进入 `completed`。

### 7.4 失败刷新

- 使用现有 MediaSpider 失败目录映射稳定错误代码与建议。
- 目标行更新为 `failed`，记录最近尝试时间并清空活动 ID。
- 保留已有业务字段、最后成功时间、快照和增量，不用空结果覆盖。
- 工作流进入 `failed`，前端显示“上次数据仍可查看”和安全失败原因。
- 单个对象失败不影响批量刷新中的其他对象。

## 8. 前端交互设计

页面顶部保留“监控视频 / 监控账号”切换，并增加：

- `刷新全部`：当前类型为空或全部已有活动任务时禁用。
- `添加监控`：打开与当前类型匹配的单字段链接表单。
- 最近刷新概览：成功数量、刷新中数量、失败数量。

每张卡片提供：

- 名称/标题、平台、可点击原始链接。
- 关键指标；缺失值显示 `—`，不显示虚假数字。
- 正负增量；首次成功刷新显示“首次采集”。
- 最近成功时间和刷新状态。
- `刷新`、`打开原内容/主页`、`删除`。

新增对象在首次抓取完成前展示链接、平台和“等待首次采集”。删除需要二次确认。API 失败通过现有 Toast 显示，同时卡片保留可重试入口。

## 9. 并发、一致性与安全

- 所有 repository 查询必须同时包含 `user_id` 和 `account_id`。
- 手动和自动刷新通过目标行锁与 `active_workflow_id` 去重。
- 工作流完成写入前再次验证目标仍存在且活动 ID 与本工作流一致；陈旧工作流不得覆盖新任务结果。
- 指标更新与快照插入在同一事务中完成。
- URL 只接受 HTTPS 和三个受支持平台的已知域名，解析平台由后端完成，不能信任前端传入的平台。
- API、日志、工作流结果和快照均不得包含 Cookie、请求头、浏览器状态或完整底层异常。
- 周期扫描限制批量大小并复用现有工作流并发上限，避免一次性启动过多浏览器任务。

## 10. 数据库迁移与兼容性

新增一条 Alembic 迁移创建三张表、外键、唯一约束、认领索引和快照索引。迁移只新增结构，不修改现有账号报告和工作流数据。Dashboard 的 `competitor_count` 与 `competitor_posts` 在查询时从真实监控表聚合或在新增/删除事务内同步，不能继续依赖种子值。

前端不再保留竞品演示 seed。现有其他页面和 API 不改变。后端 Python 命令与测试必须在 `starx` conda 环境运行。

## 11. 测试与验收

### 11.1 后端

- URL 平台识别、非法域名、短链与重复链接测试。
- 三个平台 detail 配置映射及账号/视频 normalizer 测试。
- 新增、列表、删除、越权和账号隔离 API 测试。
- 首次添加立即创建任务、重复刷新复用活动任务、陈旧任务不能覆盖新任务测试。
- 成功快照、缺失指标、正负增量和失败保留旧数据测试。
- `SKIP LOCKED` 认领边界、批量上限、多扫描器不重复认领测试。
- 生命周期启动/停止、到期自动提交、重启恢复测试。
- 使用 `conda run --no-capture-output -n starx pytest ...` 运行相关测试和全量回归。

### 11.2 前端

- API 路径和请求体测试。
- 添加、删除、单项刷新、全部刷新、加载/空/失败状态测试。
- 工作流轮询终止、账号切换取消旧轮询和陈旧响应保护测试。
- 源码中不存在演示 seed，缺失指标不显示伪造数字。
- 运行 `npm test` 和 `npm run build`。

### 11.3 验收场景

1. 用户切换到任一运营账号，添加一个受支持平台主页和一个内容链接，两者立即进入首次采集状态。
2. 采集成功后刷新页面，真实数据仍存在并显示最近成功时间。
3. 点击单项或全部刷新，接口立即返回、页面显示进度，完成后指标和增量更新。
4. 将测试对象的 `next_refresh_at` 调整为到期，后台扫描器无需前台请求即可创建并执行刷新工作流。
5. 模拟凭证失效或平台失败，旧数据不丢失，页面显示安全错误并可再次手动刷新。
6. 两个用户或两个运营账号不能读取、刷新或删除彼此的监控对象与工作流。
