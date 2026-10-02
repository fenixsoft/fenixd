# 设计：add-codefix-commit-first-contract

## Context

- 搁浅机理（09-25 实证两批）：批 agent 的收尾习惯是「把定向 pytest 丢后台 → 等结果 → 汇总」，回合在等待中结束；fix-out 产物行已写 `fixed`，但 `git commit` 从未执行。编排按「分支无提交」拒合回（`no_effective_fix`），worktree 清理后未提交修改 stranded（`impl-code-review-fix-1790303558` 至今残留 20+ 文件），条目在后续批重做（双倍花费）。
- 现状拒合回判定在 `core/code_fix.py` 批收尾路径，「产物行无 fixed 或分支无提交 → 拒合回」。
- 分支上 commit 无副作用风险：批分支生命周期止于合回或丢弃，中间 commit 不影响主树。

## Goals / Non-Goals

**Goals:**
- 提示词契约改变 agent 行为（少发生）
- 编排机械兜底保证即使 agent 违约也不搁浅（发生了也兜住）

**Non-Goals:**
- 不改回归门本身（salvage 后回归失败走当时生效的重试语义）
- 不做 fix-out 产物行与 git diff 的逐条对账（超出必要；salvage 粒度是整批）
- 不清理历史 stranded worktree（`1790303558` 由人工处置，属运行时文件）

## Decisions

- **D1 双层防护**：提示词契约是软约束（成本最低、防患于先），机械 salvage 是硬保障（兜住违约）。只用提示词已被本仓多次实证不可靠（fast-track 产物契约族事故）；只用机械层则 agent 继续攒大批未提交改动，salvage 粒度过粗。两层都要。
- **D2 salvage 三元组判定顺序**：产物行 `fixed>0`（读 fix-out）→ 分支 tip 与建树点比较（已有逻辑）→ `git status --porcelain` 非空。顺序即成本排序；porcelain 检测在最后，只在怀疑搁浅时执行。
- **D3 commit message 约定 `orchestrator-salvage: batch <batch_no> run <run_id>`**：可追溯（审计/回滚定位），与 agent 正常 commit 显式区分。
- **D4 真零改动（产物声明 fixed 但 porcelain 为空）不空提交**：维持拒合回。理由：空提交会把「声明与事实不符」的批白洗成 resolved，正是零有效修复守卫要防的（该守卫的立 spec 动机即「全 skipped 批白洗」）。

## Risks / Trade-offs

- [salvage 把半成品改动合入并通过回归门] → salvage 后仍必须过回归门；未提交改动本就是 agent 的工作产物，回归是对其的裁决，语义上与 agent 自己 commit 等价
- [porcelain 检测把无关文件（如 worktree 内运行时产物）卷入 salvage commit] → 只 `git add` 已跟踪的修改与新增的源码路径不可行时，退而 `git add -A`（worktree 内本就只有批分支工作区）；若观察到 gitignored 噪音，收紧为 `git add -u` + 显式 untracked 源码路径——实现时以 worktree 实测为准，验收场景覆盖「salvage 后分支 diff 与工作区改动一致」
- [契约段与既有 prompt 段冲突]（如「验证通过才算修复」的旧表述）→ 落任务时同步排查 `agents/code-fix.md` 全文，删除/改写与「先 commit 再验证」矛盾的表述

## Migration Plan

合入即生效（无配置键）；对在飞链无影响（批收尾路径多一个前置检测）。回滚 = revert 收尾分支。
