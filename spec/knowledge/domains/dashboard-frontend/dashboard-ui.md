<!-- knowledge: capability=dashboard-ui rev=1 sources=spec/archive/2026-09-02-add-fenix-dashboard -->

# 仪表盘基础界面

Dashboard 前端的三大视图骨架与秒级刷新约束，是其余前端能力的载体。

## 现行规则

- 仪表盘前端提供概览、项目详情与实时运行对话三类视图，数据经 SSE 与 API 双通道刷新。
- 跨项目概览视图展示全部监控项目：项目名、SPEC 总数、各状态计数、任务总进度（已完成/总数 + 百分比进度条）、问题/阻塞数、活跃 Agent 运行数；每 2 秒自动刷新（轮询 `/api/overview`），点击项目下钻到 SPEC 列表。
- SPEC 详情视图展示：名称、状态、优先级、创建/更新时间、错误信息；任务清单（按 tasks.md 分组、勾选状态）；验证进度（`.fenix/verify-progress/<spec>.json`）；场景级测试结果（report.json 每场景 pass/fail/warn/error 与断言详情）；bug 列表（失败/错误场景聚合 + verification-report.md bug 段尽力解析）；失败截图缩略图（点击放大）。验证阶段存在截图与场景结果时一并展示。
- 运行记录视图：展示 SPEC 相关的运行记录列表（来自 `.fenix/runs/`），每条含 run_id、Agent 类型、状态（运行中/已完成/异常终止）、起始时间；「运行中」记录自动刷新并实时渲染产物流——LLM 对话（assistant 文本、user 消息）、工具调用（tool_use 名称与输入摘要）、工具结果摘要、最终 result/error 事件；长时间无输出的运行仍展示已捕获的 jsonl 追加事件，使用户可见「Fenixd 此刻在干什么」。
- 刷新约束：所有视图的数据刷新周期不超过 2 秒；刷新不得造成页面闪烁或滚动位置丢失（详情视图滚动位置在刷新时保持）。

## 溯源

- 史前复原 — 仪表盘概览/项目详情/实时运行对话三视图与 SSE + API 双通道刷新骨架
- [2026-09-02 add-fenix-dashboard](spec/archive/2026-09-02-add-fenix-dashboard/) — 建立跨项目概览、SPEC 详情（任务/验证/场景/bug/截图）与运行中对话实时渲染契约及 ≤2 秒刷新约束
