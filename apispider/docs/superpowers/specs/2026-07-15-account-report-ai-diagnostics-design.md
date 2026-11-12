# 账号报告 AI 调用诊断设计

## 背景与根因

账号报告工作流会先生成检索词，再生成最终报告。当前 `AIService.chat_completion` 在请求读取超时、响应状态异常或响应解析异常时统一返回 `None`，账号报告随后统一抛出“AI 服务未返回有效结果”。现有日志无法区分调用阶段，也无法区分“未收到响应”和“收到无效响应”。

本次故障日志中的 `ReadTimeout` 表明请求已经发出，但在当前 60 秒读取窗口内没有收到完整响应，因此该次调用不存在可打印的 AI 正文。

## 目标

1. 将通用 AI 文本调用超时时间提高到 360 秒。
2. 账号报告的两次 AI 调用均记录阶段、返回长度和完整返回内容。
3. AI 服务记录请求耗时、超时配置、响应状态和是否收到响应。
4. HTTP 错误或响应 JSON 解析失败时记录完整原始响应体。
5. 日志不得记录 Token、Cookie 或 Authorization 内容。

## 设计

### AI 服务边界

`AIService.chat_completion` 在调用开始时记录单调时钟。收到成功响应并解析 JSON 后，在 INFO 日志记录模型、状态码、耗时、响应长度和完整 JSON payload。异常日志增加异常类型、超时秒数、耗时、`response_received` 和已收到的原始响应体；尚未收到响应时明确输出 `response_received=false`。

保留现有返回契约：成功返回文本，HTTP 或网络异常返回 `None`，430 仍返回既有哨兵值。本次只增强可观测性，不引入重试或改变业务错误语义。

### 账号报告边界

`AccountReportWorkflow._complete` 接收明确的阶段名：`keyword_planning` 或 `report_analysis`。AI 返回后先记录 workflow id、阶段、内容长度和完整内容，再做空值检查。这样可以直接判断失败发生在哪次调用，并看到进入严格 JSON 解析前的原始模型输出。

### 配置

将 `Settings.DEFAULT_TIMEOUT`、`AIService` 的兜底默认值以及当前 `.env` 的 `DEFAULT_TIMEOUT` 统一设为 360 秒，避免不同启动环境出现不一致。

## 测试

1. 模拟成功响应，断言 AI 服务日志包含完整 payload、状态码和响应长度。
2. 模拟 `ReadTimeout`，断言日志包含异常类型、360 秒超时信息以及 `response_received=false`。
3. 模拟非 JSON 响应，断言日志包含完整原始响应体。
4. 运行账号报告工作流，断言两个阶段的完整 AI 返回都被记录。
5. 运行相关测试集，并检查代码差异。

