# spec-mergeback-inplace-repair（delta）

## ADDED Requirements

### Requirement: repair 成功的待合并状态持久化

repair run 到达终态成功时，框架 MUST 在 re-merge-back 执行**之前**写入一个持久的「待 re-merge-back」标记（该 spec 的实现分支已含 main 的合并且冲突已解决，仅剩重新合并进主树这一步）。

该标记 MUST 在以下时机清除：re-merge-back 成功（转入 `implemented`）；同一失败链进入下一轮 repair；或该失败链放弃并回退 fallback 重派。标记 MUST NOT 在 repair run 运行期间写入——只有终态成功才写。

现状缺口：repair run 运行期与「repair 已成功但 re-merge 未执行」两态在 STATE 中**完全同形**（`status=implementing`、`_repair_round` 同值、`branch` 同为 null），恢复链无法区分，只能按「被打断的在飞实现」处理。该标记是这一区分的唯一持久化表达。

#### Scenario: repair 成功即落标记

- **WHEN** repair run 返回终态 success，re-merge-back 尚未执行
- **THEN** STATE 存在该 spec 的待 re-merge-back 标记，且实现分支与 run_id 已记录

#### Scenario: 标记在 re-merge 成功后清除

- **WHEN** re-merge-back 成功并把 spec 推进为 `implemented`
- **THEN** 该标记被清除，MUST NOT 残留在 `implemented` 及其后状态上

#### Scenario: repair 运行期不写标记

- **WHEN** repair run 正在运行（尚未返回终态）
- **THEN** STATE 无该标记，恢复链仍按「在飞实现」语义处理

#### Scenario: 超轮次回退时清除标记

- **WHEN** 同一失败链内 repair 已达轮次上限并回退 fallback 全新重派
- **THEN** 该标记被清除，新实现轮次从干净状态开始

### Requirement: re-merge 成功路径的锚点先于载体清理

re-merge-back 成功路径中，实现分支与 `implementer_run` 写入 STATE 的动作 MUST 发生在**清理 repair worktree 之前**。

现状顺序为先 `wm.cleanup(wt_path, success=True)` 再 `update_spec({branch: …})`：在两步之间存在一个「载体已删、锚点未写」的窗口，daemon 若落在该窗口内退出，则锚点与载体同时不可得（分支名仍可用 `recovery-branch-anchor` 的命名空间回落救回，但 ORDER 缺陷本身 MUST 消除）。

#### Scenario: 先落锚点再清载体

- **WHEN** re-merge-back 成功，框架随即清理 repair worktree
- **THEN** 清理动作执行时 STATE 的 `branch` 已被写入，MUST NOT 出现「worktree 已删而 branch 仍为 null」的中间态

## MODIFIED Requirements

### Requirement: 修复方向反转与主树干净态

repair agent MUST 在实现分支一侧修复：把 main merge 进分支并解决冲突后 commit。派发 repair 前框架 MUST 保证主树处于 merge abort 后的干净态。repair 期间主树无需冻结：其他 spec 的 merge-back 可照常推进主树；repair 完成后的 re-merge-back 若因主树再度前进产生新冲突，按既有冲突处理路径与熔断计数处理。

repair run 运行期间 spec 的 `status` MUST 保持 `implementing`（repair 是 implementing 内部的一条车道，不引入新状态）。为使该状态在重启后仍可区分「在飞」与「已修复待合并」，MUST 同时满足「repair 成功的待合并状态持久化」要求——运行期与该要求所写的标记共同构成完整的状态表达。

#### Scenario: 主树保持干净

- **WHEN** repair agent 被派出
- **THEN** 主树处于 merge abort 后的干净态，不残留半合并文件

#### Scenario: repair 运行期的可区分性

- **WHEN** daemon 在 repair run 运行期间重启
- **THEN** 该 spec 无待 re-merge-back 标记，恢复链按「在飞实现」语义处理

#### Scenario: repair 已成功的可区分性

- **WHEN** daemon 在 repair run 已成功、re-merge-back 尚未执行时重启
- **THEN** 该 spec 存在待 re-merge-back 标记，恢复链 MUST 据此走 re-merge-back 路径（见 `interrupt-recovery-preserve` 的「恢复期消费待 re-merge-back 标记」）
