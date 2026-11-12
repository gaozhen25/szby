# 推荐选题星级展示实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**目标：** 将选题中心卡片左上角的固定“⭐ AI 推荐”恢复为 Kim 分支的 1–5 星推荐指数 UI。

**架构：** 仅在 `TopicCenter.jsx` 内恢复 Kim 的纯函数 `recommendStars(topic)`，由卡片渲染函数调用；不新增状态、组件或接口。测试继续采用项目现有的源码契约测试，锁定真实分值优先、无分值时稳定生成 3–5 星，以及不显示固定文案。

**技术栈：** React、JavaScript、Node.js 内置测试运行器（`node --test`）。

## 全局约束

- 直接复用 `origin/Kim` 中的 `recommendStars(topic)` 逻辑。
- 推荐标识只显示星星，不显示“AI 推荐”。
- 不使用 `Math.random()`，同一选题的无分值星数必须稳定。
- 不修改后端、不新增依赖、不改动卡片其他交互。

---

### 任务 1：恢复 Kim 推荐星级 UI

**文件：**
- 修改：`src/pages/TopicCenter.preview.test.js`
- 修改：`src/pages/TopicCenter.jsx`

**接口：**
- 输入：`recommendStars(topic)` 接收选题对象，可读取 `score`、`heat`、`recommendScore`、`recommend_score`、`id` 和 `title`。
- 输出：返回由 `⭐` 组成的字符串；真实有效分值对应 1–5 星，无有效分值时稳定返回 3–5 星。

- [ ] **步骤 1：先修改源码契约测试，使其描述 Kim 星级行为**

```js
test("topic cards preserve Kim CTA hierarchy and recommendation stars", () => {
  assert.match(topicCenterSource, /const recommendStars = \(topic\) =>/);
  assert.match(topicCenterSource, /topic\?\.score \?\? topic\?\.heat \?\? topic\?\.recommendScore \?\? topic\?\.recommend_score/);
  assert.match(topicCenterSource, /Math\.max\(1, Math\.min\(5/);
  assert.match(topicCenterSource, /return "⭐"\.repeat\(3 \+ \(hash % 3\)\)/);
  assert.match(topicCenterSource, /const stars = recommendStars\(topic\)/);
  assert.match(topicCenterSource, /title="推荐指数">\{stars\}/);
  assert.doesNotMatch(topicCenterSource, /⭐ AI 推荐/);
  assert.doesNotMatch(topicCenterSource, /Math\.random/);
  assert.match(topicCenterSource, /className="btn btn-create"/);
  assert.match(topicCenterSource, /去创作/);
  assert.match(topicCenterSource, /换一个/);
  assert.match(topicCenterSource, /收藏/);
  assert.match(styles, /\.btn-create\s*\{/);
  assert.match(styles, /\.topic-actions \.btn-ghost/);
  assert.match(styles, /\.topic-score\s*\{/);
});
```

- [ ] **步骤 2：运行目标测试，确认测试按预期失败**

运行：`node --test src/pages/TopicCenter.preview.test.js`

预期：FAIL，失败原因是 `TopicCenter.jsx` 尚未定义 `recommendStars`，仍含固定“⭐ AI 推荐”。

- [ ] **步骤 3：把 Kim 的星级计算和渲染代码原样恢复到当前组件**

在 `metaLabelWithEmoji` 后加入：

```js
const recommendStars = (topic) => {
  const raw = Number(topic?.score ?? topic?.heat ?? topic?.recommendScore ?? topic?.recommend_score);
  if (Number.isFinite(raw) && raw > 0) {
    const stars = Math.max(1, Math.min(5, Math.round(raw <= 5 ? raw : raw / 20)));
    return "⭐".repeat(stars);
  }
  const seed = String(topic?.id || topic?.title || "topic");
  let hash = 0;
  for (let i = 0; i < seed.length; i += 1) hash = (hash * 31 + seed.charCodeAt(i)) >>> 0;
  return "⭐".repeat(3 + (hash % 3));
};
```

在 `card` 中计算星数并替换固定文案：

```jsx
const stars = recommendStars(topic);
```

```jsx
<div className="topic-score" title="推荐指数">{stars}</div>
```

- [ ] **步骤 4：运行目标测试，确认通过**

运行：`node --test src/pages/TopicCenter.preview.test.js`

预期：全部 PASS。

- [ ] **步骤 5：运行前端完整测试与构建验证**

运行：`npm test`

预期：全部测试 PASS。

运行：`npm run build`

预期：Vite 构建成功，无编译错误。

- [ ] **步骤 6：提交实现**

```bash
git add src/pages/TopicCenter.preview.test.js src/pages/TopicCenter.jsx
git commit -m "fix: restore Kim topic recommendation stars"
```
