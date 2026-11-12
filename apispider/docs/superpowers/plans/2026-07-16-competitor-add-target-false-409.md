# 竞品监控新增目标误报 409 修复实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复新增竞品账号或视频时因工作流外键插入顺序导致的误报 `409 Conflict`。

**Architecture:** 保持现有服务和 API 接口不变，只调整 `CompetitorRepository.add_target` 的事务顺序。先持久化并刷新工作流，再插入引用该工作流的监控目标；同时仅将两个目标唯一约束冲突转换为 `DuplicateCompetitorTarget`。

**Tech Stack:** Python、SQLAlchemy、PostgreSQL、pytest

## Global Constraints

- 后端命令必须使用名为 `starx` 的 conda 环境。
- 不修改或删除用户未跟踪的 `scripts/extractors.py`。
- 账号和视频新增目标必须走相同的事务与错误分类逻辑。

---

### Task 1: 修复新增监控目标事务

**Files:**
- Modify: `app/services/competitor_monitoring/repository.py`
- Test: `tests/test_competitor_service.py`

**Interfaces:**
- Consumes: `CompetitorRepository.add_target(...)` 与现有唯一约束名称。
- Produces: `_is_duplicate_target_error(exc: IntegrityError) -> bool`，以及保证工作流先于目标落库的 `add_target`。

- [x] **Step 1: 写入失败回归测试**

  新增开启 SQLite 外键校验的服务 fixture，并分别新增账号与视频，断言返回目标引用的工作流真实存在；再为错误分类辅助函数构造带 PostgreSQL `diag.constraint_name` 的异常，断言只有两个目标唯一约束被识别为重复。

- [x] **Step 2: 验证测试在修复前失败**

  Run: `conda run --no-capture-output -n starx pytest -q tests/test_competitor_service.py -k "foreign_key_order or duplicate_constraint"`

  Expected: 外键顺序测试因 `active_workflow_id` 引用尚未插入的工作流而失败，或错误分类辅助函数尚不存在。

- [x] **Step 3: 实现最小修复**

  在 `add_target` 中先 `session.add(workflow)` 并 `session.flush()`，随后添加目标并提交。读取 `IntegrityError.orig.diag.constraint_name`，只对 `uq_competitor_accounts_account_url` 与 `uq_competitor_videos_account_url` 抛出 `DuplicateCompetitorTarget`，其他完整性错误原样抛出。

- [x] **Step 4: 验证定向测试通过**

  Run: `conda run --no-capture-output -n starx pytest -q tests/test_competitor_service.py tests/test_competitor_api.py`

  Expected: 全部通过。

- [x] **Step 5: 运行后端回归并提交**

  Run: `conda run --no-capture-output -n starx pytest -q -k "not test_prompt_job_api_creates_job_and_background_generates_prompt"`

  Expected: 全部通过（排除依赖外部 OSS TLS 的既知测试）。

  Commit: `fix: preserve competitor target integrity errors`
