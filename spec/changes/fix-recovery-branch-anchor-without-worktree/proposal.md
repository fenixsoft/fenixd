## Why

2026-09-14 `fix-impl-tasks-completion-gate` 滞留 7h42m，根因不是卡死，而是 **daemon 重启把一轮已完工的实现整轮丢弃后从零重做**（白烧约 3 小时 + 一次实现预算）。

该 spec 的实际进度：00:48 派发 → 01:36 全部交付物实现完毕（tasks.md 勾满 1.1–9.6）→ 05:31 跑完有界全量回归（4155s / 3152 passed，17 项失败与基线逐字一致）→ 05:32 implementer succeeded → merge 预演检出 2 处语义冲突 → 直通 repair 通道 → **05:36:32 repair 成功**（分支 `fenix/fix-impl-tasks-completion-gate-1789318103` 已 merge main 并解决冲突，随时可 fast-forward 进 main）。

05:36:44 daemon 重启，`recover_interrupted` 判定「实现被打断」，写 `status=ready / implementer_run=null / branch=null` 并重派，05:36:45 在**全新分支**上从 main 重写一遍。

保留路径当时**本可命中**：分支在 git refs 里、已 merge main、相对 main 有未合并提交，完全满足 `interrupt-recovery-preserve` 的「有提交分支保留并续做」判据。它失败的原因只有一个——**框架无法叫出这个分支的名字**：

1. **`branch` 登记滞后于 run 生命周期。** `branch` 只在 merge-back **成功之后**才写入 STATE（`core/pm_engine/dispatch.py:2774-2785` repair re-merge 成功处、`:2497` fast-track、`:1045` implementer）。本次走了 repair 通道，那条写 `branch` 的代码从未执行——事故 spec 全部 17 条 `state_machine` 更新中无任何一条写入过非空 `branch`。**一切「已实现、未合并」的在飞状态，STATE.branch 恒为 null。**
2. **回落源只认在册 worktree。** `_recovery_preserve_spec`（`core/state_machine.py:905-919`）在 STATE 无 branch 时回落 `worktree_manager.find_worktree_by_spec`，而该查询的真相源是 `git worktree list --porcelain`（`core/worktree_manager.py:3140`）——**只读 worktree 注册，全仓无任何 `git branch --list`**。此刻两个 worktree 都已不在册：实现 worktree 随成功收口被清（21:32:20 `Cleaning up worktree … (success=True)`），repair worktree 被关闭期孤儿清扫摘掉（21:36:40 `Cleaning up orphan: …/repair-…`）。
3. **排水「干净收口」是假信号，保全 sidecar 从未写。** `_preserve_interrupted_runs` 仅在 `drain_wait` 返回非空（排水超时）时触发（`fenixd.py:1718-1721`）。本次 repair agent 在排水窗口内自行退出，`remaining runs: []` → 不写 sidecar；而保护集 `protected = set(preserved_wts)`（`fenixd.py:1749`）只由 sidecar 构造 → **空集** → `cleanup_orphans(protected=∅)` 无差别清理。注意 repair worktree 此刻**仍在 `git worktree list` 注册表中**，本可保住。
4. **静默早退。** `core/state_machine.py:918` `if not branch: return False` 无任何日志——本次兜底失败零留痕，只能靠下游「建了新分支」这一间接信号推断。

净效果：`fenix/fix-impl-tasks-completion-gate-1789318103` 一直在 git 里躺着、已可 fast-forward，**没有任何代码去看它一眼**。

与既有 `fix-preserve-chain-first-round-gap`（09-12 已推）的关系：那个 SPEC 已定位同一类缺陷（「`branch` 登记滞后于 run 生命周期」），其处方是「回落到 git 事实查询」，但事实源选了**在册 worktree** 并明确保留「STATE `branch` 为完成态记录，语义不变」。**本变更处理的是它的补集**——「run 已成功、worktree 已清、branch 未落盘」这个它未覆盖的窗口，不是重复立项。

## What Changes

- **A｜锚点提前落盘（治本）**：implement / repair run 到达**终态成功**时，在 merge-back 之前把 `branch` 与 `implementer_run` 写入 STATE。`branch` 语义由「已合并分支」变为「**本轮实现分支**」；消费点普查结论：唯一按「是否已合并」分支的消费点 `core/pm_engine/verification.py:5248-5253` 问的是 git（`_branch_merged_into_tree`）而非字段值，无需改动。
- **B｜回落源扩容（兜底）**：保留判据在「STATE.branch 缺失 ∧ 无在册 worktree」时再回落一层 **git 分支命名空间**——按 `worktree.implement_branch_prefix`（缺省 `fenix`）枚举 `refs/heads/<prefix>/<spec>-*`，优先取 `main` 为其祖先者（正好识别「repair 已把 main 合入分支」形态），其次取 `rev-list --count main..<branch>` 最大者。
- **C｜「已修复待合并」显式可表达**：repair run 成功时（re-merge-back 之前）写入持久标记；恢复路径见到 `implementing + 该标记` → 走 re-merge-back 而非重派 implementer。消除「无任何字段能区分『还在飞』与『run 已成功只剩合并』」的现状。
- **D｜关闭期载体保护**：保护集构造增加一路来源（STATE 中 `implementing` spec 的在册 worktree），不再只依赖 sidecar；sidecar 触发条件从「排水超时」放宽到「排水结束后仍存在收口未完成的 implementing spec」；`cleanup_stale_worktrees` 的 `git branch -D` 前置检查在飞 spec 的分支引用。
- **E｜锚点缺失必须出声**：保留判据的早退路径与清空重派路径 MUST 打 WARNING，并附分支命名空间命中的候选清单。
- **顺序修复**：repair re-merge 成功路径把 `update_spec(branch=…)` 提到 `wm.cleanup(wt_path)` **之前**（现状先删锚点载体、后写锚点值，happy path 上留有同类窗口）。

**BREAKING**：无。`branch` 的取值集合不变，仅写入时机提前；无配置项语义变更，无数据迁移。

## Capabilities

### New Capabilities

- `recovery-branch-anchor`: 恢复锚点的**来源与存在性**契约——(i) 实现/repair run 产出成功即落盘 `branch`/`implementer_run`；(ii) 锚点缺失时的 git 分支命名空间枚举与候选排序；(iii) 锚点不可得时的强制留痕。

### Modified Capabilities

- `interrupt-recovery-preserve`: 「恢复保留分支续做」的 branch 来源改为经 `recovery-branch-anchor` 解析（含命名空间回落）；「清理协调」的保护集来源扩容并明确「保护集不得因 sidecar 未写而退化为空集」。
- `mergeback-inplace-repair`: 补「repair 成功即落待 re-merge-back 标记」与「re-merge 成功路径先落 branch 再清 worktree」两条约束；明确 repair 运行期 `status` 保持 `implementing` 时的可恢复性要求。
- `agent-shutdown-interrupt`: 关闭期保护集来源与 sidecar 触发条件；stale worktree 清扫删分支前的在飞引用检查。

## Impact

**代码**

| 文件 | 改动 |
|---|---|
| `core/state_machine.py` | `_recovery_preserve_spec` 回落链扩容 + 早退/清空路径留痕 |
| `core/pm_engine/dispatch.py` | implement/repair run 成功即落 branch；repair 待合并标记；re-merge 成功路径调序 |
| `core/worktree_manager.py` | 新增按 spec 枚举候选分支的查询（与 `find_worktree_by_spec` 同源口径）；`cleanup_stale_worktrees` 删分支前置检查 |
| `fenixd.py` | 关闭期保护集构造扩容；sidecar 触发条件放宽 |

**行为**：daemon 重启恢复的保留命中率提升（覆盖「已实现未合并」窗口）；`branch` 字段在 spec 生命周期内更早可见（Dashboard 与 `bin/fenix_process.py` 展示会提前显示分支名，属预期变化）。

**兼容性**：`branch` 取值不变；既有 STATE 数据零迁移；无新增配置键（复用 `worktree.implement_branch_prefix`）。

**非目标**：不改变排水窗口时长与快速停机语义；不改变 repair 轮次上限与熔断阈值；不引入「长活 run 自适应延长排水」；不改动 `interrupt-recovery-preserve` 既有的「零提交分支走清空」兼容分支。
