# 账号报告采集进度与平台诊断设计

## 1. 背景与问题定位

账号报告 workflow 已能轮询展示总进度，但目前只返回 `currentStage` 和百分比。用户无法判断正在采集哪个平台、博主或关键词，也无法知道某个平台为何失败。所有支持平台采集失败时，后端只保留统一错误“所有支持平台采集失败，旧报告已保留”，导致排查成本高、等待过程缺少反馈。

本次故障已通过最小化真实探测定位为三个独立问题：

1. 小红书关键词采集进入签名阶段后失败。项目对 `xhshow` 的兼容补丁仍使用旧版 `build_payload_array` 参数签名，而当前 `xhshow 0.1.0` 增加了 `hex_md5_path` 参数，最终触发 `TypeError: ... got multiple values for argument 'sign_state'`。
2. 抖音 Cookie 未通过登录态校验，运行时转入登录弹窗流程，等待“登录”按钮 30 秒后超时。该情况应被归类为“登录凭证失效或未生效”，而不是普通浏览器超时。
3. 当前账号档案中的小红书和抖音主页都使用 `growth` 作为用户标识，不是可采集的真实博主主页。即使关键词采集恢复，博主采集仍应给出“主页链接无效或账号不存在”的独立提示。

## 2. 目标

1. 修复小红书签名兼容问题，并用自动化测试覆盖当前 `xhshow` 调用约定。
2. 在不引入 WebSocket 或 SSE 的前提下，复用现有 1.5 秒 workflow 轮询展示实时采集活动。
3. 前端展示当前平台、当前动作、博主主页的安全摘要、关键词、已发现内容标题和累计数量。
4. 将平台失败转换为稳定、可操作、无敏感信息的错误代码与中文提示。
5. 所有平台失败时，最终错误包含平台级摘要，同时继续保留旧报告。
6. Cookie、请求头、原始用户 ID、异常原文和完整主页查询参数不得进入数据库、API、日志或前端。

## 3. 非目标

- 不新增 WebSocket、SSE、Redis Pub/Sub 或独立事件服务。
- 不在前端配置、读取或展示 Cookie。
- 不展示评论采集的逐条内容，避免高频写库和敏感内容暴露。
- 不把浏览器内部步骤、选择器、堆栈或底层异常原文暴露给用户。
- 不修改账号报告的证据筛选、AI 分析和报告持久化契约。
- 不自动修正无效主页链接；由用户回到账号档案填写真实链接。

## 4. 方案选择

### 4.1 采用方案：结构化活动快照加现有轮询

workflow 在 `resultPayload.crawlProgress` 中保存一个有界快照，现有 workflow 查询接口原样返回。前端每 1.5 秒轮询时渲染当前活动和最近活动。

该方案的优点：

- 复用现有 API、鉴权、轮询和数据库模型，不引入长连接基础设施。
- 页面刷新、网络短暂中断或切换账号后仍可恢复进度。
- 失败结果可持久化，便于用户回看和排查。
- 采集事件频率受控，不会把每个浏览器动作写入数据库。

### 4.2 未采用方案

- 仅增加阶段文案：改动最小，但仍无法展示平台、博主、内容和失败原因。
- SSE 或 WebSocket：实时性更高，但本次采集本身以秒为单位，现有 1.5 秒轮询足够；引入连接管理和多实例广播不符合本次范围。

## 5. 模块设计

### 5.1 采集进度领域模型

在 `app/services/account_report/crawl_progress.py` 中定义账号报告专用的进度模型和构造器，避免继续扩大 workflow 主文件。

```text
CrawlProgressSnapshot
  current                 当前活动，可为空
  activities[]            最近活动，最多 30 条
  platformSummaries[]     每个平台的状态与累计计数

CrawlActivity
  sequence                workflow 内单调递增序号
  stage                   creator | keyword | content | comments | platform | workflow
  status                  pending | running | completed | failed | skipped
  platform                xhs | dy | ks
  platformName            小红书 | 抖音 | 快手
  action                  稳定动作代码
  message                 面向用户的中文文案
  subject                 安全摘要，如博主名称、脱敏主页或关键词
  contentTitle            已发现内容标题的清洗与截断值
  contentCount            当前平台累计内容数
  creatorCount            当前平台累计博主数
  commentCount            当前平台累计评论数
  occurredAt              UTC ISO 8601 时间

PlatformCrawlSummary
  platform
  platformName
  status                  pending | running | completed | partial | failed | skipped
  contentCount
  creatorCount
  commentCount
  failureCode             稳定错误代码，可为空
  failureMessage          安全中文提示，可为空
```

活动数组采用环形截断语义，只保留最近 30 条。相同平台、动作、状态和主体的连续事件合并更新计数，防止关键词分页和评论回调造成高频膨胀。

### 5.2 MediaSpider 事件边界

`MediaCrawlerService` 的两个公开方法新增可选 `on_progress` 回调。该回调只接收 `CrawlerProgressEvent` 白名单模型，不接收 `CrawlerRunConfig`、Cookie、浏览器对象或原始异常。

运行时在以下边界发出事件：

1. 等待进程级爬虫锁。
2. 开始平台运行。
3. 开始博主主页采集或关键词搜索。
4. Collector 首次保存博主。
5. Collector 保存内容时，按受控频率报告标题和累计计数。
6. 评论累计数量变化时只报告计数，不报告评论文本。
7. 平台运行完成、失败或取消。

事件回调异常不得中断爬虫。回调实现只负责把安全事件转成账号报告进度快照并调用 `WorkflowStore.update_progress()`。

### 5.3 workflow 持久化

账号报告 workflow 为每个平台初始化 `PlatformCrawlSummary`，并在博主采集、关键词采集和平台失败处更新快照。快照写入：

```json
{
  "crawlProgress": {
    "current": {},
    "activities": [],
    "platformSummaries": []
  }
}
```

继续使用 `WorkflowRecord.result_payload`，不新增数据库表或迁移。`WorkflowStore.update_progress()` 已按字典合并 `result_payload`，因此完成后的 `reportVersion` 与 `crawlProgress` 可以共存。

平台爬取串行执行时，百分比仍保持单调不回退。细节更新可以保持同一百分比，只刷新 `updatedAt` 与 `resultPayload`。

### 5.4 安全错误分类

在 `app/services/mediaspider/error_classifier.py` 中完成底层异常到安全错误的单向转换。分类只在进程内检查异常类型和有限的已知调用路径/消息片段；持久化结果不包含原始异常。

稳定错误代码与提示：

| 错误代码 | 用户提示 | 建议动作 |
|---|---|---|
| `credentials_missing` | 未配置该平台登录凭证 | 后端配置 Cookie 并重启服务 |
| `credentials_expired` | 登录凭证失效或未生效 | 更新该平台 Cookie 并重启服务 |
| `creator_url_invalid` | 博主主页链接无效或账号不存在 | 在账号档案填写真实完整主页链接 |
| `platform_blocked` | 平台触发访问验证，暂时无法采集 | 稍后重试或检查运行环境 |
| `browser_timeout` | 平台页面响应超时 | 稍后重试 |
| `runtime_incompatible` | 平台采集组件不兼容 | 后端修复或升级采集组件 |
| `crawler_failed` | 平台采集失败 | 稍后重试并查看服务日志中的安全诊断 ID |

本次抖音“登录态校验失败后进入弹窗并超时”必须归类为 `credentials_expired`，不能归类为 `browser_timeout`。缺失 Cookie 在打开浏览器前归类为 `credentials_missing`。

每个平台的博主采集和关键词采集分别记录结果。只要有一次成功，平台摘要可以为 `partial`，workflow 继续生成报告；所有支持平台的所有采集均失败时，workflow 失败，错误文案为：

```text
所有支持平台采集失败，旧报告已保留。小红书：<安全原因>；抖音：<安全原因>
```

### 5.5 小红书签名兼容修复

`_patch_xhshow_a3_hash()` 不再假定固定位置参数签名。兼容层先检查 `CryptoProcessor.build_payload_array` 的参数，分别支持旧版和当前包含 `hex_md5_path` 的版本：

- 当前版本调用原方法时完整透传 `hex_parameter`、`hex_md5_path`、`a1_value`、`app_identifier`、`string_param`、`timestamp` 和 `sign_state`。
- GET 的 A3 修复使用传入的 `hex_md5_path` 或完整 URL 查询参数计算值，不改变 POST 的原始结果。
- monkey patch 增加幂等标记，模块重复导入时不重复包裹。
- 若依赖出现未知签名，在启动或首次签名时抛出可分类的兼容错误，而不是产生含糊的参数冲突。

自动化测试用伪造的新旧签名类验证参数透传和 GET/POST 行为，不发起真实平台请求。

## 6. 前端交互设计

### 6.1 报告页状态卡

现有顶部 workflow 状态卡扩展为两层：

- 第一层保留阶段名称、总进度百分比和进度条。
- 第二层显示当前活动，例如“正在采集小红书博主：账号主页”“正在搜索抖音关键词：上海探店”“已发现内容：周末双人餐实测”。

状态卡下方显示最近 5 条活动，按时间倒序排列。每条包括平台标签、状态图标、动作描述和累计计数。内容标题最多展示 60 个字符，超出省略。

### 6.2 平台摘要

活动列表下显示小红书、抖音、快手的平台摘要：

- 运行中：显示当前动作和累计内容数。
- 完成：显示内容、博主、评论计数。
- 部分成功：显示已有计数和未成功步骤的原因。
- 失败：显示安全失败原因和可操作建议。
- 跳过：显示未配置凭证或平台暂不支持。

旧报告存在时，进度卡置于旧报告上方，旧报告继续可读。首次生成时，进度卡与骨架屏同时显示。失败后保留活动和平台摘要，不把真实错误替换为统一的“请稍后重试”。

### 6.3 前端兼容与降级

前端通过纯函数解析 `workflow.resultPayload.crawlProgress`。旧 workflow 或后端尚未返回该字段时，继续使用 `currentStage` 和 `progress`，不出现空白或运行时错误。

平台提示文案由后端提供，前端只负责展示；前端保留稳定错误代码用于选择建议图标，不自行根据英文异常文本猜测原因。

## 7. 数据流

```text
平台爬虫 / 内存 Collector
        │ 安全 CrawlerProgressEvent
        ▼
MediaCrawlerService on_progress
        │
        ▼
AccountReportCrawlProgressTracker
        │ 有界 CrawlProgressSnapshot
        ▼
WorkflowStore.update_progress(result_payload={crawlProgress})
        │
        ▼
GET report workflow（现有 1.5 秒轮询）
        │
        ▼
AccountReport 进度卡、最近活动、平台摘要
```

## 8. 隐私与可靠性

- Cookie 字段继续使用 `SecretStr`，不进入进度事件和序列化结果。
- `subject` 不保存完整查询参数；博主 URL 只显示平台名和安全路径摘要，原始用户 ID 必须脱敏或省略。
- 内容标题移除 URL、手机号、邮箱、联系方式、凭证形态文本，并限制长度。
- 评论只记录数量，绝不进入实时活动。
- 底层异常只在服务端安全日志中记录分类、异常类型和诊断 ID；不记录异常原文中可能携带的请求头。
- 进度回调失败不影响采集；数据库暂时不可写时，采集仍继续，下一次成功更新覆盖当前快照。
- workflow 取消后不再写入进度，爬虫资源清理保持现有保证。

## 9. 测试策略

### 9.1 后端

1. `xhshow` 新旧方法签名均能正确透传参数；当前版本不再触发重复 `sign_state`。
2. GET A3 修复与 POST 原行为分别正确，补丁重复应用保持幂等。
3. Collector 按内容/博主/评论边界发出白名单事件，事件不含 Cookie、原始用户 ID和评论文本。
4. 活动最多保留 30 条，连续同类事件合并，序号单调递增。
5. 进度快照与 workflow 的其他 `resultPayload` 字段合并而非覆盖。
6. 抖音登录弹窗超时归类为 `credentials_expired`；普通页面超时归类为 `browser_timeout`。
7. 无效博主主页归类为 `creator_url_invalid`，关键词采集仍可独立继续。
8. 所有平台失败时，workflow 错误包含各平台安全原因；任何响应和日志快照不含 Cookie。
9. 部分平台或部分步骤成功时继续生成报告，并在平台摘要中标记 `partial`。

后端测试与运行统一使用 `conda run -n starx pytest ...`。

### 9.2 前端

1. 旧 workflow 无 `crawlProgress` 时继续显示现有阶段与百分比。
2. 当前活动、最近 5 条活动和平台摘要正确渲染。
3. 活动标题截断，失败原因和建议可见。
4. 轮询更新只影响当前账号，切换账号后旧响应不能覆盖新页面。
5. workflow 失败后仍保留进度明细和旧报告。
6. 组件和 API 测试中不出现 Cookie 字段或凭证文本。

## 10. 验收标准

1. 小红书最小关键词采集不再因 `build_payload_array` 参数冲突失败。
2. 账号报告生成期间，用户最迟在下一次 1.5 秒轮询看到当前平台和采集动作。
3. 发现公开内容后，页面能显示安全标题摘要与累计内容数。
4. 抖音 Cookie 失效时，页面明确提示更新抖音登录凭证，不再只显示“全部采集失败”。
5. 博主主页无效时，页面明确引导用户回账号档案修改链接；关键词采集不被该失败阻断。
6. 全部采集失败仍不覆盖旧报告，且失败详情在刷新页面后仍可查看。
7. 后端全量测试和前端全量测试通过，所有新增安全测试通过。
