# 账号报告领域包分层重构设计

## 背景

`app/services/account_report` 当前由二十余个平铺模块组成，采集、证据、提示词、领域模型、相似账号配置和 workflow 注册处于同一层。`workflow.py` 同时负责平台解析、爬虫调度、证据安全、AI 分块、兼容摘要和持久化，体量超过千行，已难以安全演进。

## 目标

- 按业务职责分成 `domain`、`collection`、`evidence`、`generation`、`workflows` 五个子域。
- 相似账号的人工配置与解析收敛到 `similar_accounts` 子包。
- 以基类统一 AI 完成、严格解析、重试和单分块预览的通用行为。
- 将平台采集从报告 workflow 中分离为可独立测试的采集执行器。
- 保持 HTTP 接口、workflow type、数据库字段、AI 输出结构和前端轮询契约不变。

## 分层边界

### domain

只放置稳定的领域模型和值对象，不依赖爬虫、AI 或数据库。

### collection

负责平台计划、运行参数、采集进度和采集执行。输出仅为采集结果与失败摘要，不生成报告。

### evidence

负责将采集结果归一化为可信证据，完成热度排序、AI 白名单投影、确定性兜底与输出安全校验。

### generation

负责账号上下文裁剪、提示词、分块契约、响应规范化和专项生成器，不直接写数据库。

### workflows

只组装上述能力、发布进度、调用存储端口并注册 workflow type。基类封装通用 AI 调用与分块生成行为，整份报告与单分块 workflow 只保留编排差异。

## 依赖方向

```text
workflows -> collection -> domain
workflows -> evidence   -> domain
workflows -> generation -> domain
similar_accounts -> domain
```

子域之间不反向依赖 `workflows`，避免现有 workflow 注册导致的循环导入继续扩散。

## 兼容与验证

- 应用内部导入全部切换到新分层，包根 `__init__.py` 只暴露必要的公共契约。
- 工作流注册仍由 `app.services.workflow` 启动时触发。
- 测试按新模块边界导入，并增加包结构与依赖方向检查。
- 使用 `starx` conda 环境执行账号报告、工作流、API 和数据库回归测试。
