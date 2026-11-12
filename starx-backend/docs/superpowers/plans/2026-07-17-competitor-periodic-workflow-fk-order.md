# 竞品周期任务工作流外键顺序修复实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复竞品周期扫描领取到期目标时的工作流外键约束错误。

**Architecture:** 保持现有事务边界与调度接口不变，在写入目标外键前显式持久化并刷新新工作流。测试环境开启 SQLite 外键校验，以复现 PostgreSQL 的约束行为。

**Tech Stack:** Python 3.12、SQLAlchemy、PostgreSQL、SQLite、pytest

## Global Constraints

- 后端命令必须使用名为 `starx` 的 conda 环境。
- 不修改用户未跟踪的 `scripts/extractors.py`。
- 不修改数据库结构或公开接口。

---

### Task 1: 增加周期领取外键顺序回归测试并修复

**Files:**
- Modify: `tests/test_competitor_periodic_scheduler.py`
- Modify: `app/services/competitor_monitoring/repository.py:420-454`

**Interfaces:**
- Consumes: `CompetitorPeriodicScheduler.scan_once() -> int`、`CompetitorRepository.claim_due_targets(now: datetime, limit: int) -> list[WorkflowRecord]`。
- Produces: 工作流插入先于目标 `active_workflow_id` 更新的事务顺序。

- [x] **Step 1: 写入失败回归测试**

  在 `_harness` 创建 engine 后注册连接事件，对每个 SQLite DBAPI 连接执行 `PRAGMA foreign_keys=ON`。扩展扫描测试，读取两个目标并断言其活动工作流均存在。

- [x] **Step 2: 运行测试并确认修复前失败**

  Run: `conda run --no-capture-output -n starx pytest -q tests/test_competitor_periodic_scheduler.py::test_scan_submits_due_account_and_video_once`

  Expected: FAIL，错误包含 `FOREIGN KEY constraint failed`。

- [x] **Step 3: 实现最小修复**

  在 `claim_due_targets` 中创建工作流后执行：

  ```python
  session.add(workflow)
  session.flush()
  target.active_workflow_id = workflow.id
  ```

  其余状态字段和最终 `session.commit()` 保持不变。

- [x] **Step 4: 运行定向测试并确认通过**

  Run: `conda run --no-capture-output -n starx pytest -q tests/test_competitor_periodic_scheduler.py tests/test_competitor_service.py`

  Expected: 全部通过。

- [x] **Step 5: 运行相关后端回归与静态差异检查**

  Run: `conda run --no-capture-output -n starx pytest -q tests/test_competitor_periodic_scheduler.py tests/test_competitor_service.py tests/test_competitor_api.py`

  Run: `git diff --check`

  Expected: 测试全部通过，差异检查无输出。
