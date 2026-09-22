# merge-back-wip-overlap-gate

## 背景与痛点

merge-back（实现分支合回主树）时，若主树存在与分支改动重叠的未提交 WIP，stash→merge→pop 的 pop 阶段必然冲突。现状（fix-mergeback-stashpop-silent-loss，已归档）只能做到：merge 前 autostash + WIP 重叠预检（仅产出告警文本，`core/worktree_manager.py:2208-2260`「warning only, merge proceeds」）+ pop 冲突自愈（丢弃 stash 版、保留合并版，`core/worktree_manager.py:1577+`）。被丢弃的 stash 版即使保留在栈中，人工也难以及时找回核对——09-09 修复后 5 天内同型事件复发 2 次（实证 `.fenix/admin_alerts.json`：09-14T12:22 丢弃 SuggestedImprovementsPanel.tsx、09-15T00:09 丢弃 core/admin_store.py，后者丢弃内容恰含 AdminStore 序列化必要改动）。另一类后果是 merge 被主树 WIP 拒绝，合并被阻塞待人工清理。

## 目标

merge-back 前主树 WIP 与分支改动重叠时，不再静默走「pop 冲突→自愈丢弃」：**默认自动收纳**（重叠改动随 autostash 卷走、合并后恢复，pop 冲突时保留条目并逐文件给出找回指引），**阻塞策略仅在显式配置时启用**（阻塞并告警，等待人工清理主树 WIP 后放行）。两类冲突（merge 拒绝、pop 丢弃）均从源头收口。

## 作用域与默认值

- 闸门判定的重叠集合 MUST 排除 `spec/changes/**`：该前缀被 `ensure_clean_tree` 的 autostash 显式排除（`core/worktree_manager.py:1559`），却在主树长期脏（实测当前 34 个脏 tracked `spec/changes/**` 文件）——纳入闸门会分别导致「收纳无效」与「几乎每次 merge-back 阻塞」。该前缀沿用既有提交通道收口。
- 默认策略 = 自动收纳，阻塞仅显式配置启用（重叠 ≠ 冲突，block 为默认属净回归）。
- 阻塞 MUST NOT 计入既有 merge 熔断记账（阈值 2 → 自动冻结 `blocked`，比现状更差）。

## 非目标

- 不改变无重叠/主树干净的正常 merge-back 行为（无重叠时沿用现行 autostash→merge→pop）。
- 不替代 git stash 的人工找回流程（仅从源头减少丢弃发生）。
- 不为 `spec/changes/**` 引入新的 stash/阻塞语义（沿用既有提交通道）。
- 同源草案 `spec/changes/evo-merge-back-wip-overlap-gate/`（capability `worktree`，created 2026-09-16）与本目录为**同一需求的两份草案且默认策略互相矛盾**：实现前 MUST 先收敛为一份（以本文件的默认策略与作用域约束为基准），避免主树出现两套语义不同的 merge-back 闸门。
