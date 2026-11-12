# 账号报告权威来源元数据设计

## 背景

账号报告工作流会在采集完成后，由服务端根据真实执行结果构造并校验 `SourceMeta`。完整报告提示词同时要求 AI 返回 `sourceMeta`，当前解析器会先对 AI 返回的完整对象执行 `AccountReportPayload` 校验；工作流只有在校验成功后，才会用服务端 `SourceMeta` 覆盖 AI 返回值。

当 AI 返回 `failedPlatforms: ["小红书"]` 时，Pydantic 因契约要求 `list[dict]` 而拒绝报告。该字段随后本应被服务端权威值覆盖，因此当前流程错误地让一个不可信且最终不会采用的 AI 元数据阻断了报告生成。

## 目标

- 服务端生成并校验的 `SourceMeta` 是账号报告来源元数据的唯一可信来源。
- 在完整 `AccountReportPayload` 校验前注入权威 `sourceMeta`，避免 AI 返回的等价或错误元数据阻断报告。
- `similarAccounts`、`complianceRules`、`targetUserProfile`、`hotContents`、`topBloggers`、`contentStrategy` 继续执行现有严格校验。
- 不改变持久化结构、API 响应结构、采集流程或报告字段上限。

## 非目标

- 不把任意字符串形式的 `failedPlatforms` 猜测转换成失败摘要对象。
- 不放宽独立调用 `parse_account_report` 时的默认校验规则。
- 不在本次修复中增加 AI 重试、修改提示词总体结构或迁移数据库。

## 方案比较

### 方案一：校验前注入服务端权威 `sourceMeta`（采用）

为 `parse_account_report` 增加仅限关键字参数 `trusted_source_meta`。调用方提供该参数时，解析器先完成 JSON 解码和现有等价字段归一化，再用权威值替换 AI 返回的 `sourceMeta`，最后执行完整 Pydantic 校验。

优点：信任边界清晰；直接消除当前顺序缺陷；仍能校验权威元数据本身；其他报告字段保持严格。缺点：解析器接口增加一个可选参数。

### 方案二：将字符串失败平台归一化成对象

在 `response_normalizer` 中把 `"小红书"` 转换为 `{"platform": "小红书"}`。

优点：改动小。缺点：缺少 `mode` 和 `reason`，需要猜测语义；会让不可信 AI 数据暂时通过模型校验；不能处理其他 AI 元数据幻觉，因此不采用。

### 方案三：只强化提示词

在 JSON 示例中加入完整失败摘要对象，并要求 AI 原样复制输入 `sourceMeta`。

优点：不改解析接口。缺点：模型输出不具备确定性，无法建立可靠边界；同类格式偏差仍可能再次阻断工作流，因此不作为根修。

## 数据流

1. 工作流根据平台计划、采集结果和失败分类构造 `SourceMeta`，并立即通过 Pydantic 校验。
2. 工作流将该值序列化为别名格式，既作为提示词输入，也作为 `trusted_source_meta` 传给报告解析器。
3. 解析器只接受裸 JSON 或完整 JSON fence，保持现有语法约束。
4. 解析器执行现有 AI 等价字段归一化。
5. 若提供 `trusted_source_meta`，解析器在完整模型校验前替换 AI 的 `sourceMeta`。
6. `AccountReportPayload` 对六个 AI 分析块和权威来源元数据一起执行严格校验。
7. 候选过滤、安全检查和持久化流程保持不变；持久化前现有的服务端元数据覆盖可继续保留，作为纵深防护。

## 接口与边界

解析接口调整为：

```text
parse_account_report(raw: str, *, trusted_source_meta: dict[str, Any] | None = None) -> AccountReportPayload
```

- 参数为关键字专用，避免既有位置调用产生歧义。
- 未提供参数时行为完全不变：错误的 AI `sourceMeta` 仍会被严格拒绝。
- 提供参数时不做字符串猜测或字段补造，直接交给 `AccountReportPayload` 统一校验。
- 账号报告工作流是本次唯一新增的参数调用方。

## 错误处理

- 非法 JSON、缺失报告块、非法风险等级、空关键文本等继续失败。
- 服务端权威 `sourceMeta` 若不满足模型约束仍会失败，不允许绕过校验。
- AI 返回的 `sourceMeta` 无论缺失、类型错误或内容幻觉，都不会覆盖服务端权威值。
- 本次不改变工作流失败状态和 scheduler 异常传播语义。

## 测试策略

采用红—绿测试流程：

1. 解析器回归测试：AI 返回 `failedPlatforms: ["小红书"]`，同时传入合法权威元数据；修复前应复现当前 `ValidationError`，修复后应成功且结果只包含权威失败摘要。
2. 严格性测试：不传 `trusted_source_meta` 时，同一错误 AI 元数据仍必须被拒绝。
3. 工作流回归测试：模拟 AI 返回错误 `sourceMeta`，验证工作流成功持久化，最终 `failedPlatforms` 等于服务端采集结果而不是 AI 值。
4. 运行账号报告解析、工作流和数据库相关测试，确认没有回归。

## 验收标准

- 用户日志中的 `sourceMeta.failedPlatforms.0` 字符串错误不再导致账号报告工作流失败。
- 持久化报告的 `sourceMeta` 与服务端采集状态一致。
- AI 其他六个报告块仍严格遵守现有契约。
- 所有新增与相关既有测试通过。
