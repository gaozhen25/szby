# MediaSpider Cookie 池设计

## 背景与目标

当前后端通过 `Settings` 从三个 `STARX_MEDIASPIDER_*_COOKIES` 环境变量读取单条平台 Cookie，再由账号报告 workflow 将 Cookie 注入 MediaSpider 运行参数。这种方式无法轮换多个账号凭证，且把爬虫凭证绑定到了进程级环境配置。

本次改造将 Cookie 唯一来源调整为后端目录下的 `cookies/cookies.json`。每次账号报告 workflow 启动时读取一次文件，为本次 workflow 创建局部 Cookie 池快照；Cookie 内容不得进入全局配置或长期缓存。每个平台按轮询顺序选取 Cookie，明确发生认证失效时自动换用下一条，直至成功或该平台池耗尽。

## 范围

本次包含：

- 小红书、抖音、快手三个现有 MediaSpider 平台的 Cookie 加载。
- Cookie JSON 的结构校验、安全错误处理和局部生命周期。
- 跨 workflow 的轮询游标，以及单次爬取的认证失败切换。
- 账号报告 workflow 中博主爬取和关键词爬取的 Cookie 池接入。
- `scripts/media_spider.py` 直接爬取入口的 Cookie 池接入与硬编码凭证清理。
- 删除三个 Cookie 环境变量及对应文档。
- 单元测试和账号报告 workflow 回归测试。

本次不包含：

- 自动探测 Cookie 到期时间。
- 修改或回写 `cookies/cookies.json`。
- 将 Cookie 池存入数据库、Redis 或远程密钥服务。
- 对超时、平台风控、URL 错误等非认证错误自动切换 Cookie。

## 配置文件契约

固定读取路径为后端项目根目录下的 `cookies/cookies.json`，即 `BASE_DIR / "cookies" / "cookies.json"`。文件结构如下：

```json
{
  "xhs": ["cookie-a", "cookie-b"],
  "dy": ["cookie-c"],
  "ks": []
}
```

约束如下：

- 顶层必须是 JSON 对象。
- 仅支持 `xhs`、`dy`、`ks` 三个平台键；缺失的平台按空池处理。
- 每个平台值必须是字符串数组。
- Cookie 字符串在使用前去除首尾空白，空字符串被忽略。
- 同一平台完全相同的 Cookie 在快照内去重，并保持文件中的首次出现顺序。
- 文件不存在、JSON 无法解析或字段类型不合法时，抛出不包含文件内容和 Cookie 的安全配置异常。
- 加载器与异常字符串不得实现会输出 Cookie 内容的 `repr` 或序列化接口。

`cookies/cookies.json` 是运行时敏感配置，由部署方维护。本次代码不得创建、修改或提交用户现有的该文件。

## 架构与组件

### Cookie 池加载器

新增 `app/services/mediaspider/cookie_pool.py`，集中承担以下职责：

- 从固定路径读取并解析 JSON。
- 校验平台映射和 Cookie 数组。
- 生成本次 workflow 独享的不可变 Cookie 快照。
- 为指定平台构造一次爬取可使用的轮询序列。

加载器不挂到全局 `Settings`，也不在模块级变量保存 JSON 或 Cookie 列表。

### 轮询游标

进程内允许常驻的状态只有每个平台的下一个起始位置，例如 `xhs -> 2`，不得保存 Cookie 本身。游标访问使用线程锁保护，以免并发 workflow 领取到相同起始位置。

一次爬取开始时，使用平台当前游标确定首条 Cookie，并立即将游标推进一位。若发生认证失效，继续沿快照环形顺序尝试剩余 Cookie；同一次爬取中每条 Cookie 最多尝试一次。

游标是尽力而为的进程内公平轮询：服务重启后从初始位置重新开始，不要求跨进程或跨重启保持。

### 调用入口集成

账号报告 workflow 在 `execute()` 取得账号上下文并解析出待爬平台后，读取 `cookies/cookies.json` 一次。快照保存在 `execute()` 的局部变量中，只存活于本次 workflow。

现有 `Settings.mediaspider_runtime_options(platform)` 保留非敏感运行参数的组装能力，但不再读取或返回 Cookie。workflow 为每一次博主或关键词爬取从快照领取 Cookie，再把 Cookie 合并进该次调用参数。

为避免博主、关键词和直接脚本复制重试逻辑，Cookie 池模块提供统一的异步调用辅助函数：

1. 获取该平台本次爬取的候选 Cookie 顺序。
2. 使用当前 Cookie 调用 MediaSpider 服务。
3. 成功则立即返回结果。
4. 捕获 `CrawlerExecutionError` 且 `failure.code == "credentials_expired"` 时尝试下一条。
5. 其他 `CrawlerExecutionError` 或其他异常立即向现有失败处理逻辑传播。
6. 候选 Cookie 全部认证失效后，传播最后一个安全分类异常。

若平台池为空，沿用现有 `credentials_missing` 和“未配置平台凭证”语义，不启动该平台爬取。

`scripts/media_spider.py` 同样在 `main()` 开始时调用加载器创建局部快照，并通过统一辅助函数执行爬取；脚本中不得保留任何 Cookie 字符串常量。

## 数据流

1. 账号报告 workflow 启动并读取账号上下文。
2. workflow 解析需要采集的平台。
3. 加载器从磁盘读取一次 `cookies/cookies.json`，校验后创建局部快照。
4. workflow 从 `Settings` 获取不含 Cookie 的 MediaSpider 公共运行参数。
5. 每次博主或关键词爬取向快照请求该平台的轮询候选序列。
6. workflow 使用第一条 Cookie 调用 MediaSpider。
7. 若认证失效，依次切换剩余 Cookie；成功或遇到非认证错误后停止。
8. workflow 结束，局部快照失去引用；进程仅保留不含凭证的整数游标。

## 错误与安全策略

- Cookie 文件整体损坏属于 workflow 配置错误，失败信息只描述“Cookie 池配置不可用”，不包含解析附近文本、原始 JSON 或 Cookie。
- 单个平台为空只影响该平台，使用现有缺少凭证分类；其他平台仍可继续。
- 只有明确的 `credentials_expired` 分类触发换 Cookie，防止对网络错误、浏览器错误或风控错误造成重复请求。
- 最后一条 Cookie 认证失效后保留现有公开失败分类，不暴露尝试次数、Cookie 片段或底层异常。
- 测试桩和断言可使用明确的假 Cookie，但生产日志、异常、进度事件、模型序列化和 `repr` 均不得输出真实 Cookie。
- 删除 `Settings` 的三个 `SecretStr` Cookie 字段、字段映射及 `.env.example`/README 中的环境变量说明，避免出现双重配置来源。

## 测试策略

### Cookie 池单元测试

- 正确加载三个平台并过滤空字符串。
- 缺失平台映射为空池。
- 同平台重复 Cookie 去重且保持顺序。
- 文件不存在、非法 JSON、顶层非对象、平台值非数组、数组元素非字符串时安全失败。
- 连续创建 workflow 快照时重新读取文件，证明 Cookie JSON 未被模块级缓存。
- 多次领取时起始 Cookie 按平台轮询，且各平台游标互不影响。
- 任何异常和对象表示都不包含测试 Cookie。

### workflow 测试

- workflow 开始时只读取一次 Cookie 文件。
- 博主和关键词爬取均从池中领取 Cookie。
- 第一条认证失效时使用下一条并成功。
- 所有 Cookie 认证失效时返回现有凭证失效失败。
- 非认证分类失败时不切换 Cookie。
- 空池沿用缺少凭证处理，其他平台不受影响。
- `Settings.mediaspider_runtime_options()` 返回值不再包含 `cookies`。

### 直接脚本测试

- AST 检查确认脚本不存在 Cookie 字符串变量。
- 注入测试池后，脚本把池中 Cookie 传给爬虫服务。
- 脚本与 workflow 共用认证失效轮换辅助函数。

### 验证命令

后端所有 Python 测试必须使用项目指定环境：

```bash
conda run -n starx pytest tests/test_mediaspider_cookie_pool.py tests/test_mediaspider_config.py tests/test_account_report_workflow.py -q
conda run -n starx pytest tests/test_mediaspider_*.py tests/test_account_report_*.py -q
```

## 验收标准

- Cookie 仅从 `cookies/cookies.json` 读取，`.env` 不再支持三个平台 Cookie。
- 账号 workflow 和直接爬取脚本均从 Cookie 池取值，不存在硬编码 Cookie 旁路。
- 每个账号报告 workflow 启动时重新读取一次 JSON，不存在模块级 Cookie 内容缓存。
- 每个平台在多次爬取间轮询选择 Cookie。
- 明确认认证失效后自动尝试池内下一条，单次爬取不重复同一 Cookie。
- 非认证错误不触发 Cookie 切换。
- 空池、坏配置和池耗尽均产生安全、稳定且不泄密的失败行为。
- 相关测试在 `starx` conda 环境通过。
