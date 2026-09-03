## ADDED Requirements

### Requirement: 跨项目概览视图
Dashboard 首页 MUST 展示监控的所有项目，每个项目显示：项目名、SPEC 总数、各状态计数（如 drafted/ready/implementing/testing/verified/done/pushed/bug-found）、任务总进度（已完成/总数 + 百分比进度条）、问题/阻塞数、活跃 Agent 运行数。首页 MUST 每 2 秒自动刷新（轮询 `/api/overview`），并允许用户点击项目下钻到 SPEC 列表。

#### Scenario: 概览展示多个项目统计
- **WHEN** 监控列表包含两个项目且各有多个 SPEC
- **THEN** 首页同时展示两个项目的卡片，各卡片状态计数、进度条与问题数与后端聚合结果一致

#### Scenario: 概览自动刷新
- **WHEN** 页面打开 2 秒后后端状态发生变化
- **THEN** 页面自动更新为最新状态，无需手动刷新

### Requirement: SPEC 详情视图
点击某个 SPEC 后 MUST 进入详情视图，展示：名称、状态、优先级、创建/更新时间、错误信息；任务清单（按 tasks.md 分组、勾选状态）；验证进度（`.fenix/verify-progress/<spec>.json`）；场景级测试结果（`report.json` 中每个场景的 pass/fail/warn/error 与断言详情）；bug 列表（失败/错误场景聚合 + `verification-report.md` 中的 bug 段尽力解析）；失败截图缩略图（点击放大）。验证阶段存在截图与场景结果时 MUST 一并展示。

#### Scenario: 详情展示任务与验证结果
- **WHEN** 某 SPEC 处于 testing 状态且已有 report.json 与进度文件
- **THEN** 详情页显示任务分组与勾选、验证进度条、逐场景结果及失败场景的断言信息

#### Scenario: 失败截图展示与放大
- **WHEN** 某失败场景存在截图文件
- **THEN** 详情页以缩略图形式展示该截图，点击可查看大图

### Requirement: 运行中 Agent 实时活动与 LLM 对话展示
SPEC 详情视图 MUST 展示该 SPEC 相关的运行记录列表（来自 `.fenix/runs/`），每条记录显示 run_id、Agent 类型、状态（运行中/已完成/异常终止）、起始时间。对「运行中」的记录 MUST 自动刷新并实时渲染其产物流：LLM 对话（assistant 文本、user 消息）、工具调用（tool_use 名称与输入摘要）、工具结果摘要、最终 result/error 事件。对长时间无输出的运行，MUST 仍能展示已捕获的事件（来自 jsonl 追加流），使用户可见「Fenixd 此刻在干什么」。

#### Scenario: 运行中对话实时渲染
- **WHEN** 某 implementer 运行中且 jsonl 持续追加 assistant 与 tool_use 事件
- **THEN** 详情页的该运行记录实时渲染这些对话与工具调用，无需页面刷新

#### Scenario: 异常终止可见
- **WHEN** 某运行因超时或错误终止
- **THEN** 记录状态显示「异常终止」，并展示 error 终态事件内容与已捕获的部分对话

### Requirement: 秒级数据刷新
所有视图的数据刷新周期 MUST 不超过 2 秒；刷新不得造成页面闪烁或滚动位置丢失（详情视图滚动位置在刷新时保持）。

#### Scenario: 刷新不丢滚动位置
- **WHEN** 用户在详情页滚动到中部且触发自动刷新
- **THEN** 页面内容更新但滚动位置保持不变
