# Proposal: fix-redispatch-loop-governance

## Why

2026-09-17 `fix-robustness-edge-cases` 事故暴露了「run 层成功 ≠ spec 层成功」这一结构性裂缝的完整后果：实现 Agent **每一轮都真实干完 14/15 任务**、写出正确的 `status: "partial"` 结果文件、如实把最后一条任务（人工运维门控）申报为 `unattainable`——然后被 spec 层的收口判定判为失败重派。连烧 **3 轮、每轮约 $18**，且**每轮的 5 个提交整支丢弃**（分支从未并入 main），最后要靠人工抢救分支才把成果捞回来。

直接根因（已原地修复，见 `core/run_task_track.gap_from_result`）：诚实退出的三处消费在缺 `unfinished` 时回退读**主树** `tasks.md` 勾选，而主树 `[x]` 只在成功/merge-back 路径由 `_sync_task_progress` 回写——partial 收敛恰恰走不到那条路径，构成**读侧自锁**。

但根因修复只堵了「读错源」这一个洞。同一个事故还暴露了三个**尚未治理**的缺口：

1. **没有重派熔断**：读源缺陷存在期间，框架连续 3 轮对**同一 spec、同一终局**热派新 run，无任何「同因重派达 N 轮即冻结转人工」的护栏。若有，损失可从 3 轮降到 1 轮。
2. **成果不继承**：run 层「成功」（`result.success=True`）时 `cleanup(success=True)` 会清理 worktree、`keep_for_reuse` 只在失败路径触发——于是「run 成功但 spec 层判失败」时**必然从零重派**（新 worktree、从 main 起），前一轮成果仅存在于分支上。
3. **收敛链的对称性与边界未固化**：full 车道与 fast-track 车道各有一份 `honest_exit_gap` 用法，二者是否等价、收敛后是否必然走到 merge-back + verifier、中间会不会被零变更哨/交付物守卫打断——均无契约锁定。

## What Changes

- **固化「诚实退出收敛」的正确形态为可测契约**：run 层成功 + `partial` + 缺口 ⊆ `unattainable` ⇒ 收敛为 `implemented`（`is_success=True`、`final_error=None`）⇒ 走既有成功路径（零变更哨判定 → 交付物守卫 → relint → merge-back → 入队 verifier）。MUST NOT 因缺口非空而判失败重派。
- **统一缺口口径的反回退保护**：三处消费点（`dispatch._honest_exit_gap` / `engine._partial_attribution` / `engine._task_completion_blocker`）MUST 统一走 `core.run_task_track.gap_from_result`；MUST NOT 存在任何「缺 `unfinished` 时回退读主树 tasks.md 勾选」的路径。加**结构性守卫测试**防回潮。
- **重派熔断**：对同一 spec 的**同因**重派（如连续多轮 `partial` 且缺口集合不变、或连续多轮以同一归因文案判失败）达阈值即冻结转人工 + 人工升级告警，MUST NOT 无限热派。
- **成果继承**：`partial` 收敛失败（确有未申报缺口、或收敛后卡在后续门）时，重派 MUST 保留 worktree 现场与分支成果供下轮继承（`keep_for_reuse` 语义扩展到该形态），MUST NOT 从零重建。
- **两条车道对齐**：full 车道与 fast-track 车道的诚实退出收敛 MUST 语义等价（同一判据、同一收口动作序列、同一可观测留痕），差异须在 design 中显式记录并说明理由。

## Capabilities

### New Capabilities

- `honest-exit-convergence`: 诚实退出收敛的完整契约——收敛判据、缺口口径单点、收敛后的收口动作序列、两条车道对称性、可观测留痕。

- `redispatch-loop-governance`: 重派循环治理——同因重派熔断阈值与冻结动作、成果继承（worktree/分支不重建）、与既有预算计数/死亡豁免的关系。

### Modified Capabilities

（无——本变更不修改既有 spec 级行为要求）

## Impact

- **代码**：`core/pm_engine/dispatch.py`（`_honest_exit_gap` 收敛判据与两条车道调用点、重派熔断）、`core/pm_engine/engine.py`（`_partial_attribution` / `_task_completion_blocker`）、`core/run_task_track.py`（`gap_from_result` 契约）、`core/agent_runner/runner.py`（`keep_for_reuse` 触发点扩展）。
- **API**：零变化（全部为内部收口逻辑）。
- **测试**：新增收敛链契约测试、车道对称测试、重派熔断测试、成果继承测试；`tests/test_honest_exit_convergence.py` 扩充。
- **风险**：重派熔断阈值过紧会误冻真实需要多轮修复的 spec——design MUST 给出「同因」的机械判据（缺口集合不变 / 归因文案指纹相同）与保守阈值。
- **运行时**：改 `dispatch.py` / `runner.py`，daemon 需重启生效（`restart_request` 信号，由 supervisor 消费）。
