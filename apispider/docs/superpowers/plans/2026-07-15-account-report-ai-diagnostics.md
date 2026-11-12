# 账号报告 AI 调用诊断实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 精确记录账号报告两阶段 AI 返回与异常边界，并将通用文本 AI 超时提高到 360 秒。

**Architecture:** 通用 HTTP 诊断放在 `AIService.chat_completion` 边界，账号报告业务阶段与完整文本放在 `AccountReportWorkflow` 边界。保持现有调用返回契约，仅增强日志和配置。

**Tech Stack:** Python、httpx、pytest、Pydantic Settings、conda `starx`

## Global Constraints

- 设计与计划文档使用中文。
- 后端测试必须使用名为 `starx` 的 conda 环境。
- 不记录 Token、Cookie 或 Authorization 内容。
- 通用文本 AI 超时时间统一为 360 秒。

---

### Task 1: AI 服务响应诊断与超时配置

**Files:**
- Modify: `app/services/ai_service.py`
- Modify: `app/core/config.py`
- Modify: `.env`
- Test: `tests/test_ai_service_logging.py`

**Interfaces:**
- Consumes: `AIService.chat_completion(messages, ..., timeout_seconds)` 现有调用契约。
- Produces: 成功与失败的结构化诊断日志；默认超时 360 秒。

- [x] **Step 1: 写失败测试**

新增成功响应、读取超时和非法 JSON 响应客户端，分别断言完整 payload、`response_received=false` 和完整原始响应体日志；断言配置默认值为 360。

- [x] **Step 2: 运行测试确认失败**

Run: `conda run -n starx pytest tests/test_ai_service_logging.py -q`

Expected: 新增日志字段和 360 秒默认值断言失败。

- [x] **Step 3: 最小实现**

在 `chat_completion` 中保存开始时间和可选响应对象，成功时记录完整 payload，异常时记录异常类型、超时、耗时、是否收到响应及原始响应体；同步三个默认超时配置位置。

- [x] **Step 4: 运行测试确认通过**

Run: `conda run -n starx pytest tests/test_ai_service_logging.py -q`

Expected: PASS。

### Task 2: 账号报告阶段化原始返回日志

**Files:**
- Modify: `app/services/account_report/workflow.py`
- Test: `tests/test_account_report_workflow.py`

**Interfaces:**
- Consumes: `AIService.chat_completion` 返回的 `str | None`。
- Produces: `_complete(prompt: str, *, stage: str) -> str`，记录 workflow id、阶段、长度和完整 AI 返回。

- [x] **Step 1: 写失败测试**

运行完整账号报告工作流并捕获日志，断言 `keyword_planning`、`report_analysis` 以及两次 AI 原始返回内容均存在。

- [x] **Step 2: 运行测试确认失败**

Run: `conda run -n starx pytest tests/test_account_report_workflow.py -q`

Expected: 阶段化 AI 返回日志断言失败。

- [x] **Step 3: 最小实现**

为 `_complete` 增加 `stage` 关键字参数，在空值校验前记录完整返回，并在两个调用点传入固定阶段名。

- [x] **Step 4: 运行测试确认通过**

Run: `conda run -n starx pytest tests/test_account_report_workflow.py -q`

Expected: PASS。

### Task 3: 回归验证

**Files:**
- Verify: `app/services/ai_service.py`
- Verify: `app/services/account_report/workflow.py`
- Verify: `tests/test_ai_service_logging.py`
- Verify: `tests/test_account_report_workflow.py`

**Interfaces:**
- Consumes: Task 1 和 Task 2 的实现。
- Produces: 可交付的验证证据。

- [x] **Step 1: 运行相关测试集**

Run: `conda run -n starx pytest tests/test_ai_service_logging.py tests/test_account_report_workflow.py -q`

Expected: 全部 PASS。

- [x] **Step 2: 检查差异**

Run: `git diff --check`

Expected: 无输出，退出码 0。
