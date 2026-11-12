# 账号报告博主主页链接实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**目标：** 让新生成的账号报告将相似账号和头部博主的公开真实昵称、可信主页链接保存到数据库，并允许前端直接打开主页，同时确保这些真实资料不进入 AI prompt。

**架构：** MediaSpider 在内部 `CrawlResult` 中保留公开展示资料；账号报告证据模型同时携带展示字段和已有脱敏字段，再通过独立 AI 投影显式移除展示资料。AI 完成分析后，workflow 只按 `platform + creatorHash` 从可信证据回填真实昵称和主页链接，前端复用报告归一化阶段的安全 URL 校验。

**技术栈：** Python 3.12、Pydantic 2、FastAPI、SQLAlchemy JSON、pytest、React 18、Node.js `node:test`、Vite。

## 全局约束

- 所有后端 Python 命令必须使用名为 `starx` 的 conda 环境。
- AI prompt 不得包含公开真实昵称、主页链接或原始用户 ID。
- 小红书完整公开笔记链接允许进入 AI prompt；现有 `note_url` 必须包含采集结果提供的 `xsec_token` 与 `xsec_source`。
- 主页链接只允许从稳定平台 ID 构造为支持平台的 HTTPS 正式域名。
- `similarAccounts` 和 `topBloggerDetails` 继续使用现有 JSON 数据库列，不增加 Alembic 迁移。
- 历史报告不回填；缺少 `profileUrl` 时前端必须降级为普通文本。
- 不修改候选数量、排序、合规分析、用户画像或选题下游契约。
- `complianceRules` 必须同时包含现有证据风险与行业预防风险；无证据时不得声称违规已经发生，也不得编造法规条款。
- 后端仓库当前存在其他未提交改动；每次编辑和暂存前必须检查差异，只提交本计划相关行。

---

## 文件结构

- 修改 `app/services/mediaspider/runtime/collector.py`：统一构造三个平台的可信公开主页链接，并保留原始公开昵称。
- 修改 `app/services/mediaspider/stores/xhs.py`、`douyin.py`、`kuaishou.py`：把稳定原始创作者 ID 传给统一构造器。
- 修改 `app/services/mediaspider/stores/xhs.py`：同时使用标准 URL 编码把详情记录中的笔记访问参数写入现有 `note_url`。
- 修改 `app/services/account_report/models.py`：为内部创作者证据增加展示字段；为持久化输出模型增加可选 `profileUrl`。
- 新建 `app/services/account_report/ai_evidence.py`：把完整报告证据投影为仅供 AI 使用的脱敏字典。
- 修改 `app/services/account_report/evidence.py`：从采集结果保留展示字段，排名与去重仍沿用现有逻辑。
- 修改 `app/services/account_report/prompts.py`：只序列化 AI 安全投影。
- 修改 `app/services/account_report/prompts.py`：明确行业合规提醒的证据复盘与未来风险推演规则。
- 修改 `app/services/account_report/workflow.py`：白名单过滤后从可信证据回填真实昵称和主页链接。
- 修改 `src/utils/accountReport.js`：归一化账号 `profileUrl` 为 `safeProfileUrl`。
- 修改 `src/pages/account-report/AccountReportSections.jsx`：三个账号展示位置复用安全账号链接组件。
- 修改 `src/styles/pages.css`：增加账号主页链接的 hover/focus 样式。
- 修改对应后端与前端测试文件，覆盖安全边界、持久化和交互。

---

### Task 1：MediaSpider 保留可信公开展示资料

**文件：**

- 修改：`app/services/mediaspider/runtime/collector.py`
- 修改：`app/services/mediaspider/stores/xhs.py`
- 修改：`app/services/mediaspider/stores/douyin.py`
- 修改：`app/services/mediaspider/stores/kuaishou.py`
- 测试：`tests/test_mediaspider_runtime.py`

**接口：**

- 输入：`build_safe_creator(platform: str, raw_id: Any, raw: dict[str, Any])`
- 输出：现有安全创作者字典新增 `display_name: str` 与 `profile_url: str`；`nickname` 仍是脱敏名称。
- 输出：`update_xhs_note` 保存完整 `note_url`；缺少 `xsec_token` 或 `xsec_source` 时保存基础链接。
- 约束：`profile_url` 只能由 `platform + raw_id` 构造，不能直接信任 `raw` 中的 URL。

- [ ] **Step 1：先写三个平台链接和真实昵称的失败测试**

在 `tests/test_mediaspider_runtime.py` 导入 `build_safe_creator`，增加参数化测试：

```python
@pytest.mark.parametrize(
    ("platform", "raw_id", "expected_url"),
    [
        ("xhs", "xhs-user", "https://www.xiaohongshu.com/user/profile/xhs-user"),
        ("dy", "dy-sec-user", "https://www.douyin.com/user/dy-sec-user"),
        ("ks", "ks-user", "https://www.kuaishou.com/profile/ks-user"),
    ],
)
def test_safe_creator_preserves_public_display_fields(platform, raw_id, expected_url):
    creator = build_safe_creator(platform, raw_id, {"nickname": "公开博主名称"})

    assert creator["display_name"] == "公开博主名称"
    assert creator["nickname"] != "公开博主名称"
    assert creator["profile_url"] == expected_url
    assert raw_id not in creator["creator_hash"]
```

再增加非法平台或空 ID 不生成链接的测试：

```python
def test_safe_creator_does_not_copy_untrusted_profile_url():
    creator = build_safe_creator(
        "unknown",
        "raw-user",
        {"nickname": "公开名", "profile_url": "javascript:alert(1)"},
    )
    assert creator["profile_url"] == ""
```

增加小红书完整笔记链接测试：

```python
def test_xhs_store_preserves_complete_note_url_with_search_token():
    result = asyncio.run(_collect_xhs_note({
        "note_id": "6a411e68000000000701114b",
        "xsec_token": "ABsEQjfB8dALwX2ljCtVLnK3wzfUu9tWlrIFgxVCVfq50=",
        "xsec_source": "pc_search",
        "user": {"user_id": "raw-user", "nickname": "张三"},
        "interact_info": {},
    }))

    assert result.contents[0]["note_url"] == (
        "https://www.xiaohongshu.com/explore/6a411e68000000000701114b"
        "?xsec_token=ABsEQjfB8dALwX2ljCtVLnK3wzfUu9tWlrIFgxVCVfq50%3D"
        "&xsec_source=pc_search"
    )
```

- [ ] **Step 2：运行测试并确认 RED**

运行：

```bash
conda run --no-capture-output -n starx pytest tests/test_mediaspider_runtime.py -k 'safe_creator_preserves_public_display_fields or safe_creator_does_not_copy_untrusted_profile_url or xhs_store_preserves_complete_note_url' -q
```

预期：因缺少 `display_name`、`profile_url`，且 `note_url` 不含查询参数而失败。

- [ ] **Step 3：实现统一主页链接构造和真实昵称保留**

在 `collector.py` 增加私有映射与构造器：

```python
_PROFILE_URL_TEMPLATES = {
    "xhs": "https://www.xiaohongshu.com/user/profile/{creator_id}",
    "dy": "https://www.douyin.com/user/{creator_id}",
    "ks": "https://www.kuaishou.com/profile/{creator_id}",
}


def _public_profile_url(platform: str, raw_id: Any) -> str:
    creator_id = str(raw_id or "").strip()
    template = _PROFILE_URL_TEMPLATES.get(str(platform or "").strip().lower())
    if not template or not creator_id:
        return ""
    return template.format(creator_id=quote(creator_id, safe="-._~"))
```

`build_safe_creator` 返回值增加：

```python
"display_name": str(nickname).strip()[:100],
"profile_url": _public_profile_url(platform, raw_id),
```

保留现有 `nickname: mask_nickname(nickname)`。三个 store 的 `save_creator` 继续将平台稳定原始 ID 作为 `raw_id` 参数传入，不把任意 URL 传入构造器。

`stores/xhs.py` 使用 `urllib.parse.urlencode` 构造笔记链接：

```python
def _note_url(note_id: Any, xsec_token: Any, xsec_source: Any) -> str:
    base_url = f"https://www.xiaohongshu.com/explore/{quote(str(note_id), safe='-._~')}"
    token = str(xsec_token or "").strip()
    source = str(xsec_source or "").strip()
    if not token or not source:
        return base_url
    return f"{base_url}?{urlencode({'xsec_token': token, 'xsec_source': source})}"
```

`update_xhs_note` 把 `note_item.get("xsec_token")` 和 `note_item.get("xsec_source")` 传入该函数，结果仍写入现有 `note_url`。

- [ ] **Step 4：运行定向测试并确认 GREEN**

运行：

```bash
conda run --no-capture-output -n starx pytest tests/test_mediaspider_runtime.py -q
```

预期：该文件全部通过；完整 `note_url` 被保留，现有进度事件仍只展示脱敏 `nickname`，不会读取 `display_name`。

- [ ] **Step 5：检查并提交后端采集边界改动**

```bash
git diff --check
git add app/services/mediaspider/runtime/collector.py app/services/mediaspider/stores/xhs.py app/services/mediaspider/stores/douyin.py app/services/mediaspider/stores/kuaishou.py tests/test_mediaspider_runtime.py
git commit -m "feat: preserve creator profile display data"
```

---

### Task 2：分离完整创作者证据与 AI 安全投影

**文件：**

- 修改：`app/services/account_report/models.py`
- 修改：`app/services/account_report/evidence.py`
- 新建：`app/services/account_report/ai_evidence.py`
- 修改：`app/services/account_report/prompts.py`
- 测试：`tests/test_account_report_evidence.py`

**接口：**

- `CreatorEvidence` 新增 `display_name: str = Field(default="", alias="displayName")`、`profile_url: str = Field(default="", alias="profileUrl")`。
- 新函数 `build_ai_evidence(evidence: ReportEvidence) -> dict[str, Any]` 产生与当前 prompt 相同的顶层结构，但每个创作者只含脱敏允许字段。
- `build_account_report_prompt(...)` 改为调用 `build_ai_evidence`，不再直接 `model_dump` 完整证据。
- `build_account_report_prompt(...)` 的 `complianceRules` 指令要求覆盖证据风险与行业预防风险，输出结构保持不变。

- [ ] **Step 1：写证据保留和 AI 投影的失败测试**

在 `tests/test_account_report_evidence.py` 增加：

```python
def test_creator_display_data_is_preserved_but_removed_from_ai_evidence():
    evidence = build_report_evidence(
        [],
        [CrawlResult(
            platform="xhs",
            crawl_type="search",
            creators=[{
                "creator_hash": "0123456789abcdef",
                "nickname": "公***称",
                "display_name": "公开博主名称",
                "profile_url": "https://www.xiaohongshu.com/user/profile/public-id",
            }],
        )],
        set(),
    )

    creator = evidence.industry.similar_accounts[0]
    assert creator.display_name == "公开博主名称"
    assert creator.profile_url.endswith("/public-id")

    ai_evidence = build_ai_evidence(evidence)
    serialized = json.dumps(ai_evidence, ensure_ascii=False)
    assert creator.name in serialized
    assert "公开博主名称" not in serialized
    assert "public-id" not in serialized
    assert "profileUrl" not in serialized
    assert "displayName" not in serialized
```

增加合规生成边界的 prompt 测试：

```python
def test_report_prompt_requires_evidence_and_predictive_industry_compliance_rules():
    prompt = build_account_report_prompt(
        {"account": {"industry": "美妆", "productService": "功效护肤", "platforms": ["小红书"]}},
        empty_report_evidence(),
        {"platforms": ["小红书"]},
    )

    assert "证据复盘风险" in prompt
    assert "行业预防风险" in prompt
    assert "即使公开样本中暂未出现" in prompt
    assert "不得把预防性风险描述为当前账号已经违规" in prompt
    assert "不得编造法规编号、处罚结果或平台公告" in prompt
```

- [ ] **Step 2：运行测试并确认 RED**

运行：

```bash
conda run --no-capture-output -n starx pytest tests/test_account_report_evidence.py::test_creator_display_data_is_preserved_but_removed_from_ai_evidence -q
```

预期：证据测试因 `CreatorEvidence` 或 `build_ai_evidence` 尚不存在而失败；合规 prompt 测试因缺少新指令而失败。

- [ ] **Step 3：实现模型字段、证据读取与独立 AI 投影**

`evidence._creator` 从原始字典读取：

```python
display_name=str(_first(raw, "display_name"))[:100],
profile_url=str(_first(raw, "profile_url"))[:1000],
```

`ai_evidence.py` 为每个创作者显式输出：

```python
def _creator(item: CreatorEvidence) -> dict[str, Any]:
    return {
        "platform": item.platform,
        "creatorHash": item.creator_hash,
        "name": item.name,
        "fansCount": item.fans_count,
        "worksCount": item.works_count,
        "interactionCount": item.interaction_count,
        "hitContentCount": item.hit_content_count,
        "representativeContents": list(item.representative_contents),
    }
```

内容和评论同样使用显式字段白名单；最终返回 `currentAccountEvidence`、`industryEvidence`、`ownerHashes`。`prompts.py` 改为：

```python
"evidence": build_ai_evidence(evidence),
```

在报告主指令中增加以下明确约束，保持 JSON 契约不变：

```text
complianceRules 必须同时覆盖“证据复盘风险”和“行业预防风险”。证据复盘风险来自当前账号或行业公开内容；行业预防风险要结合账号行业、产品/服务、目标受众、转化目标与目标平台推演，即使公开样本中暂未出现也必须覆盖后续创作容易踩坑的具体表达。没有证据时不得把预防性风险描述为当前账号已经违规，不得编造法规编号、处罚结果或平台公告。
```

- [ ] **Step 4：运行证据与 prompt 测试并确认 GREEN**

运行：

```bash
conda run --no-capture-output -n starx pytest tests/test_account_report_evidence.py tests/test_account_report_workflow.py -k 'evidence or prompt or privacy or sensitive' -q
```

预期：相关测试全部通过，prompt 安全断言仍成立。

- [ ] **Step 5：提交 AI 边界改动**

```bash
git diff --check
git add app/services/account_report/models.py app/services/account_report/evidence.py app/services/account_report/ai_evidence.py app/services/account_report/prompts.py tests/test_account_report_evidence.py
git commit -m "feat: separate report display and ai evidence"
```

---

### Task 3：可信合并并持久化主页链接

**文件：**

- 修改：`app/services/account_report/models.py`
- 修改：`app/services/account_report/workflow.py`
- 测试：`tests/test_account_report_workflow.py`
- 测试：`tests/test_db_service.py`

**接口：**

- `SimilarAccount` 与 `TopBlogger` 新增 `profile_url: str = Field(default="", alias="profileUrl")`。
- 新私有函数 `_merge_creator_display_data(report: AccountReportPayload, evidence: ReportEvidence) -> AccountReportPayload`。
- `_persistence_payload` 的外部字段名保持不变，只让列表项包含 `profileUrl`。

- [ ] **Step 1：写 workflow 可信回填的失败测试**

扩展 `test_filters_ai_candidates_to_crawled_creator_records` 或新增独立测试，使 crawler 返回：

```python
{
    "creator_hash": competitor_hash,
    "nickname": "竞***称",
    "display_name": "真实竞品名称",
    "profile_url": "https://www.douyin.com/user/dy-competitor",
}
```

AI 对同一合法候选返回伪造名称，并额外携带 `profileUrl: "https://evil.example/user"`。最终断言：

```python
assert persisted["similarAccounts"][0]["name"] == "真实竞品名称"
assert persisted["similarAccounts"][0]["profileUrl"] == "https://www.douyin.com/user/dy-competitor"
assert persisted["topBloggerDetails"][0]["name"] == "真实竞品名称"
assert persisted["topBloggerDetails"][0]["profileUrl"] == "https://www.douyin.com/user/dy-competitor"
assert "evil.example" not in json.dumps(persisted)
```

为兼容性增加无展示字段候选测试，断言仍保存 AI 脱敏名称且 `profileUrl == ""`。

- [ ] **Step 2：运行测试并确认 RED**

运行：

```bash
conda run --no-capture-output -n starx pytest tests/test_account_report_workflow.py -k 'creator_display or crawled_creator_records' -q
```

预期：最终名称仍来自 AI，且没有可信 `profileUrl`。

- [ ] **Step 3：实现证据索引和不可伪造的回填**

在 `workflow.py` 为相似账号和头部博主分别按 `_candidate_key` 建立索引。白名单过滤之后执行：

```python
def _with_display_data(item, source):
    updates = {"profile_url": source.profile_url}
    if source.display_name:
        updates["name"] = source.display_name
    return item.model_copy(update=updates)
```

`_merge_creator_display_data` 分别使用 `evidence.industry.similar_accounts` 与 `evidence.industry.top_bloggers`，避免跨候选集合取值。workflow 的顺序必须为：解析 AI 输出 → `_filter_report_candidates` → `_merge_creator_display_data` → 评论逐字校验 → `_persistence_payload`。

Pydantic 模型保持默认忽略 AI 输出中的未知 `profileUrl`；最终值始终被可信证据覆盖。

- [ ] **Step 4：验证 workflow 与数据库 JSON 往返**

在 `tests/test_db_service.py` fixture 的 `similarAccounts` 和 `topBloggerDetails` 增加 `profileUrl`，断言 replace/read 后字段未变化。运行：

```bash
conda run --no-capture-output -n starx pytest tests/test_account_report_workflow.py tests/test_db_service.py -q
```

预期：两份测试全部通过。

- [ ] **Step 5：提交可信持久化改动**

```bash
git diff --check
git add app/services/account_report/models.py app/services/account_report/workflow.py tests/test_account_report_workflow.py tests/test_db_service.py
git commit -m "feat: persist trusted creator profile links"
```

---

### Task 4：前端安全归一化和可点击主页

**文件：**

- 修改：`../starx-frontend/src/utils/accountReport.js`
- 修改：`../starx-frontend/src/utils/accountReport.test.js`
- 修改：`../starx-frontend/src/pages/account-report/AccountReportSections.jsx`
- 修改：`../starx-frontend/src/pages/AccountReport.preview.test.js`
- 修改：`../starx-frontend/src/styles/pages.css`

**接口：**

- `normalizeStructuredReport` 为相似账号和头部博主增加 `safeProfileUrl`，值为合法 HTTP(S) URL 或空字符串。
- `CreatorProfileName({ creator, fallback })` 只读取 `creator.safeProfileUrl`，决定渲染 `<a>` 或普通文本。

- [ ] **Step 1：写安全 URL 归一化失败测试**

在 `accountReport.test.js` 的结构化报告 fixture 中加入合法和恶意主页链接，断言：

```javascript
assert.equal(structured.similarAccounts[0].safeProfileUrl, "https://www.douyin.com/user/abc");
assert.equal(structured.similarAccounts[1].safeProfileUrl, "");
assert.equal(structured.topBloggerDetails[0].safeProfileUrl, "https://www.xiaohongshu.com/user/profile/xyz");
```

恶意 fixture 使用 `javascript:alert(1)`，并保留一个缺失字段的历史报告 fixture。

- [ ] **Step 2：运行测试并确认 RED**

运行：

```bash
npm test -- src/utils/accountReport.test.js
```

工作目录：`../starx-frontend`。预期：账号项没有 `safeProfileUrl`，断言失败。

- [ ] **Step 3：实现账号链接归一化**

复用现有 `isSafeHttpUrl`，为两个列表映射：

```javascript
function withSafeProfileUrl(item) {
  return {
    ...item,
    safeProfileUrl: isSafeHttpUrl(item?.profileUrl) ? item.profileUrl : "",
  };
}
```

不得在 JSX 中直接使用未经归一化的 `profileUrl`。

- [ ] **Step 4：写三个展示位置的失败预览测试**

在 `AccountReport.preview.test.js` 断言 section 源码包含一个统一组件、`safeProfileUrl`、`target="_blank"` 和 `rel="noopener noreferrer"`，并且相似账号概览、详情与头部博主都调用该组件。

- [ ] **Step 5：实现统一名称链接组件与样式**

在 `AccountReportSections.jsx` 增加：

```jsx
function CreatorProfileName({ creator, fallback, className = "" }) {
  const label = creator?.name || fallback;
  if (!creator?.safeProfileUrl) return <span className={className}>{label}</span>;
  return (
    <a
      className={`creator-profile-link ${className}`.trim()}
      href={creator.safeProfileUrl}
      target="_blank"
      rel="noopener noreferrer"
    >
      {label}
    </a>
  );
}
```

替换三处名称渲染。`pages.css` 增加不破坏现有布局的颜色继承、下划线和 `:focus-visible` 轮廓。

- [ ] **Step 6：运行前端定向测试和构建**

工作目录：`../starx-frontend`。

```bash
npm test -- src/utils/accountReport.test.js src/pages/AccountReport.preview.test.js
npm run build
```

预期：测试全部通过，Vite 构建退出码为 0。

- [ ] **Step 7：提交前端改动**

在 `../starx-frontend` 仓库执行：

```bash
git diff --check
git add src/utils/accountReport.js src/utils/accountReport.test.js src/pages/account-report/AccountReportSections.jsx src/pages/AccountReport.preview.test.js src/styles/pages.css
git commit -m "feat: link report creators to profiles"
```

---

### Task 5：全链路回归与需求审计

**文件：**

- 审查：本计划涉及的所有文件
- 不新增生产行为；仅在发现测试遗漏或边界错误时回到对应 Task 修正。

**接口：** 无新增接口。

- [ ] **Step 1：运行后端账号报告完整回归**

工作目录：`starx-backend`。

```bash
conda run --no-capture-output -n starx pytest \
  tests/test_mediaspider_runtime.py \
  tests/test_account_report_evidence.py \
  tests/test_account_report_workflow.py \
  tests/test_account_report_api.py \
  tests/test_db_service.py -q
```

预期：全部通过且 0 failures。

- [ ] **Step 2：运行后端完整测试**

```bash
conda run --no-capture-output -n starx pytest -q
```

预期：全部通过且 0 failures；若存在与本次无关的既有失败，必须记录失败测试、错误信息和与本次差异的关系，不能宣称完整测试通过。

- [ ] **Step 3：运行前端完整测试与构建**

工作目录：`starx-frontend`。

```bash
npm test
npm run build
```

预期：全部通过，构建退出码为 0。

- [ ] **Step 4：执行隐私与持久化静态审计**

在 `starx-backend` 执行：

```bash
rg -n 'displayName|profileUrl|display_name|profile_url' app/services/account_report app/services/mediaspider tests
git diff --check
```

逐项确认：

1. `build_account_report_prompt` 只调用 `build_ai_evidence`；
2. AI 输出契约不要求 `profileUrl`；
3. 最终 `profileUrl` 只从证据索引合并；
4. 数据库 JSON 和 API 保留新字段；
5. 前端 JSX 只使用 `safeProfileUrl`；
6. 历史缺失链接不会产生不可点击的空 `<a>`。
7. AI 证据中的 `ContentEvidence.publicUrl` 仍保留由小红书 `note_url` 映射的完整公开笔记链接。
8. prompt 明确要求 `complianceRules` 同时覆盖证据复盘与行业预防风险，并禁止把推演伪装成已发生事实。

- [ ] **Step 5：检查两个仓库的最终差异和提交范围**

```bash
git -C starx-backend status --short
git -C starx-backend log -5 --oneline
git -C starx-frontend status --short
git -C starx-frontend log -5 --oneline
```

预期：本功能文件已提交；用户原有未提交改动仍被保留且未混入本功能提交。
