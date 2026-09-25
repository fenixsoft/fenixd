# add-freeze-stop-inflight-agents — Proposal

## Why

用户冻结一个 SPEC（写 `blocked + frozen:True`）的语义是「停止推进、等人工裁决」，但框架只挡住**边界**——runner 的两处 frozen 检查（`_attempt_top_guards` / `_should_give_up_before_retry`）都只在 attempt / 重试边界执行，而真正管着 agent 进程的 `_run_claude` 轮询环**只查 run-cancel 旗标，不看 spec 的 frozen 字段**。冻结对在飞 attempt 是空操作。

2026-09-20 实证：`fix-cr-robustness` 于 03:10 被冻结，其 implementer 进程照跑 39 分钟，期间反复撞 503 重试（`api_retry` 至第 9 次），持续空烧 token；只能靠人工写 `cancel_run_request.json` 才停下。2026-09-18 同类事故（`evo-merge-back-wip-artifact-scope`）冻结后 agent 又跑了 8 分钟，最终被 daemon 重启排水 SIGTERM 掉。

同时，用户冻结/删除一个 SPEC 时，其名下**任何**在跑 agent（评审 reviewer、实现 implementer、出题 planner、判定 judge、修复 repair、fast-track）都应在该 SPEC 不再推进的前提下停止——现状是只有 run 粒度的人工取消才能做到，与「冻结/删除一个 SPEC 就整体停住」的直觉相悖。

SPEC 删除路径同源：`soft_delete_spec` 对 120 秒内活跃的 run 只**拒绝**（409），既不停止也不给用户任何推进手段。

## What Changes

- **冻结即停（核心）**：`_run_claude` 轮询环（1 秒粒度）在既有 run-cancel 旗标检查旁增加 frozen 检查。命中 → 先对当前 worktree 做 WIP checkpoint 保全 → `terminate()` → 最长 10 秒宽限 → 存活则 `kill()` → 向 run 产物追加 `frozen-terminated` 终态行 → 抛独立异常（与 `RunCancelledError` 并列，**不复用取消语义**）。
- **冻结终止独立终态**：新增 `_frozen_hold` 标记（与 `_cancelled_hold` 并列、互不读写），记录「被冻结终止、现场已保全、待解冻续做」。冻结终止的 run 不重试、不重派、不翻转 status（保持 blocked + frozen）。
- **解冻自动续做**：`unfreeze_spec` 恢复原状态时，若检测到 `_frozen_hold` 且保留分支相对 main 有未合并提交 → 走与 `_recovery_preserve_spec` **同源**的输出（保留 `branch` / `implementer_run` + 置 `_recovery_resume: True`），dispatch 在保留分支上 resume 续做（而非从零新建分支）。无提交/无分支则清标记走普通重派。
- **覆盖该 SPEC 名下全部 agent**：冻结时的停止动作按 spec 归属匹配在该册全部 run（复用 `run_spec_part` 全等归属），不限于主链路 run。
- **删除先停再删（异步受理）**：`soft_delete_spec` 的 120 秒硬拦改为「请求停止该 SPEC 全部在跑 run → 等终态（有界）→ 软删除」。API 侧改为异步受理（202 + `stopping: N`），前端提示「正在停止 N 个进行中的 agent」并轮询刷新，spec 行几秒内消失。
- **前端反馈**：冻结操作后行内提示「已停止 N 个在跑 agent，进度已留存」；删除确认弹窗与 toast 展示停止计数。

## Capabilities

### New Capabilities

- `freeze-stop-inflight-agents`: 冻结 SPEC 即终止其名下全部在跑 agent——轮询环 frozen 检查、冻结终止独立终态、终止前 WIP 保全、`_frozen_hold` 标记与解冻后保留分支自动续做。
- `delete-stop-inflight-agents`: 删除 SPEC 前先终止其名下全部在跑 agent 并等待终态（有界）再软删除；API 异步受理与前端停止计数反馈。

### Modified Capabilities

（无。既有 `run-cancel` / `interrupt-recovery-preserve` / `cancel-holdstate-durability` 能力的 requirement 不变——新增冻结终止走并行独立通道，不改它们的契约。）

## Impact

**核心链路（5 层）**

- `core/agent_runner/runner.py`：轮询环 frozen 检查、`FrozenTerminatedError`、run 产物 `frozen-terminated` 终态行、attempt 顶守卫与收口分型复用。
- `core/state_machine.py`：`_frozen_hold` 标记（序列化键表 + 布尔转换 + 解冻时清除）、`freeze_spec` 保全分支锚点、`unfreeze_spec` 续做接线。
- `core/pm_engine/dispatch/`：冻结终止结果的 hold-state 分支（对齐 `_cancelled_hold` 的既有落点，但不写 `_cancelled_hold`）。
- `core/dashboard/data/`：`soft_delete_spec` 等待语义、`freeze_spec` 返回值扩展（`stopped_agents` 计数）。
- `core/dashboard/routes/spec_routes.py`：`/api/spec-delete` 异步受理。

**前端**

- `core/dashboard/static/src/pages/projects/list.tsx`（删除/冻结反馈与轮询）。
- `core/dashboard/static/src/services/dashboard.ts`（返回类型扩展）。

**依赖与风险**

- 与既有 run-cancel 通道**并行独立**：两者可同时存在，frozen 优先级高于取消（冻结是 spec 级、取消是 run 级）。
- 与 `interrupt-recovery-preserve` 复用同一保全/续做机制（`wip_checkpoint` + `_recovery_resume` + `resolve_resume_site`），不新建第二套。
- 风险点：daemon 未受 supervisor 托管（`unmanaged`）时文件信号无人消费——删除异步受理必须前置托管态校验（对齐 `request_spec_approve_push` 既有契约）。
