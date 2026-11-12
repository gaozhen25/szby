# 账号主页无效时保留行业证据 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 账号主页链接缺失或无效时，仍使用关键词采集结果生成非零 `sampleCount`、相似账号、爆款笔记和头部博主候选。

**Architecture:** 删除证据层按 `unknown_owner_platforms` 整个平台短路的逻辑，只保留基于可信 `owner_hashes` 的自身排除。工作流继续记录 `creator_url_invalid` 提示，但不再计算或传递未知 owner 平台集合；AI 候选白名单、链接回填和持久化结构保持不变。

**Tech Stack:** Python 3.12、Pydantic、pytest、SQLAlchemy；后端命令必须使用 conda 环境 `starx`。

## Global Constraints

- 设计文档使用中文书写。
- 后端 Python 测试必须使用名为 `starx` 的 conda 环境。
- 主页无效时接受行业候选中可能混入当前账号，不使用名称或 AI 推断身份。
- 有可信 owner ID 时必须继续排除当前账号。
- 不修改前端和数据库结构，不回填历史报告。

---

### Task 1: 证据层不再按未知 owner 平台清空行业结果

**Files:**
- Modify: `app/services/account_report/evidence.py:211-390`
- Test: `tests/test_account_report_evidence.py`

**Interfaces:**
- Consumes: `build_report_evidence(current_account_results, industry_results, own_creator_hashes)` 与 `owner_hashes: set[str]`。
- Produces: `_collect_records` 和 `_enrich_creators` 仅按可信 `owner_hashes` 排除自身；`build_report_evidence` 不再接收 `unknown_owner_platforms`。

- [ ] **Step 1: 写主页未知时仍保留行业候选的失败测试**

在 `tests/test_account_report_evidence.py` 添加：

```python
def test_unknown_owner_keeps_all_keyword_industry_evidence():
    evidence = build_report_evidence(
        [],
        [
            _result(
                "xhs",
                contents=[
                    {
                        "note_id": "possible-self",
                        "user_id": "unknown-self",
                        "title": "可能属于当前账号",
                    },
                    {
                        "note_id": "industry-note",
                        "user_id": "industry-author",
                        "title": "行业样本",
                    },
                ],
                creators=[
                    {"user_id": "unknown-self", "nickname": "未知账号"},
                    {"user_id": "industry-author", "nickname": "行业账号"},
                ],
            )
        ],
        set(),
        unknown_owner_platforms={"xhs"},
    )

    assert {item.content_id for item in evidence.industry.hot_contents} == {
        "possible-self",
        "industry-note",
    }
    assert len(evidence.industry.similar_accounts) == 2
    assert len(evidence.industry.top_bloggers) == 2
```

- [ ] **Step 2: 运行测试并确认按旧逻辑失败**

Run:

```bash
conda run --no-capture-output -n starx pytest -q tests/test_account_report_evidence.py::test_unknown_owner_keeps_all_keyword_industry_evidence
```

Expected: FAIL，`hot_contents` 为空，因为旧实现对 `xhs` 整个平台执行短路。

- [ ] **Step 3: 删除未知 owner 平台短路逻辑**

在 `app/services/account_report/evidence.py` 中：

1. 从 `_collect_records` 与 `_enrich_creators` 的参数中删除 `unknown_platforms`。
2. 删除 `_collect_records` 中以下平台级短路：

```python
if exclude_owners and platform in unknown_platforms:
    continue
```

3. 将内容和创作者排除条件统一为仅命中可信 owner hash：

```python
if item is None or (exclude_owners and item.creator_hash in owner_hashes):
    continue
```

```python
if exclude_owners and item.creator_hash in owner_hashes:
    continue
```

4. `_enrich_creators` 对内容的排除条件改为：

```python
if exclude_owners and item.creator_hash in owner_hashes:
    continue
```

5. 从 `build_report_evidence` 签名删除 `unknown_owner_platforms`，并删除 `unknown_platforms` 归一化和四处参数传递。

- [ ] **Step 4: 调整失败测试为最终公开接口**

从测试调用中删除：

```python
unknown_owner_platforms={"xhs"},
```

测试名称和断言保持不变，表达“没有可信 owner hash 时保留全部关键词行业结果”。

- [ ] **Step 5: 验证未知 owner 保留、已知 owner 仍排除**

Run:

```bash
conda run --no-capture-output -n starx pytest -q \
  tests/test_account_report_evidence.py::test_unknown_owner_keeps_all_keyword_industry_evidence \
  tests/test_account_report_evidence.py::test_report_evidence_separates_current_account_from_industry_candidates
```

Expected: 2 passed。

- [ ] **Step 6: 提交证据层修改**

```bash
git add app/services/account_report/evidence.py tests/test_account_report_evidence.py
git commit -m "fix: keep industry evidence without owner profile"
```

---

### Task 2: 工作流停止传递未知 owner 平台并验证持久化候选

**Files:**
- Modify: `app/services/account_report/workflow.py:360-555`
- Test: `tests/test_account_report_workflow.py:1040-1130`

**Interfaces:**
- Consumes: Task 1 中不再包含 `unknown_owner_platforms` 的 `build_report_evidence`。
- Produces: 主页无效 notice 与关键词采集可同时成功；行业候选进入 AI prompt，并能通过白名单持久化。

- [ ] **Step 1: 将旧 fail-closed 工作流测试改成期望保留行业证据**

将 `test_unknown_owner_platform_is_fail_closed_for_all_industry_evidence` 重命名为：

```python
def test_unknown_owner_platform_keeps_keyword_industry_evidence(unknown_xhs_url):
```

把断言替换为：

```python
assert {item["platform"] for item in candidates} == {"xhs", "dy"}
assert {item["creator_hash"] for item in candidates} == {
    anonymize_user_id("unknown-self"),
    anonymize_user_id("xhs-competitor"),
    anonymize_user_id("dy-competitor"),
}
assert {item["content_id"] for item in industry["hotContents"]} == {
    "xhs-self-post",
    "xhs-other-post",
    "dy-other-post",
}
assert {item["platform"] for item in industry["comments"]} == {"xhs", "dy"}
```

这里保留 `xhs-self-post` 是方案 1 的明确取舍；抖音已有可信 owner ID，因此 `dy-self-post` 仍必须被排除。

- [ ] **Step 2: 运行工作流测试并确认接口不匹配或旧行为失败**

Run:

```bash
conda run --no-capture-output -n starx pytest -q tests/test_account_report_workflow.py::test_unknown_owner_platform_keeps_keyword_industry_evidence
```

Expected: FAIL；Task 1 删除参数后，工作流仍传递 `unknown_owner_platforms`，或旧工作流结果不包含小红书候选。

- [ ] **Step 3: 删除工作流中的未知 owner 平台状态**

在 `app/services/account_report/workflow.py` 中：

1. 删除初始化：

```python
known_owner_platforms: set[str] = set()
```

2. 删除两处：

```python
known_owner_platforms.add(plan.platform_code)
```

3. 删除 `unknown_owner_platforms` 集合计算。
4. 将证据构建恢复为只传可信 owner hash：

```python
evidence = build_report_evidence(
    current_account_results,
    industry_results,
    owner_hashes,
)
```

主页链接无效的 `record_notice(plan, mode="creator")` 保持不变。

- [ ] **Step 4: 扩展持久化白名单测试覆盖未知 owner 候选**

在 `test_persistence_filters_ai_candidates_through_separate_evidence_allowlists` 中，把最终断言改为同时接受可信的小红书未知 owner 候选与抖音竞品候选：

```python
assert [item["creatorHash"] for item in persisted["similarAccounts"]] == [
    unknown_hash,
    competitor_hash,
]
assert [item["creatorHash"] for item in persisted["topBloggerDetails"]] == [
    unknown_hash,
    competitor_hash,
]
```

继续断言抖音候选名称和主页链接由可信证据覆盖，并且 `evil.example` 不进入持久化结果。

- [ ] **Step 5: 运行账号报告工作流和证据测试**

Run:

```bash
conda run --no-capture-output -n starx pytest -q \
  tests/test_account_report_evidence.py \
  tests/test_account_report_workflow.py \
  tests/test_account_report_hot_content_urls.py \
  tests/test_account_report_owner_identity.py
```

Expected: 全部通过，无失败。

- [ ] **Step 6: 运行后端全量测试与补丁检查**

Run:

```bash
git diff --check
conda run --no-capture-output -n starx pytest -q
```

Expected: `git diff --check` 退出码 0；全量测试退出码 0。若外部 PostgreSQL 或 OSS 不可访问，必须单独报告环境失败，并保留 Task 5 的账号报告测试通过证据。

- [ ] **Step 7: 提交工作流修改**

```bash
git add app/services/account_report/workflow.py tests/test_account_report_workflow.py
git commit -m "fix: generate report from industry crawl without profile"
```

---

## 验收检查

- 主页缺失、短链或非主页链接时，小红书关键词结果仍进入行业证据。
- 没有可信 owner ID 时允许当前账号内容混入候选。
- 有可信 owner ID 的平台仍排除自身内容和账号。
- `sampleCount` 使用保留后的热门行业候选数量，不再因主页无效变为 0。
- 相似账号、爆款笔记、头部博主仍受 AI 候选白名单限制。
- 完整笔记链接和博主主页链接回填逻辑不回归。
