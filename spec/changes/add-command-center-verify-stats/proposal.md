# Change: add-command-center-verify-stats

## Why

新版三段验证流水线（`agents.use_new_verifier=True` 默认启用）下，验证由 planner-plan 出题 → VerifyEngine 进程内机械执行 → planner-judge 判定完成，**全程不产生任何 `verify-` 前缀 run 文件**（VerifyEngine 纯进程内执行，无 LLM、无 run 产物）。而指挥中心「验证」车道卡的统计唯一来源是 `verify-` 前缀 run（`core/agent_runner/run_files.py` 车道前缀映射）。结果是：只要启动了验证（无论是否派 agent），验证活动在指挥中心完全不可见——验证卡恒 0 run、恒 idle。实证：`.fenix/runs/` 全量仅 5 个 legacy `verify-` run（全在 archive），而 `.fenix/verify-progress/` 下大量 SPEC 走过新版验证。

## What Changes

- `aggregate_org`（`core/dashboard/data/command_center.py`）读侧新增 verify-progress 聚合：每项目扫 `.fenix/verify-progress/<spec>/report.json`（终态验证轮）与 `.fenix/verify-progress/<spec>.json`（进度摘要在飞信号），折入 verifier 车道卡既有字段（runs/success_rate/activity_14d/last_activity_ts/status/attributables），窗口口径（today/7d/all）与既有 run 统计一致。
- 统计口径（用户已定稿「读侧聚合」方向）：runs 计「窗内有验证产物的 SPEC 数」（report.json 每轮原子覆盖、无轮次历史，读侧不造历史）；success_rate 采用轮级执行口径 `errors==0 → done`（场景级 fail 是产品缺陷发现，不计入执行成功率分母）；在飞 = 进度摘要 `done<total` 且 mtime 落新鲜窗（15 分钟，对齐 admin_monitor 孤儿判定阈值）。
- 前端小改（`core/dashboard/static/src/pages/command-center/shared.ts`）：`AttributableRun.run_id` 放宽为可空 + `activityLineState` 主路径过滤器容忍空 run_id——在飞验证无 run 文件，归属条目不可点开运行记录弹窗（渲染端 legacy 路径已容忍空 run_id，渲染零改动）。
- 纯读侧聚合：不新增写路径、不合成 run 文件、不新增端点，`verify-` 前缀的全部既有消费方（`_cancel_lane_runs` / verify 单飞 / admin_monitor 失败计数）零触碰。

## Capabilities

### New Capabilities

（无）

### Modified Capabilities

- `command-center-aggregation`：org 车道卡聚合的统计源从「仅 run 文件」扩展为「run 文件 + verify-progress 产物」，verifier 车道卡新增验证活动可见性。Delta 见 `specs/command-center-aggregation/spec.md`（能力既有 spec：`spec/archive/2026-11-02-add-command-center-spec-view/specs/command-center-aggregation/spec.md`）。

## Impact

- 受影响代码：`core/dashboard/data/command_center.py`（aggregate_org 读侧聚合 + verify-progress 助读函数）、`core/dashboard/static/src/pages/command-center/shared.ts`（类型 + 过滤器约 3 行）。
- 测试：`tests/test_command_center_aggregation.py` 增补 verify-progress 折入用例。
- 零影响面：验证流水线写路径（verify_engine / pm_engine）、run 文件消费方、指挥中心其余四端点（kpi/pipeline/ledger/inbox）、既有 run 统计口径。
- 风险：低——纯读侧新增数据源，防御性跳过脏产物即可，不改变既有键语义（折入既有字段，MUST NOT 新增响应键）。
