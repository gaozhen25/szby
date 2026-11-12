# 竞品监控 API 与调度说明

## 1. 功能边界

竞品监控按当前登录用户和运营账号隔离，支持小红书、抖音、快手的公开账号主页与公开内容详情链接。链接必须是 HTTPS，并由后端根据已知域名识别平台。

添加监控对象后会立即创建一次 `competitor_refresh` 工作流。用户也可以刷新单个对象或当前类型的全部对象；后台周期扫描器使用相同工作流自动刷新到期对象。删除监控对象会级联删除对应指标快照。

账号监控每次只采集一个博主主页及其返回顺序中的前 10 条视频，并明确关闭一级、二级评论采集。每次成功刷新都会把账号指标和当次视频集合写入独立快照。首次刷新只建立视频基线；后续刷新按平台内容 ID（缺失时按内容链接）与上一份快照比较，并通过账号接口的 `newVideos` 返回本次新增视频。每条新增视频包含原平台 `contentUrl`，前端可直接跳转查看。

## 2. API

所有接口都位于 `/api/v1`，并要求登录态。

### 2.1 监控账号

- `GET /accounts/{account_id}/competitors/accounts`：列出监控账号。
- `POST /accounts/{account_id}/competitors/accounts`：添加监控账号，请求体为 `{ "profileUrl": "https://..." }`，返回 `target` 和首次刷新 `workflow`。
- `DELETE /accounts/{account_id}/competitors/accounts/{target_id}`：删除监控账号，成功返回 204。
- `POST /accounts/{account_id}/competitors/accounts/{target_id}/refresh`：刷新单个账号，返回工作流。
- `POST /accounts/{account_id}/competitors/accounts/refresh-batch`：刷新当前运营账号下全部监控账号，返回 `workflows`。

### 2.2 监控视频

- `GET /accounts/{account_id}/competitors/videos`：列出监控视频。
- `POST /accounts/{account_id}/competitors/videos`：添加监控视频，请求体为 `{ "contentUrl": "https://..." }`，返回 `target` 和首次刷新 `workflow`。
- `DELETE /accounts/{account_id}/competitors/videos/{target_id}`：删除监控视频，成功返回 204。
- `POST /accounts/{account_id}/competitors/videos/{target_id}/refresh`：刷新单个视频，返回工作流。
- `POST /accounts/{account_id}/competitors/videos/refresh-batch`：刷新当前运营账号下全部监控视频，返回 `workflows`。

### 2.3 刷新状态

- `GET /accounts/{account_id}/competitors/refresh-workflows/{workflow_id}`：读取刷新工作流状态。

对象的 `refreshStatus` 取值为 `pending`、`running`、`succeeded`、`failed`。工作流使用统一工作流状态；前端轮询至 `completed`、`failed` 或 `cancelled` 后重新加载列表。

`deltaMetrics` 是当前成功快照相对上一次成功快照的指标差值。首次成功刷新没有可比较快照，因此为空对象。账号对象的 `latestVideos` 是最近一次成功刷新的前 10 条视频，`newVideos` 是相对上一份视频基线新增的条目。刷新失败只更新错误和调度状态，不覆盖最后一次成功指标或视频集合。

## 3. 自动刷新

应用启动时会启动进程内周期扫描器，关闭时等待扫描器安全退出。数据库中的 `next_refresh_at` 是调度事实来源；扫描器通过行锁和 `SKIP LOCKED` 原子认领到期对象，并用 `active_workflow_id` 防止手动刷新和定时刷新重复执行。

可配置项：

```dotenv
STARX_COMPETITOR_REFRESH_INTERVAL_SECONDS=21600
STARX_COMPETITOR_SCHEDULER_SCAN_SECONDS=60
STARX_COMPETITOR_SCHEDULER_BATCH_SIZE=20
STARX_COMPETITOR_WORKFLOW_STALE_SECONDS=7200
STARX_COMPETITOR_WORKFLOW_HEARTBEAT_SECONDS=60
```

- `REFRESH_INTERVAL_SECONDS`：成功或失败后到下一次自动刷新的间隔，默认 6 小时。
- `SCHEDULER_SCAN_SECONDS`：扫描数据库的间隔，默认 60 秒。
- `SCHEDULER_BATCH_SIZE`：单次最多认领的账号和视频总数，默认 20。
- `WORKFLOW_STALE_SECONDS`：`pending/running` 工作流无更新后判定为失联并重新调度的时间，默认 2 小时。
- `WORKFLOW_HEARTBEAT_SECONDS`：运行中刷新任务的续租间隔，默认 60 秒，应显著小于失联阈值。

多实例部署时可以同时启动扫描器，行锁会避免同一目标被重复认领。工作流提交失败会把对象标记为失败并清除活动任务，后续仍可手动刷新或等待下个周期。异常退出留下的活动任务超过失联阈值后会被安全标记失败，并在到期时重新认领。

## 4. 数据与安全

- 只保存公开资料、当前指标、指标快照和安全错误信息。
- Cookie 从后端 Cookie 池读取，不进入 API、数据库、工作流载荷或日志。
- 不向前端暴露底层爬虫异常、请求头、浏览器状态和认证信息。
- 同一链接只在同一运营账号内去重；不同用户和运营账号之间不能读取、刷新或删除彼此的对象和工作流。

## 5. 部署检查

```bash
conda run -n starx alembic upgrade head
conda run -n starx pytest tests -q
conda run -n starx uvicorn app.main:app
```

生产环境还需要为目标平台配置有效 Cookie 池。没有对应平台凭证时，刷新工作流会失败并保留旧指标。
