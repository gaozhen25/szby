# 账号报告四板块独立生成与重生成设计

## 背景

账号报告页面只展示四个核心板块：相似账号、行业合规提醒、目标用户画像、爆款笔记参考。现有工作流虽然会并行执行 AI 分块，但产品层仍把整份报告视为一个生成单元，用户无法只更新其中一个板块。

## 目标

- 四个可见板块各自提供“重新生成”入口。
- 单板块任务只调用目标板块的 AI 契约。
- 单板块完成后只替换目标板块，不清空或覆盖另外三个已发布板块。
- “重新生成全部”继续复用完整账号采集与报告工作流。
- 生成失败时保留原报告内容。

## 接口契约

整份报告继续使用：

- `POST /api/v1/accounts/{account_id}/report/workflows`

四个板块分别使用独立接口，不再由前端向统一接口传 `sectionKey`：

- `POST /api/v1/accounts/{account_id}/report/similar-accounts/workflows`
- `POST /api/v1/accounts/{account_id}/report/compliance-rules/workflows`
- `POST /api/v1/accounts/{account_id}/report/target-user-profile/workflows`
- `POST /api/v1/accounts/{account_id}/report/hot-contents/workflows`

所有接口请求体只包含 `referenceComments`。后端由路由固定板块，调用方不能通过请求体改写任务目标。旧版统一接口的 `sectionKey` 暂时保留兼容。账号同一时刻仍只允许一个账号报告任务；已有任务执行中时复用该任务，避免采集与写入竞争。

## 工作流设计

任务沿用账号档案、知识库、公开内容采集、证据归一化与来源校验链路。完整任务和四个板块分别注册为五种 workflow 类型：

- `account_report`
- `account_report_similar_accounts`
- `account_report_compliance_rules`
- `account_report_target_user_profile`
- `account_report_hot_contents`

四个板块 workflow 类在代码中明确声明自己的板块键，不能依赖外部输入改变生成目标；公共采集和持久化管线由基类复用，避免复制长流程。

单板块工作流的进度载荷包含：

- `reportSectionKey`：当前目标板块；
- `reportSectionsTotal: 1`；
- `reportSectionsCompleted`：完成后只包含目标板块；
- `reportPreview`：来源元数据与目标板块预览。

## 持久化设计

完整任务继续原子替换整份结构化报告。单板块任务使用独立的局部更新方法，在同一数据库事务内更新：

1. 目标结构化字段；
2. 对应的旧版中文摘要字段；
3. 本次采集的 `sourceMeta`；
4. `reportVersion` 与 `generatedAt`。

载荷未包含的报告字段保持不变。持久化层使用字段允许列表，拒绝隐藏分析字段和空板块更新，防止调用方借局部接口覆盖其他报告数据。

## 前端交互

- 页面右上角入口显示“重新生成全部”。
- 四张报告卡片各自显示“重新生成”。
- 单板块执行时保留当前已发布内容，目标卡片按钮显示“生成中…”。
- 为避免同一报告并发写入，任务执行期间禁用其他生成按钮和评论开关。
- 单板块任务不展示整页加载动画；完整任务仍展示采集和生成过程。
- 轮询完成后重新读取服务端报告，以服务端局部合并结果为准。

## 兼容性与验证

- 不增加数据库列，不需要迁移历史数据。
- 原有不带 `sectionKey` 的客户端行为不变。
- 旧版摘要字段同步更新，下游仍可读取兼容数据。
- 测试覆盖请求校验、目标分块唯一调用、局部字段保留、前端请求透传、四卡片入口、轮询与生产构建。
