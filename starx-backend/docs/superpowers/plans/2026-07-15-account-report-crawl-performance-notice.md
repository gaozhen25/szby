# 账号报告采集提速与主页链接非阻断提示实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将账号报告单次采集内部并发调整为 3、每关键词内容上限收敛到 10、单内容一级评论上限调整为 20，并把无效博主主页从平台失败改为可见但非阻断的配置提示。

**Architecture:** 配置层提供全局 MediaSpider 默认值，账号报告通过独立 `crawl_options.py` 对内容上限做单向收敛。进度领域模型用独立 notice 通道表达无效主页，workflow 只负责把已识别场景路由到 notice 或 failure；前端显式归一化并分别渲染两类状态。

**Tech Stack:** Python 3、Pydantic、pytest、异步 MediaSpider workflow、React 18、原生 Node Test Runner、CSS。

## Global Constraints

- 后端 Python 命令必须通过 `conda run -n starx` 执行。
- 设计与实施文档使用中文。
- `MEDIASPIDER_MAX_CONCURRENCY` 默认值必须为 `3`。
- `MEDIASPIDER_MAX_COMMENTS_COUNT` 默认值必须为 `20`。
- `ACCOUNT_REPORT_MAX_NOTES_PER_KEYWORD` 默认值必须为 `10`，并满足 `ge=1`。
- 账号报告有效内容上限必须为 `min(MEDIASPIDER_MAX_NOTES_COUNT, ACCOUNT_REPORT_MAX_NOTES_PER_KEYWORD)`。
- 关键词计划仍为 3～5 个不重复关键词，每个关键词最多 12 个字符。
- 子评论采集保持关闭；最终证据仍最多 20 条内容、20 条评论、单内容 3 条评论。
- 多个 workflow 继续受进程级爬虫锁串行保护，本次只提升单次运行内部并发。
- Cookie、完整主页 URL、用户标识、请求头和异常原文不得进入日志、API、进度快照、报告来源或测试输出。
- 无效主页 notice 的公开文案固定为“配置的博主主页链接无效，已跳过主页采集”。
- 无效主页不得写入 `sourceMeta.failedPlatforms`；真正的凭证、网络、风控、运行时和关键词异常继续走 failure。

---

## 文件结构

### 后端新增文件

- `app/services/account_report/crawl_options.py`：只负责把全局 MediaSpider 参数收敛为账号报告运行参数。
- `app/services/account_report/crawl_notice_catalog.py`：只负责构造账号报告可公开的固定 notice 文案。
- `tests/test_account_report_crawl_options.py`：独立验证账号报告专用内容上限，不依赖完整 workflow。

### 后端修改文件

- `app/core/config.py`：调整并发和评论默认值，新增账号报告专用内容上限。
- `.env.example`：记录与代码一致的非敏感配置示例。
- `app/services/account_report/crawl_progress_models.py`：保存 notice 状态并序列化 notice 摘要字段。
- `app/services/account_report/crawl_progress.py`：新增非阻断 `notice()` 跟踪入口。
- `app/services/account_report/workflow.py`：应用账号报告参数，并把四类无效主页场景路由到 notice。
- `tests/test_mediaspider_config.py`：验证默认配置与环境覆盖。
- `tests/test_account_report_crawl_progress.py`：验证 notice/failure 状态机、安全和持久化。
- `tests/test_account_report_workflow.py`：验证 workflow 继续关键词采集、报告来源和真实失败语义。

### 前端修改文件

- `src/utils/accountReport.js`：归一化 `noticeCode`、`noticeMessage`、`noticeSuggestion`。
- `src/utils/accountReport.test.js`：行为测试 notice 字段与旧记录兼容。
- `src/pages/account-report/AccountReportWorkflowProgress.jsx`：分开展示配置提示和平台失败。
- `src/styles/pages.css`：增加非红色 notice 与 skipped 活动样式。
- `src/pages/AccountReport.preview.test.js`：约束组件已接入 notice 展示且不使用不安全 HTML。

---

### Task 1: 配置默认值与账号报告运行参数收敛

**Files:**
- Create: `app/services/account_report/crawl_options.py`
- Create: `tests/test_account_report_crawl_options.py`
- Modify: `app/core/config.py:199-210`
- Modify: `.env.example:65-71`
- Modify: `tests/test_mediaspider_config.py:1-90`

**Interfaces:**
- Consumes: `runtime_settings.mediaspider_runtime_options(platform: str) -> dict[str, object]`。
- Produces: `account_report_runtime_options(runtime_settings: object, platform: str) -> dict[str, object]`，供 Task 3 的 workflow 使用。

- [ ] **Step 1: 为默认配置写失败测试**

在 `tests/test_mediaspider_config.py` 的首个测试中补充默认值断言：

```python
    assert options["max_notes_count"] == 30
    assert options["max_comments_count"] == 20
    assert options["max_concurrency"] == 3
    assert configured.ACCOUNT_REPORT_MAX_NOTES_PER_KEYWORD == 10
    assert options["enable_sub_comments"] is False
```

再增加正整数校验测试：

```python
def test_account_report_max_notes_per_keyword_must_be_positive(monkeypatch):
    monkeypatch.setenv("STARX_ACCOUNT_REPORT_MAX_NOTES_PER_KEYWORD", "0")

    with pytest.raises(ValueError):
        Settings(_env_file=None)
```

- [ ] **Step 2: 运行配置测试并确认失败**

Run:

```bash
conda run -n starx pytest tests/test_mediaspider_config.py -q
```

Expected: FAIL，默认评论数仍为 `10`、并发数仍为 `1`，且账号报告专用字段尚不存在。

- [ ] **Step 3: 实现配置默认值并同步示例文件**

在 `app/core/config.py` 的 MediaSpider 配置区使用：

```python
    MEDIASPIDER_MAX_NOTES_COUNT: int = 30
    MEDIASPIDER_MAX_COMMENTS_COUNT: int = 20
    MEDIASPIDER_MAX_CONCURRENCY: int = 3
    ACCOUNT_REPORT_MAX_NOTES_PER_KEYWORD: int = Field(default=10, ge=1)
    MEDIASPIDER_ENABLE_COMMENTS: bool = True
    MEDIASPIDER_ENABLE_SUB_COMMENTS: bool = False
```

将 `.env.example` 的采集上限改为：

```dotenv
STARX_MEDIASPIDER_MAX_NOTES_COUNT=30
STARX_MEDIASPIDER_MAX_COMMENTS_COUNT=20
STARX_MEDIASPIDER_MAX_CONCURRENCY=3
STARX_ACCOUNT_REPORT_MAX_NOTES_PER_KEYWORD=10
STARX_MEDIASPIDER_ENABLE_COMMENTS=true
STARX_MEDIASPIDER_ENABLE_SUB_COMMENTS=false
```

- [ ] **Step 4: 为账号报告参数收敛写失败测试**

创建 `tests/test_account_report_crawl_options.py`：

```python
from app.services.account_report.crawl_options import account_report_runtime_options


class StubRuntimeSettings:
    def __init__(self, global_limit: int, report_limit: int = 10) -> None:
        self.global_limit = global_limit
        self.ACCOUNT_REPORT_MAX_NOTES_PER_KEYWORD = report_limit

    def mediaspider_runtime_options(self, platform: str) -> dict[str, object]:
        return {
            "cookies": f"{platform}-sentinel",
            "max_notes_count": self.global_limit,
            "max_comments_count": 20,
            "max_concurrency": 3,
        }


def test_account_report_caps_global_note_limit_at_report_limit():
    options = account_report_runtime_options(StubRuntimeSettings(30), "xhs")

    assert options["max_notes_count"] == 10
    assert options["max_comments_count"] == 20
    assert options["max_concurrency"] == 3


def test_account_report_preserves_lower_global_note_limit():
    options = account_report_runtime_options(StubRuntimeSettings(6), "dy")

    assert options["max_notes_count"] == 6


def test_account_report_returns_a_copy_of_global_options():
    configured = StubRuntimeSettings(30)
    original = configured.mediaspider_runtime_options("xhs")

    options = account_report_runtime_options(configured, "xhs")

    assert options is not original
    assert original["max_notes_count"] == 30
```

- [ ] **Step 5: 运行新测试并确认导入失败**

Run:

```bash
conda run -n starx pytest tests/test_account_report_crawl_options.py -q
```

Expected: collection ERROR，`app.services.account_report.crawl_options` 尚不存在。

- [ ] **Step 6: 实现最小参数收敛函数**

创建 `app/services/account_report/crawl_options.py`：

```python
"""账号报告专用的 MediaSpider 运行参数收敛。"""

from __future__ import annotations

from typing import Any


def account_report_runtime_options(
    runtime_settings: Any,
    platform: str,
) -> dict[str, object]:
    options = dict(runtime_settings.mediaspider_runtime_options(platform))
    global_limit = max(int(options.get("max_notes_count") or 1), 1)
    report_limit = max(
        int(runtime_settings.ACCOUNT_REPORT_MAX_NOTES_PER_KEYWORD),
        1,
    )
    options["max_notes_count"] = min(global_limit, report_limit)
    return options
```

- [ ] **Step 7: 运行配置与参数测试并确认通过**

Run:

```bash
conda run -n starx pytest tests/test_mediaspider_config.py tests/test_account_report_crawl_options.py -q
```

Expected: PASS。

- [ ] **Step 8: 提交后端配置任务**

```bash
git add app/core/config.py .env.example app/services/account_report/crawl_options.py tests/test_mediaspider_config.py tests/test_account_report_crawl_options.py
git diff --cached --check
git commit -m "feat: tune account report crawl limits"
```

### Task 2: 建立安全的主页配置 notice 状态通道

**Files:**
- Create: `app/services/account_report/crawl_notice_catalog.py`
- Modify: `app/services/account_report/crawl_progress_models.py:20-145`
- Modify: `app/services/account_report/crawl_progress.py:120-230`
- Modify: `tests/test_account_report_crawl_progress.py:1-540`

**Interfaces:**
- Consumes: 固定 notice code `creator_url_invalid`，不接收调用方提供的公开文案。
- Produces: `public_account_report_notice(code: str) -> CrawlerFailure`、`AccountReportCrawlProgressTracker.notice(platform_code: str, *, mode: str, code: str) -> None`，以及平台摘要中的 `noticeCode`、`noticeMessage`、`noticeSuggestion`。

- [ ] **Step 1: 为 notice 状态机写失败测试**

在 `tests/test_account_report_crawl_progress.py` 增加：

```python
import pytest


def test_creator_url_notice_is_skipped_but_does_not_mark_platform_failed():
    store = FakeProgressStore()
    tracker = AccountReportCrawlProgressTracker(
        "wf-1", store, [CrawlTarget("抖音", "dy")]
    )

    tracker.notice(
        "dy",
        mode="creator",
        code="creator_url_invalid",
    )

    snapshot = store.merged["crawlProgress"]
    summary = snapshot["platformSummaries"][0]
    assert summary["status"] == "pending"
    assert summary["failureCode"] is None
    assert summary["noticeCode"] == "creator_url_invalid"
    assert summary["noticeMessage"] == "配置的博主主页链接无效，已跳过主页采集"
    assert summary["noticeSuggestion"] == "请在账号档案中填写该平台真实、完整的博主主页链接"
    assert snapshot["current"]["status"] == "skipped"
    assert snapshot["current"]["action"] == "creator_skipped"


def test_platform_completes_after_creator_notice_and_keeps_notice_visible():
    store = FakeProgressStore()
    tracker = AccountReportCrawlProgressTracker(
        "wf-1", store, [CrawlTarget("抖音", "dy")]
    )
    tracker.notice("dy", mode="creator", code="creator_url_invalid")

    tracker.complete("dy", content_count=4, creator_count=0, comment_count=8)

    summary = store.merged["crawlProgress"]["platformSummaries"][0]
    assert summary["status"] == "completed"
    assert summary["contentCount"] == 4
    assert summary["failureCode"] is None
    assert summary["noticeCode"] == "creator_url_invalid"


def test_real_failure_and_creator_notice_remain_separate():
    store = FakeProgressStore()
    tracker = AccountReportCrawlProgressTracker(
        "wf-1", store, [CrawlTarget("抖音", "dy")]
    )
    tracker.notice("dy", mode="creator", code="creator_url_invalid")
    tracker.fail(
        "dy",
        mode="keyword",
        failure=CrawlerFailure(
            code="browser_timeout",
            message="平台页面响应超时",
            suggestion="请稍后重试",
        ),
    )

    summary = store.merged["crawlProgress"]["platformSummaries"][0]
    assert summary["status"] == "failed"
    assert summary["failureCode"] == "browser_timeout"
    assert summary["noticeCode"] == "creator_url_invalid"


def test_tracker_rejects_unknown_notice_codes_without_persisting_text():
    store = FakeProgressStore()
    tracker = AccountReportCrawlProgressTracker(
        "wf-1", store, [CrawlTarget("抖音", "dy")]
    )

    with pytest.raises(ValueError, match="unsupported account report notice code"):
        tracker.notice("dy", mode="creator", code="forged-notice-sentinel")

    assert "forged-notice-sentinel" not in json.dumps(store.merged, ensure_ascii=False)
```

- [ ] **Step 2: 运行 tracker 测试并确认失败**

Run:

```bash
conda run -n starx pytest tests/test_account_report_crawl_progress.py -q
```

Expected: collection ERROR 或 FAIL，notice 目录、`tracker.notice()` 和摘要字段尚不存在。

- [ ] **Step 3: 创建固定 notice 文案目录**

创建 `app/services/account_report/crawl_notice_catalog.py`：

```python
"""账号报告可公开的非阻断采集提示。"""

from app.services.mediaspider.models import CrawlerFailure


def public_account_report_notice(code: str) -> CrawlerFailure:
    if code != "creator_url_invalid":
        raise ValueError("unsupported account report notice code")
    return CrawlerFailure(
        code="creator_url_invalid",
        message="配置的博主主页链接无效，已跳过主页采集",
        suggestion="请在账号档案中填写该平台真实、完整的博主主页链接",
    )
```

- [ ] **Step 4: 扩展平台状态与摘要模型**

在 `PlatformState` 增加：

```python
    notices: dict[str, CrawlerFailure] = field(default_factory=dict)

    @property
    def latest_notice(self) -> CrawlerFailure | None:
        return next(reversed(self.notices.values()), None)
```

保持 `status` 只检查 `active`、`failures` 和 `successful_runs`，不得让 `notices` 触发 `partial` 或 `failed`。

在 `PlatformCrawlSummary` 增加：

```python
    notice_code: str | None = Field(default=None, alias="noticeCode")
    notice_message: str | None = Field(default=None, alias="noticeMessage")
    notice_suggestion: str | None = Field(default=None, alias="noticeSuggestion")
```

在 `platform_summary(state)` 中读取并安全序列化：

```python
    notice = state.latest_notice
```

并向构造器增加：

```python
        noticeCode=notice.code if notice else None,
        noticeMessage=(
            sanitize_public_text(notice.message, limit=120) if notice else None
        ),
        noticeSuggestion=(
            sanitize_public_text(notice.suggestion, limit=160) if notice else None
        ),
```

- [ ] **Step 5: 实现 tracker 的非阻断入口**

在 `crawl_progress.py` 导入固定 notice 目录：

```python
from .crawl_notice_catalog import public_account_report_notice
```

在 `AccountReportCrawlProgressTracker.fail()` 前增加：

```python
    def notice(
        self,
        platform_code: str,
        *,
        mode: str,
        code: str,
    ) -> None:
        state = self._states.get(platform_code)
        if state is None:
            return
        safe_notice = public_account_report_notice(code)
        safe_mode = mode if mode == "creator" else "workflow"
        state.notices[safe_mode] = safe_notice
        state.active = False
        state.settle_current_counts()
        self.current_stage = "creator_crawling"
        self.progress = max(self.progress, 15)
        self._append_lifecycle_activity(
            state,
            stage="creator",
            action="creator_skipped",
            status="skipped",
            message=safe_notice.message,
        )
        self._persist()
```

不要修改 `failure_summary()`：notice 不是失败，不应进入全部失败原因拼接。

- [ ] **Step 6: 运行 tracker 测试并确认通过**

Run:

```bash
conda run -n starx pytest tests/test_account_report_crawl_progress.py -q
```

Expected: PASS，既有 failure 安全测试继续通过。

- [ ] **Step 7: 提交后端 notice 状态任务**

```bash
git add app/services/account_report/crawl_notice_catalog.py app/services/account_report/crawl_progress_models.py app/services/account_report/crawl_progress.py tests/test_account_report_crawl_progress.py
git diff --cached --check
git commit -m "feat: track nonblocking creator link notices"
```

### Task 3: workflow 应用采样上限并将无效主页路由到 notice

**Files:**
- Modify: `app/services/account_report/workflow.py:245-430`
- Modify: `tests/test_account_report_workflow.py:55-610`

**Interfaces:**
- Consumes: Task 1 的 `account_report_runtime_options()` 与 Task 2 的 `tracker.notice()`。
- Produces: 无效主页继续关键词采集且不写 `failedPlatforms` 的完整 workflow 行为。

- [ ] **Step 1: 让 workflow 测试桩携带完整采集上限**

将 `StubSettings` 改为：

```python
class StubSettings:
    def __init__(
        self,
        cookies=None,
        *,
        max_notes_count=30,
        report_max_notes_per_keyword=10,
    ):
        self.cookies = cookies or {
            "xhs": "xhs-secret",
            "dy": "dy-secret",
            "ks": "ks-secret",
        }
        self.max_notes_count = max_notes_count
        self.ACCOUNT_REPORT_MAX_NOTES_PER_KEYWORD = report_max_notes_per_keyword

    def mediaspider_runtime_options(self, platform):
        return {
            "cookies": self.cookies.get(platform, ""),
            "headless": True,
            "max_notes_count": self.max_notes_count,
        }
```

- [ ] **Step 2: 更新无效主页预期并补充分支测试**

把 `test_invalid_creator_url_variants_still_run_keyword_crawl` 的摘要断言替换为：

```python
    assert summary["status"] == "completed"
    assert summary["failureCode"] is None
    assert summary["noticeCode"] == "creator_url_invalid"
    assert summary["noticeMessage"] == "配置的博主主页链接无效，已跳过主页采集"
    assert store.replacements[0][2]["sourceMeta"]["failedPlatforms"] == []
```

把空博主结果测试的核心断言替换为：

```python
    assert summary["status"] == "completed"
    assert summary["failureCode"] is None
    assert summary["noticeCode"] == "creator_url_invalid"
    assert summary["contentCount"] == 0
    assert store.replacements[0][2]["sourceMeta"]["failedPlatforms"] == []
```

把跨平台链接测试的来源断言替换为：

```python
    assert store.replacements[0][2]["sourceMeta"]["failedPlatforms"] == []
    summary = store.result_payloads[-1]["crawlProgress"]["platformSummaries"][0]
    assert summary["noticeCode"] == "creator_url_invalid"
```

增加已分类异常分支：

```python
def test_classified_invalid_creator_url_becomes_notice_and_keyword_continues():
    invalid = CrawlerFailure(
        code="creator_url_invalid",
        message="博主主页链接无效或账号不存在",
        suggestion="在账号档案填写真实完整主页链接",
    )
    store = StubStore(platforms=["抖音"])
    crawler = ClassifiedCrawler(failures={("creator", "dy"): invalid})

    asyncio.run(
        _execute(
            store=store,
            crawler=crawler,
            ai=StubAI(report=_report_payload(platforms=["抖音"])),
        )
    )

    assert [(mode, platform) for mode, platform, _ in crawler.calls] == [
        ("creator", "dy"),
        ("keyword", "dy"),
    ]
    summary = store.result_payloads[-1]["crawlProgress"]["platformSummaries"][0]
    assert summary["status"] == "completed"
    assert summary["failureCode"] is None
    assert summary["noticeCode"] == "creator_url_invalid"
    assert store.replacements[0][2]["sourceMeta"]["failedPlatforms"] == []
```

增加运行参数接入测试：

```python
def test_workflow_caps_each_platform_keyword_crawl_at_report_limit():
    store = StubStore(platforms=["小红书"])
    crawler = StubCrawler()

    asyncio.run(
        _execute(
            store=store,
            crawler=crawler,
            ai=StubAI(report=_report_payload(platforms=["小红书"])),
            settings=StubSettings(max_notes_count=30, report_max_notes_per_keyword=10),
        )
    )

    assert all(options["max_notes_count"] == 10 for _, _, options in crawler.calls)
```

- [ ] **Step 3: 运行 workflow 测试并确认失败**

Run:

```bash
conda run -n starx pytest tests/test_account_report_workflow.py -q
```

Expected: FAIL，当前无效主页仍进入 `failureCode` 与 `failedPlatforms`，且运行参数仍未调用账号报告收敛函数。

- [ ] **Step 4: 接入参数收敛和 notice 依赖**

在 `workflow.py` 导入：

```python
from .crawl_options import account_report_runtime_options
```

将运行参数字典改为：

```python
        runtime_options_by_platform = {
            plan.platform_code: account_report_runtime_options(
                runtime_settings,
                plan.platform_code,
            )
            for plan in plans
        }
```

在 `record_failure()` 后增加：

```python
        def record_notice(plan: CrawlPlan, *, mode: str) -> None:
            tracker.notice(
                plan.platform_code,
                mode=mode,
                code="creator_url_invalid",
            )
```

删除只为失败分支构造的 `invalid_creator_url = public_crawler_failure("creator_url_invalid")`。

- [ ] **Step 5: 将四类无效主页分支改为 notice**

将以下分支中以 `failure=invalid_creator_url` 调用 `record_failure()` 的代码改为：

```python
                    record_notice(plan, mode="creator")
```

需要覆盖的分支是：

1. `plan.creator_url` 存在但 `planned_owner_hashes` 为空。
2. `creator_result` 的内容数与博主数都为 0。
3. `plan.creator_url` 为空。

将已分类异常分支改为：

```python
                    except CrawlerExecutionError as exc:
                        if exc.failure.code == "creator_url_invalid":
                            record_notice(plan, mode="creator")
                        else:
                            record_failure(plan, mode="creator", failure=exc.failure)
```

保留通用 `except Exception`、缺少凭证和关键词采集的原有 failure 逻辑。

- [ ] **Step 6: 运行 workflow、tracker 与参数测试**

Run:

```bash
conda run -n starx pytest tests/test_account_report_crawl_options.py tests/test_account_report_crawl_progress.py tests/test_account_report_workflow.py -q
```

Expected: PASS。

- [ ] **Step 7: 提交 workflow 任务**

```bash
git add app/services/account_report/workflow.py tests/test_account_report_workflow.py
git diff --cached --check
git commit -m "fix: skip invalid creator links in account reports"
```

### Task 4: 前端分别展示平台失败与主页配置提示

**Files:**
- Modify: `src/utils/accountReport.js:34-178`
- Modify: `src/utils/accountReport.test.js:40-115`
- Modify: `src/pages/account-report/AccountReportWorkflowProgress.jsx:1-105`
- Modify: `src/styles/pages.css:3595-3747`
- Modify: `src/pages/AccountReport.preview.test.js:60-95`

**Interfaces:**
- Consumes: 后端平台摘要的可选 `noticeCode`、`noticeMessage`、`noticeSuggestion`。
- Produces: 归一化后的 `summary.noticeCode`、`summary.noticeMessage`、`summary.noticeSuggestion`，以及独立的 `report-platform-notice` 展示区域。

- [ ] **Step 1: 为 notice 归一化写失败测试**

在 `src/utils/accountReport.test.js` 增加：

```javascript
test("crawl progress preserves a nonblocking creator configuration notice", () => {
  const progress = normalizeCrawlProgress({
    resultPayload: {
      crawlProgress: {
        platformSummaries: [{
          platform: "dy",
          platformName: "抖音",
          status: "completed",
          contentCount: 12,
          noticeCode: "creator_url_invalid",
          noticeMessage: "配置的博主主页链接无效，已跳过主页采集",
          noticeSuggestion: "请在账号档案中填写该平台真实、完整的博主主页链接",
          rawNotice: "https://example.test/profile?token=must-not-pass",
        }],
      },
    },
  });

  assert.deepEqual(progress.platformSummaries[0], {
    platform: "dy",
    platformName: "抖音",
    status: "completed",
    contentCount: 12,
    noticeCode: "creator_url_invalid",
    noticeMessage: "配置的博主主页链接无效，已跳过主页采集",
    noticeSuggestion: "请在账号档案中填写该平台真实、完整的博主主页链接",
  });
  assert.doesNotMatch(JSON.stringify(progress), /must-not-pass/);
});
```

- [ ] **Step 2: 运行前端工具测试并确认失败**

Run:

```bash
npm test -- src/utils/accountReport.test.js
```

Expected: FAIL，notice 字段尚未进入归一化结果。

- [ ] **Step 3: 实现 notice 字段归一化**

将 `PLATFORM_SUMMARY_TEXT_FIELDS` 扩展为：

```javascript
const PLATFORM_SUMMARY_TEXT_FIELDS = [
  "platform",
  "platformName",
  "status",
  "failureCode",
  "failureMessage",
  "noticeCode",
  "noticeMessage",
];
```

在 `normalizePlatformSummary()` 处理 failure 建议后增加：

```javascript
  const noticeSuggestion = typeof value.noticeSuggestion === "string"
    ? value.noticeSuggestion.trim()
    : "";
  if (noticeSuggestion) summary.noticeSuggestion = noticeSuggestion;
```

保留现有 `summary.suggestion` 兼容字段，避免破坏旧后端的 failure 建议展示。

- [ ] **Step 4: 为组件接入写结构测试**

在 `src/pages/AccountReport.preview.test.js` 的诊断测试中增加：

```javascript
  assert.match(progressSource, /noticeMessage/);
  assert.match(progressSource, /noticeSuggestion/);
  assert.match(progressSource, /className="report-platform-notice" role="note"/);
  assert.match(progressSource, /item\.status === "skipped"/);
```

- [ ] **Step 5: 运行页面测试并确认失败**

Run:

```bash
npm test -- src/pages/AccountReport.preview.test.js
```

Expected: FAIL，组件尚未渲染 notice，也没有 skipped 活动样式入口。

- [ ] **Step 6: 分开展示 notice 和 failure**

将活动 `<li>` 的 className 改为：

```jsx
<li
  className={item.status === "failed" ? "failed" : item.status === "skipped" ? "skipped" : ""}
  key={`${item.sequence || "activity"}-${index}`}
>
```

在平台摘要的失败文案与建议之后增加：

```jsx
              {item.noticeMessage ? (
                <div className="report-platform-notice" role="note">
                  <p>{item.noticeMessage}</p>
                  {item.noticeSuggestion ? <small>建议：{item.noticeSuggestion}</small> : null}
                </div>
              ) : null}
```

保留既有：

```jsx
              {item.failureMessage ? <p>{item.failureMessage}</p> : null}
              {item.suggestion ? <small>建议：{item.suggestion}</small> : null}
```

这样 notice 与 failure 同时存在时不会互相覆盖。

- [ ] **Step 7: 增加非红色提示样式**

在 `src/styles/pages.css` 的活动标记区增加：

```css
.report-crawl-activities li.skipped .report-activity-marker {
  background: var(--color-accent-gold);
}
```

在平台摘要文案样式后增加：

```css
.report-platform-notice {
  display: grid;
  gap: 4px;
  padding: 8px 10px;
  border: 1px solid color-mix(in srgb, var(--color-accent-gold) 32%, transparent);
  border-radius: 10px;
  background: color-mix(in srgb, var(--color-accent-gold) 8%, transparent);
}

.report-platform-notice p,
.report-platform-notice small {
  color: var(--color-accent-gold);
}
```

- [ ] **Step 8: 运行前端定向测试和构建**

Run:

```bash
npm test -- src/utils/accountReport.test.js src/pages/AccountReport.preview.test.js
npm run build
```

Expected: 两个测试文件 PASS，Vite build 成功且无 JSX/CSS 解析错误。

- [ ] **Step 9: 提交前端任务**

在 `starx-frontend` 仓库执行：

```bash
git add src/utils/accountReport.js src/utils/accountReport.test.js src/pages/account-report/AccountReportWorkflowProgress.jsx src/styles/pages.css src/pages/AccountReport.preview.test.js
git diff --cached --check
git commit -m "feat: show nonblocking creator link notices"
```

### Task 5: 全量回归、安全检查与运行交接

**Files:**
- Verify: `starx-backend` 全部已修改文件与测试。
- Verify: `starx-frontend` 全部已修改文件与测试。

**Interfaces:**
- Consumes: Tasks 1～4 的完整后端与前端行为。
- Produces: 可重启部署的验证证据，不新增生产代码接口。

- [ ] **Step 1: 运行后端定向测试**

在 `starx-backend` 执行：

```bash
conda run -n starx pytest tests/test_mediaspider_config.py tests/test_account_report_crawl_options.py tests/test_account_report_crawl_progress.py tests/test_account_report_workflow.py -q
```

Expected: PASS。

- [ ] **Step 2: 运行 MediaSpider 与账号报告相关回归**

```bash
conda run -n starx pytest tests/test_mediaspider_service.py tests/test_mediaspider_runtime.py tests/test_mediaspider_platform_runtime.py tests/test_mediaspider_auth.py tests/test_mediaspider_error_classifier.py tests/test_mediaspider_safe_logging.py tests/test_account_report_api.py tests/test_account_report_evidence.py tests/test_account_report_owner_identity.py -q
```

Expected: PASS。

- [ ] **Step 3: 运行后端全量测试**

```bash
conda run -n starx pytest -q
```

Expected: 全部 PASS；输出不得包含 Cookie、Authorization、AccessKey、签名或完整主页 URL。若外部对象存储或网络集成未隔离，应使用仓库既有的内存存储测试配置重新执行，不打印真实配置值。

- [ ] **Step 4: 运行前端全量测试与生产构建**

在 `starx-frontend` 执行：

```bash
npm test
npm run build
```

Expected: 全部 PASS，生产构建成功。

- [ ] **Step 5: 检查差异范围与敏感信息**

分别在后端、前端仓库执行：

```bash
git status --short
git diff --check
git diff --stat
```

Expected: 只有计划内文件发生变化；任何用户原有修改保持不变且未被加入提交。人工查看差异，确认没有 `.env`、Cookie、请求头、完整主页链接或异常原文。

- [ ] **Step 6: 记录重启后的验收方式**

后端重启后生成一个包含无效抖音主页但凭证有效的账号报告，只观察公开进度与计数。验收结果必须满足：

```text
抖音：配置的博主主页链接无效，已跳过主页采集
随后出现：开始关键词采集 / 发现公开内容 / 评论计数更新
平台最终状态：已完成（若关键词成功）
sourceMeta.failedPlatforms：不包含该无效主页
```

真实验收不得复制、输出或截屏暴露 Cookie 和后端环境变量。
