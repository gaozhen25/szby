# MediaSpider 账号报告工作流设计

## 1. 背景

StarX 当前的账号报告只持久化五段文本，前端的相似账号、行业合规提醒、目标用户画像和爆款内容仍使用静态模拟数据。账号报告也没有进入选题推荐上下文，因此报告与后续内容生产尚未形成完整链路。

`external_project/mediaspider` 已提供 `MediaCrawlerService`，支持通过关键词和博主主页链接执行异步爬取，并以内存中的统一 `CrawlResult` 返回内容、评论和创作者数据。StarX 已取得该项目的商业使用授权；迁移时仍保留原许可证、版权声明和授权说明。

## 2. 目标

本次实现以下闭环：

1. 创建账号档案后自动创建并提交账号报告 workflow，账号创建接口不等待爬取完成。1
2. 对账号选择的小红书、抖音和快手平台，同时执行账号主页爬取和行业关键词爬取。
3. 将账号档案、知识库和跨平台爬取证据结合起来，生成结构化账号报告。
4. 在现有账号报告页面展示 workflow 进度和真实报告数据，移除相关模拟数据。
5. 让后续选题 workflow 读取最新版账号报告，并把目标用户、爆款样本、内容策略和合规限制作为选题依据。

## 3. 范围

### 3.1 本次包含

- 将 MediaSpider 的公开服务、运行时、内存 Store，以及小红书、抖音、快手的必要实现迁入 StarX 后端。
- 使用后端环境变量管理各平台 Cookie，前端和 API 响应不暴露 Cookie。
- 新增 `account_report` workflow、相关 API、数据库字段和前端轮询交互。
- 生成相似账号、行业合规提醒、目标用户画像、爆款内容、头部博主和内容策略。
- 保存结构化结论和被报告引用的精选证据。
- 选题 workflow 在报告存在时读取报告；报告缺失时保持原有降级逻辑。

### 3.2 本次不包含

- 不迁移 B 站、微博、贴吧和知乎的爬虫实现。
- 不实现视频号爬虫。
- 不长期保存完整帖子、完整评论或媒体二进制文件。
- 不在报告完成后自动生成首批选题。
- 不把 MediaSpider 拆成独立微服务或子进程服务。
- 不改造 MediaSpider 上游项目本身，也不自动同步上游更新。

## 4. 总体架构

### 4.1 模块划分

```text
app/services/mediaspider/
  __init__.py
  service.py                # 关键词爬取、博主爬取公开接口
  models.py                 # 请求、结果、枚举与异常
  runtime/
    config_scope.py         # 单次运行配置快照、应用与恢复
    collector.py            # 当前调用的内存采集、去重和结果生成
    runner.py               # 平台工厂、进程级串行锁和资源清理
  platforms/
    xhs/                    # 小红书必要实现
    douyin/                 # 抖音必要实现
    kuaishou/               # 快手必要实现
  stores/                   # 三个平台到统一内存结果的适配
  vendor/                   # 保留上游结构更安全的底层公共组件
  LICENSE                   # 原许可证、版权声明和授权说明

app/services/account_report/
  __init__.py
  models.py                 # 报告领域模型和 AI 输出契约
  evidence.py               # 跨平台归一化、去重、评分和截断
  prompts.py                # 关键词规划与完整报告提示词
  workflow.py               # account_report workflow
```

`mediaspider` 只负责采集并返回结构化原始结果，不访问 StarX 数据库，也不包含账号报告业务判断。`account_report` 负责加载业务上下文、组织爬取、精选证据、调用 AI 和持久化报告。API 路由只负责鉴权、创建或查询 workflow，以及返回报告。

### 4.2 依赖和导入约束

- 所有迁移代码使用 `app.services.mediaspider...` 包内绝对导入，不修改 `sys.path`。
- 不直接依赖 `external_project/mediaspider` 的运行路径。
- 只将实际运行小红书、抖音和快手所需的 Python 依赖加入后端依赖清单。
- 后端安装、测试和运行统一使用 `starx` conda 环境。
- MediaSpider 底层模块保留来源注释；StarX 业务适配代码遵循现有服务、日志和命名风格。

## 5. MediaSpider 服务设计

### 5.1 对外接口

迁移后的 `MediaCrawlerService` 保留两个异步关键字参数方法：

```python
async def crawl_by_keyword(*, keywords, platform, **runtime_options) -> CrawlResult
async def crawl_by_creator(*, creator_url, **runtime_options) -> CrawlResult
```

关键词方法只接受小红书、抖音和快手的标准代码或中英文别名。博主方法根据主页 URL 域名识别平台。参数模型在打开浏览器前校验 Cookie、分页、内容数量、评论数量、并发、代理和浏览器配置。

### 5.2 结果模型

```text
CrawlResult
  platform
  crawl_type
  keywords
  creator_url
  contents[]
  comments[]
  creators[]
  content_count
  comment_count
  creator_count
```

顶层结构统一，列表内部保留各平台已有字段。账号报告层通过适配器转换为自己的跨平台证据模型，避免把平台字段泄漏到报告领域和前端。

### 5.3 并发与资源清理

MediaSpider 现有实现会临时修改全局配置，因此同一进程内的所有爬取运行使用进程级异步锁串行执行。锁只限制爬虫，不限制其他 AI workflow。

每次运行必须：

1. 保存被修改的全局配置快照。
2. 绑定本次调用专属的内存 Collector。
3. 执行平台爬虫。
4. 在成功、失败或取消时关闭 BrowserContext 或 CDP 管理器。
5. 解除 Collector 并恢复配置快照。
6. 在未处理异常中仅附带脱敏的部分结果摘要：平台、模式和内容/评论/博主计数。不得附带 URL、关键词或完整内容字典；安全性优先于异常对象中的明细恢复能力。

### 5.4 隐私与数据最小化

- Cookie 只在调用期间传入爬虫，不记录到 workflow 输入、步骤输入、日志或错误消息。
- 创作者证据使用稳定哈希标识；不保存原始用户 ID、联系方式、IP 属地、性别和登录凭证。
- 报告 workflow 使用有限评论样本分析用户需求，不持久化完整评论集合。
- 不下载图片或视频；报告只保留公开封面和内容链接。

## 6. 配置设计

新增以下 `Settings` 配置，并继续使用 `STARX_` 前缀：

```text
MEDIASPIDER_XHS_COOKIES
MEDIASPIDER_DOUYIN_COOKIES
MEDIASPIDER_KUAISHOU_COOKIES
MEDIASPIDER_HEADLESS=true
MEDIASPIDER_ENABLE_CDP_MODE=false
MEDIASPIDER_CDP_CONNECT_EXISTING=false
MEDIASPIDER_CDP_DEBUG_PORT=9222
MEDIASPIDER_CUSTOM_BROWSER_PATH=
MEDIASPIDER_MAX_NOTES_COUNT=30
MEDIASPIDER_MAX_COMMENTS_COUNT=10
MEDIASPIDER_MAX_CONCURRENCY=1
MEDIASPIDER_ENABLE_COMMENTS=true
MEDIASPIDER_ENABLE_SUB_COMMENTS=false
MEDIASPIDER_ENABLE_IP_PROXY=false
MEDIASPIDER_IP_PROXY_PROVIDER=kuaidaili
MEDIASPIDER_STATIC_PROXY_URL=
```

配置读取层按平台返回运行配置的安全副本。任何日志和 Pydantic 序列化结果都必须排除或遮蔽 Cookie。

## 7. 账号报告 workflow

### 7.1 创建与去重

workflow 类型为 `account_report`。创建账号时，在账号及默认报告记录提交成功后创建 workflow 记录并提交给现有 `WorkflowScheduler`。账号创建响应保持为 `AccountSchema`，不等待 workflow。

同一账号存在 `pending` 或 `running` 的 `account_report` workflow 时，自动触发或手动重新生成都返回已有 workflow，不创建重复任务。

### 7.2 执行阶段

| 进度 | 阶段 | 行为 |
|---:|---|---|
| 5% | `context_loading` | 读取账号、知识库、主页链接和平台配置 |
| 10% | `keyword_planning` | 根据行业、产品、定位、目标人群和知识库生成检索词 |
| 15%–40% | `creator_crawling` | 对支持平台的账号主页执行博主爬取 |
| 40%–65% | `keyword_crawling` | 对支持平台执行关键词爬取 |
| 70% | `evidence_normalization` | 归一化、去重、互动评分和精选证据 |
| 75%–90% | `report_analysis` | 生成并校验完整结构化报告 JSON |
| 95%–100% | `report_persistence` | 原子更新报告并完成 workflow |

关键词规划输出少量、可解释、与账号定位相关的词，避免对每个平台发起过多搜索。三个支持平台按 MediaSpider 的串行约束执行。每个平台同时具备主页链接和 Cookie 时执行主页爬取；具备 Cookie 时执行关键词爬取。

### 7.3 降级与失败

- 视频号写入 `sourceMeta.unsupportedPlatforms`，不执行爬取。
- 某个支持平台缺少 Cookie、链接无效或运行失败时，记录到 `sourceMeta.failedPlatforms`，继续其他平台。
- 只选择视频号的账号允许使用账号档案和知识库生成无外部采集的降级报告，并明确标记数据来源限制。
- 账号包含支持平台但所有支持平台均采集失败时，workflow 失败，不生成伪装成数据驱动的报告。
- AI 返回空值、禁止标记或不符合结构化契约时，workflow 失败。
- 任一失败都不覆盖上一版已完成报告；首次生成失败时保留初始化空报告和失败 workflow。

## 8. 证据归一化

### 8.1 内容证据

`ContentEvidence` 包含平台、内容哈希或公开内容 ID、标题、摘要、脱敏作者、公开链接、封面链接、发布时间、点赞、收藏、评论、分享、来源关键词和互动分数。

数字规范化必须兼容整数、数字字符串以及“万”“万+”等平台展示形式。互动分数由可用的点赞、收藏、评论和分享加权计算；缺失指标按零处理，同时保留原始公开指标供展示。相同平台和内容标识只保留一条记录。

### 8.2 创作者证据

`CreatorEvidence` 包含平台、创作者哈希、脱敏名称、粉丝数、作品数、累计互动、命中内容数和代表内容。相似账号候选不得包含当前账号自身的创作者哈希。

### 8.3 样本截断

- 相似账号最多保存 20 个。
- 爆款内容最多保存 20 条。
- 头部博主最多保存 10 个。
- 评论只作为 workflow 临时分析材料，按内容和平台限制数量，不写入报告表。

截断发生在 AI 调用前，保证提示词体积和数据库 JSON 字段可控。

## 9. 报告数据模型

现有五个文本字段继续保留，作为兼容摘要：

```text
competitors
prohibited_words
target_users
hot_content
top_bloggers
```

`reports` 表新增：

```text
similar_accounts JSON
compliance_rules JSON
target_user_profile JSON
hot_contents JSON
top_blogger_details JSON
content_strategy JSON
source_meta JSON
report_version INTEGER
generated_at TIMESTAMPTZ NULL（UTC）
```

结构化字段语义：

- `similarAccounts`：候选账号、相似理由、公开指标和代表内容。
- `complianceRules`：风险等级、风险表达、原因、建议替换表达和适用平台。
- `targetUserProfile`：人群概括、核心需求、内容偏好、购买顾虑和转化触点。
- `hotContents`：爆款证据、互动指标和入选原因。
- `topBloggers`：行业博主及其内容特征。
- `contentStrategy`：内容支柱、表达风格、差异化机会和应避免方向。
- `sourceMeta`：采集平台、关键词、样本数、失败和降级信息、生成时间。

报告 AI 必须一次返回完整 JSON。Pydantic 契约校验通过后，在一个数据库事务中同时更新兼容摘要和结构化字段，避免出现半新半旧的数据。

## 10. API 设计

### 10.1 报告读取

`GET /accounts/{account_id}/report` 保留现有路径，响应增加结构化字段、`reportVersion` 和 `generatedAt`。旧文本字段继续返回。

### 10.2 workflow 接口

```text
POST /accounts/{account_id}/report/workflows
GET  /accounts/{account_id}/report/workflows/latest
GET  /accounts/{account_id}/report/workflows/{workflow_id}
```

`POST` 创建或返回当前进行中的 workflow。两个 `GET` 只允许访问当前用户拥有的账号和 workflow。workflow 响应复用现有状态、进度、当前阶段、错误和结果字段的命名规则。

原有逐段编辑和逐段 AI 分析接口暂时保留兼容；新版“重新生成”统一调用完整报告 workflow，避免各段基于不同批次证据生成。

## 11. 前端设计

### 11.1 状态与轮询

`useStarxApp` 新增当前账号报告 workflow 状态和独立轮询控制，复用选题 workflow 已有的运行编号与账号校验模式：

- 创建账号并切换成功后，查询 latest workflow 并进入报告页。
- 手动重新生成调用 workflow 创建接口。
- `pending` 或 `running` 时按固定间隔查询状态。
- 完成后停止轮询并重新读取报告。
- 失败后停止轮询，保留旧报告并显示错误。
- 切换账号、退出登录或组件卸载时取消旧定时器，旧账号响应不得覆盖当前账号。

### 11.2 页面展示

`AccountReport.jsx` 移除相似账号、合规规则和爆款内容的静态数组。页面读取结构化报告并展示：

- 顶部 workflow 阶段、进度、更新时间和重新生成按钮。
- 相似账号概览和最多 20 个候选账号详情。
- 行业合规提醒及替换建议。
- 目标用户画像、需求、偏好和顾虑。
- 爆款内容卡片、原始链接和互动指标。
- 采集失败、视频号不支持和无外部证据等来源说明。

旧报告存在且新 workflow 正在运行时继续显示旧报告，只在顶部展示更新进度。首次生成尚未完成时显示报告骨架和当前阶段，不显示模拟内容。

## 12. 选题 workflow 联动

`WorkflowStore.topic_recommendation_context()` 增加最新版报告上下文，包含：

- 目标用户画像摘要。
- 内容策略和差异化机会。
- 相似账号的内容特征。
- 爆款内容标题、平台、指标和入选原因。
- 合规风险表达和应避免方向。
- 报告来源与生成时间。

选题提示词明确要求：

1. 基于报告证据提炼方向，不直接复制竞品标题。
2. 选题服务账号目标用户和转化目标。
3. 遵守报告中的行业合规限制。
4. 报告不存在时继续使用账号档案、知识库和已有选题，不阻塞生成。

报告完成后不自动创建选题 workflow；用户进入选题中心或点击换一批时才执行现有选题生成流程。

## 13. 测试策略

### 13.1 MediaSpider 单元测试

- 平台别名、博主 URL、关键词和 Cookie 校验。
- 全部运行参数映射。
- 内存 Collector 去重、任务隔离和隐私字段白名单。
- 配置作用域在成功、异常和取消后恢复。
- 浏览器资源清理和部分结果异常。
- 进程内不同服务实例串行执行。
- 三个平台 Store 的内存模式适配。

测试使用伪造爬虫和固定平台响应，不连接真实平台。

### 13.2 workflow 与持久化测试

- 创建账号自动创建且只创建一个报告 workflow。
- 手动重复触发返回运行中的 workflow。
- 三个平台双路采集参数正确。
- 视频号降级、单平台失败和全部平台失败。
- 证据数字规范化、去重、排序和截断。
- AI JSON 契约校验和原子报告更新。
- 失败不覆盖旧报告。
- API 鉴权、状态查询和结构化报告响应。
- 选题上下文包含报告，报告缺失时保持兼容。

### 13.3 前端测试

- API 路径和请求方法。
- 创建账号后的 latest workflow 接管。
- 轮询完成、失败、切换账号和卸载清理。
- 报告页不再引用 mock 数据。
- 旧报告加更新进度、首次生成骨架和部分失败提示。

所有后端测试命令使用 `conda run -n starx pytest ...`，最终执行后端完整测试、前端 `npm test` 和 `npm run build`。

## 14. 运维与安全

- 部署环境必须提供目标平台 Cookie，并按秘密配置管理，不写入仓库。
- Cookie 缺失只出现在平台级安全错误中，错误内容不得回显 Cookie。
- 浏览器模式、可执行文件路径、CDP、代理和采集上限全部可配置。
- 日志记录 workflow、平台、阶段、耗时和计数，不记录 Cookie、评论原文和完整 AI 提示词。
- workflow 服务重启时沿用现有启动恢复策略，将遗留的 `pending`、`running` 任务标记失败；用户可以重新生成。
- 上游 MediaSpider 更新通过人工审查后定向同步，避免覆盖 StarX 的包边界、隐私约束和测试。

## 15. 验收标准

1. 新建小红书、抖音或快手账号后，账号创建接口快速返回，后台出现唯一的 `account_report` workflow。
2. 报告页能展示真实进度，完成后显示结构化相似账号、合规提醒、目标用户、爆款内容和内容策略。
3. 爬取结果不写入 CSV、JSON 文件或 MediaSpider 自带数据库，完整原始评论不进入 StarX 数据库。
4. 视频号账号可以完成降级报告；部分平台失败不会丢失其他平台结果。
5. 全部支持平台采集失败或 AI 报告无效时，workflow 失败且旧报告不被覆盖。
6. 重新生成不会并发创建同一账号的重复任务。
7. 选题 workflow 在报告存在时引用报告证据与合规限制，报告缺失时仍可正常生成。
8. Cookie 不出现在 API、workflow JSON、日志和测试快照中。
9. 后端完整测试、前端测试和构建全部通过。
