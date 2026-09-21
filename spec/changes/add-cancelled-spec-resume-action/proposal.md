## Why

SPEC 的实现 run 被人工取消后（Dashboard「取消 run」），daemon 写入 `_cancelled_hold: true` 保持态（fix-cancel-holdstate-recovery）。该状态是「有意等待」：全部自动恢复链路（重启恢复 / stuck 检测 / 孤儿恢复）对其显式跳过，设计上「唯一出路是显式复位」。但 Dashboard 至今没有提供这个显式复位入口：

- 「修改状态」弹窗对取消保持态 SPEC 只渲染冻结/预算区块，没有任何可执行操作；
- spec 列表摘要不下发 `_cancelled_hold` 字段，用户在界面上完全看不到 SPEC 处于保持态；
- 唯一恢复手段是手写 STATE.md（`update_spec` 携带 status + branch + `_recovery_resume` 三件套 + scheduling_kick），2026-09-21 在 fix-impl-code-review-writepath 上人工执行过一次，步骤易错且有丢工作风险（漏写 `_recovery_resume`/branch 会清锚点、从 main 重建分支，丢弃保留分支上的全部已提交成果）。

## What Changes

- Dashboard「修改状态」弹窗新增「恢复运行」区块：对处于取消保持态（`_cancelled_hold: true`）的非终态 SPEC 渲染，点击后复位为 ready 并即时唤醒派发。
- 后端新增恢复动作（dashboard admin action + 路由）：复用 `_resolve_preserved_branch` 共享判定（STATE.branch → 在册 worktree → 分支命名空间枚举三层回落），判定通过走保留分支续做（`_recovery_resume: True`），判定不通过降级普通重派并 WARNING 留痕；动作后写 scheduling_kick 信号即时派发，不等 30 分钟周期扫描。
- 列表摘要与 spec 详情下发 `cancelled_hold` 字段，前端据此条件渲染，且让用户能看出「该 SPEC 因人工取消被挂起」。
- 恢复动作同时是取消保持态的唯一界面出口，语义与冻结终止的「解冻续做」（`unfreeze_spec` + `_frozen_hold`）对齐。

## Capabilities

### New Capabilities
- `cancelled-spec-resume`: 被取消保持 SPEC 的界面恢复能力——取消保持态识别、保留分支续做复位、即时派发唤醒、终态/非保持态幂等拒绝。

### Modified Capabilities

## Impact

- `core/dashboard/data/admin_actions.py`：新增 `resume_cancelled_spec` 动作（复用 StateMachine/WorktreeManager/signals 既有单点）。
- `core/dashboard/data/summary.py`：spec 摘要新增 `cancelled_hold` 字段（`spec_detail` 同步）。
- `core/dashboard/routes/spec_routes.py` + `base.py`：新增 POST 路由 `/api/spec-resume`。
- `core/dashboard/static/src/services/dashboard.ts`：新增 API 封装。
- `core/dashboard/static/src/pages/projects/components/SpecStatusModal.tsx`：新增「恢复运行」区块（危险操作确认）。
- `core/dashboard/static/dist/`：前端产物需 `npm run build` 重建（gitignored，运行时重建）。
- 不改 daemon 派发/恢复链路本体——`_recovery_resume` 的消费与 `_resolve_preserved_branch` 判定均为既有单点，本 spec 只做界面接线。
