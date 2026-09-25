# 提案：add-codefix-commit-first-contract

## Why

「fixed=N 但 commits=0」整批搁浅已发生两批（09-25 实测：fixed=20 与 fixed=19 各一批，$14+ 编排与回归费用，且 ~39 个条目在后续批次双倍重做）。根因：批 agent 把定向验证丢给后台 pytest 后直接结束回合、**始终未 commit**，编排按「分支无提交」判 `no_effective_fix` 拒合回——worktree 里 20+ 个文件的真实修改被 stranded（实证：`impl-code-review-fix-1790303558` 残留未提交修改至今）。

## What Changes

- **MODIFIED** `code-fix-lane` 的「零有效修复拒合回」判定：拒合回前新增 salvage 分支
- **MODIFIED** `code-fix-batch-parallel` 的「汇总后一次验证一次提交」：单次提交契约与「先 commit 再验证」相斥，改为边修复边提交、收尾一次验证（评审修补：消除双 MUST 互斥）
- **ADDED** 提示词契约（`agents/code-fix.md`）：逐条修复即 commit；后台/定向验证不得作为 commit 前置条件；回合结束前 worktree 工作区必须干净（全部已 commit）
- **ADDED** 编排机械兜底：产物存在 `fixed` 行 ∧ 分支相对建树点无提交 ∧ worktree 存在未提交改动 → 自动以 `orchestrator-salvage` 前缀 message 提交到批分支，继续走既有回归/合回裁决；真零改动维持既有拒合回语义

## Capabilities

### New Capabilities

（无）

### Modified Capabilities

- `code-fix-lane`（活源：`spec/changes/add-code-fix-batch-failure-selfheal/specs/code-fix-lane/spec.md`）：「零有效修复拒合回」requirement 增加 salvage 前置分支与收尾 salvage 语义
- `code-fix-batch-parallel`（活源：`spec/changes/add-codefix-batch-parallel/specs/code-fix-batch-parallel/spec.md`）：「汇总后一次验证一次提交」requirement 改写为「边修复边提交、收尾一次验证」（原「MUST NOT 多次提交」「验证先行」与提示词契约互斥）

## Impact

- `agents/code-fix.md`：新增「先 commit 再验证」契约段
- `core/code_fix.py`：收尾判定分支（salvage 三元组检测 + 自动提交 + 留痕）
- 新增单测覆盖 salvage 触发/不触发两路
- 与 add-codefix-targeted-retry 正交：salvage 后回归失败时，走当时生效的重试语义（本 SPEC 不改回归门）
