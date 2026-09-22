# freeze-stop-inflight-agents — 增量规格（解冻续做锚点耐久）

## MODIFIED Requirements

### Requirement: 解冻后在保留分支自动续做

`unfreeze_spec` 恢复原状态时，若该 spec 的 `_frozen_hold` 为真，MUST 先做保留判定：
`branch` 在册、分支可解析、且相对 main 有未合并提交（`git rev-list --count main..<branch> > 0`）、
且载体可用。判定通过 → MUST 输出与 `interrupt-recovery-preserve` 的恢复保留**同源**的
更新集：`status` 置为原状态、保留 `branch` / `implementer_run`、置 `_recovery_resume: True`、
清 `_frozen_hold`。

保留判定 MUST NOT 以「调用方是否显式传入 `project_root` / `worktree_manager`」为前置
条件：该上下文缺失时，`unfreeze_spec` MUST 由 spec 名自解析项目根（或经实例持有上下文）
后再尝试保留判定。核心不变量——**带 `_frozen_hold` 的解冻 ⇔ 保留分支被续做，或显式
告警降级；MUST NOT 静默丢弃保留分支锚点**。

worktree 已被清理、只剩分支（在册 worktree 无命中）时，MUST 经分支命名空间枚举
（`find_branches_by_spec`）定位保留分支并**记录续做分支**（`branch` 锚点保留 /
`_recovery_resume` 置位），使 dispatch 在该分支上 resume；MUST NOT 因载体（worktree）
缺失而整体丢弃分支锚点，转而从 main 新建分支（将使保留分支不再被枚举、已交付实现被弃）。

判定不通过（无 branch / 零提交 / 分支缺失）→ MUST 清 `_frozen_hold`、不置
`_recovery_resume`、走普通重派，并 WARNING 留痕。

解冻的既有清理行为（清 `error` / `frozen_until` / `frozen` 及各计数）MUST 保持不变。

#### Scenario: 解冻命中保留分支续做

- **WHEN** 某 spec 带 `_frozen_hold: True` 且其保留分支相对 main 有未合并提交，用户解冻
- **THEN** STATE 恢复为冻结前状态、`branch`/`implementer_run` 保留、`_recovery_resume: True`、
  `_frozen_hold: False`；dispatch 拾取后在保留分支的 worktree 上 resume 续做，不新建分支

#### Scenario: 未传上下文的解冻仍不丢弃保留分支

- **GIVEN** 某 spec 带 `_frozen_hold: True` 与保留分支，且其 worktree 已清理
- **WHEN** 调用方以**不含** `project_root` / `worktree_manager` 的形式解冻该 spec
- **THEN** `unfreeze_spec` 自解析项目根后完成保留判定，保留分支锚点被采用（`branch` 保留
  / `_recovery_resume: True`）
- **AND** MUST NOT 因上下文缺失而落「新轮次派发清除旧锚点」从 main 新建分支

#### Scenario: 载体缺失仍保留续做分支

- **GIVEN** 某 spec 的保留分支相对 main 有未合并提交，但其 worktree 目录已清理
- **WHEN** 解冻该 spec
- **THEN** 经分支命名空间枚举定位保留分支并记录为续做分支（`branch` 锚点保留 /
  `_recovery_resume: True`），dispatch 重建 worktree 后在该分支 resume

#### Scenario: 保留判定不通过降级

- **WHEN** 某 spec 带 `_frozen_hold: True` 但其分支无未合并提交（或分支缺失）
- **THEN** 解冻后清 `_frozen_hold`、不置 `_recovery_resume`，spec 按原状态正常派发（从零），
  并留有 WARNING 记录降级原因

#### Scenario: 无 _frozen_hold 的解冻行为不变

- **WHEN** 解冻一个从未被冻结终止的 spec（`_frozen_hold` 缺失）
- **THEN** 解冻行为与改动前逐位一致，不触发任何续做接线
