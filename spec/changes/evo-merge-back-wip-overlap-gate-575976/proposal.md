# merge-back-wip-overlap-gate

## 背景与痛点

merge-back（实现分支合回主树）时，若主树存在与分支改动重叠的未提交 WIP，stash→merge→pop 的 pop 阶段必然冲突。现状（fix-mergeback-stashpop-silent-loss，已归档）只能做到：merge 前 autostash + WIP 重叠预检（仅产出告警文本）+ pop 冲突自愈（丢弃 stash 版、保留合并版）。被丢弃的 stash 版即使保留在栈中，人工也难以及时找回核对——09-09 修复后 5 天内同型事件复发 2 次（09-14 丢弃 SuggestedImprovementsPanel.tsx、09-15 00:09 丢弃 core/admin_store.py），后者丢弃内容恰含 AdminStore 序列化必要改动。

## 目标

merge-back 前主树 WIP 与分支改动重叠时，不再静默走「pop 冲突→自愈丢弃」：改为前置阻塞或自动收纳，从源头避免丢弃；仅在显式确认后继续。

## 非目标

- 不改变无重叠/主树干净的正常 merge-back 行为。
- 不替代 git stash 的人工找回流程（仅从源头减少丢弃发生）。