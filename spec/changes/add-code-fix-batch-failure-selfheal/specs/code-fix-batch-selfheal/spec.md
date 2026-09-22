## ADDED Requirements

### Requirement: 失败批现场即弃与锁释放

自动修复车道的全部批失败路径 MUST 在收尾前清理 worktree（`_safe_cleanup`），不得保留现场等待人工。其中「两次回归均失败」与「合回冲突」两条原保留现场路径，MUST 在 cleanup 前把 `branch` 与 `tip_sha`（分支末梢提交 SHA）写入失败档案记录。

#### Scenario: 合回冲突批失败后 worktree 被清理且锁释放
- **WHEN** 某批合回 `merge_back` 返回失败（merge_back_conflict）
- **THEN** 该批 worktree 目录被清理、`code-review-fix:code-fix` 进程内 spec 锁被释放，后续批次的 `worktree_manager.create()` 不再被该锁拒绝

#### Scenario: 两次回归失败批不再保留现场
- **WHEN** 某批两次全量回归均未通过（regression_failed_twice）
- **THEN** 该批 worktree 被清理（替代原「保留 worktree MUST NOT cleanup」语义），失败档案记录含 `branch`、`tip_sha`、`reason="regression_failed_twice"`、`failed_at`

### Requirement: 批收尾三态与链自驱动条件

`_run_batch_inner` 的收尾返回 MUST 为三态：`success`（批成功合回并核销）、`consumed`（该批条目已全部离开可选池：批成功、两次回归失败、合回冲突、agent run 失败、重试 run 失败）、`halt`（环境性失败：worktree_create_failed、worktree_manager_missing、批 worker 异常）。批 worker 对 `success` 与 `consumed` 均 MUST 执行 `_resubmit()` 推进下一批；仅 `halt` 终止链。

#### Scenario: 合回冲突批失败后链继续推进下一批
- **WHEN** 第 N 批以 merge_back_conflict 收尾（consumed）
- **THEN** 编排器自驱动再投递，第 N+1 批从剩余可选条目中选批启动，进度 `current` 含「第 N 批失败已跳过」文案

#### Scenario: 两次回归失败批失败后链继续推进下一批
- **WHEN** 第 N 批以 regression_failed_twice 收尾（consumed）
- **THEN** 编排器自驱动再投递下一批，剩余可选条目继续被消费

#### Scenario: agent run 失败批链继续且条目入链内跳过集
- **WHEN** 某批首次修复 run 失败（agent_run_failed）或重试 run 失败（regression_retry_run_failed）
- **THEN** 该批条目写入进度快照 `chain_skipped` 字段，worktree 清理，链继续推进下一批；条目不进入 fix-failed.json 永久档案

#### Scenario: 环境性失败保持链终止
- **WHEN** 批收尾为 halt（worktree_create_failed / worktree_manager_missing / 批 worker 异常）
- **THEN** 链终止（不自驱动），条目保持 open，进度 phase=failed，行为与既有语义一致

#### Scenario: consumed 循环必然收敛
- **WHEN** 链内连续多批以 consumed 失败收尾
- **THEN** 每批条目均移出可选池（失败档案 ∪ chain_skipped），可选池严格单调缩小，链在可选池为空时正常收尾，不发生无限空转

### Requirement: 链内跳过集生命周期

进度快照 MUST 新增 `chain_skipped` 字段（条目 id 列表）。`select_batch` 的排除口径 MUST 为「失败档案条目并集 ∪ chain_skipped」。新链启动（进度快照无 live 链、activation_id 更替）时 MUST 重置 `chain_skipped` 为空。

#### Scenario: 链内跳过条目本链不再被选批
- **WHEN** 条目 X 因 agent run 失败进入 chain_skipped
- **THEN** 同链后续 select_batch 不再选中 X；其他可选条目正常组批

#### Scenario: 新链启动重置链内跳过集
- **WHEN** 上一链已终止、新链激活（checkpoint 判定非同一 activation_id）
- **THEN** `chain_skipped` 重置为空，上链被瞬态跳过的条目重新进入可选池

### Requirement: 失败档案重试预算

`fix-failed.json` 记录 MUST 新增 `fail_count`（缺省 1）、`reason`、`branch`、`tip_sha`、`failed_at` 字段；同条目集（item_id 集合相同）再次失败时 MUST 复用既有记录并 `fail_count` 递增（不追加重复记录）。新链启动时 MUST 自动释放 `fail_count < FAIL_RETRY_MAX`（常量，取 3）的记录（条目回到可选池，实现下轮自动重试）；`fail_count ≥ FAIL_RETRY_MAX` 的记录保持跳过、不再释放。

#### Scenario: 失败条目下轮自动重试
- **WHEN** 某批（fail_count=1）失败入档，其后新链启动
- **THEN** 该记录被自动释放（无需人工 release_failed_batch），条目重新可选并被下轮组批消费

#### Scenario: 同条目集再失败递增 fail_count 而不重复入档
- **WHEN** 同一条目集的批在下轮再次以 regression_failed_twice 或 merge_back_conflict 入档
- **THEN** 原记录 `fail_count` 递增（1→2），`reason`/`branch`/`tip_sha`/`failed_at` 刷新，不新增记录

#### Scenario: 达到重试上限后永久跳过并一次性告警
- **WHEN** 某条目集的 `fail_count` 递增至 FAIL_RETRY_MAX（3）
- **THEN** 入档当时发一条 warning 级告警（列明条目与原因），该记录此后不再被新链释放；重复链启动不重复发告警

#### Scenario: 混合预算档案的选择性释放
- **WHEN** 新链启动时档案中存在 fail_count=1、fail_count=2、fail_count=3 三条记录
- **THEN** 仅 fail_count<3 的两条被释放，fail_count=3 的记录条目保持不可选
