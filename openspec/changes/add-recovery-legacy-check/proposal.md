# Proposal: add-recovery-legacy-check

## Why

run 死亡后的恢复重派总是从零开始：add-fail-counter-budget 首轮 run（约 65 分钟）死于网关瞬时故障后，恢复链路清理了 worktree、未提交工作全部沉没，新 run 在全新 worktree 重做——而断点续跑（resume）按设计仅限单次派发内的 attempt 重试，跨派发的遗产被直接丢弃（现场复盘确认的浪费点）。在网关瞬时故障高发的现状下，每次 run 死亡都是一次纯损失。

## What Changes

- run 死亡触发恢复重派时，死亡 run 的 worktree 与分支**保留为「遗产」**（不立即清理，带宽限期）
- 新 run 的任务书 prompt 注入「遗产检查」上下文：遗产 worktree 路径、分支名、脏文件清单（git status 快照）
- 新 run agent 拥有决策权：inspect 遗产后**自行决定**收编（把有价值的半成品复制/移植进自己的 worktree 并提交说明来源）或弃用（声明重做理由）；框架不担保遗产状态一致性，仅提供可见性
- 遗产 worktree 对新 run 为只读参考（不得在其内继续工作）；新 run 成功 merge 后遗产按既有清理路径回收；宽限期超时（默认跟随孤儿清扫周期）由 sweeper 兜底回收

## Capabilities

### New Capabilities
- `recovery-legacy-check`: run 死亡恢复重派时的遗产保留、上下文注入与 agent 自主收编决策

### Modified Capabilities

（无——恢复链路与清扫器的既有行为保持，仅增加保留与注入环节）
