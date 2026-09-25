# code-fix-lane delta：先 commit 再验证契约与 salvage 兜底

## MODIFIED Requirements

### Requirement: 全量回归门与合回（零有效修复拒合回判定段）

原「零有效修复拒合回」判定前 MUST 先执行 salvage 检测（见 ADDED「收尾 salvage commit」）：

- **零有效修复拒合回**：批收尾判定时，若产物行无一条 `status == "fixed"`，或 worktree 分支相对建树点无任何提交**且 salvage 检测无可提交的未提交改动**时，MUST NOT 合回、MUST NOT 置任何条目 `resolved`（`merge_back` 对「分支已是 HEAD 祖先」返回成功，无此守卫会把全 `skipped` 的批白洗成 `resolved`）；拒合回收尾 MUST 清理 worktree 并把该批条目写入进度快照 `chain_skipped`（链内跳过，语义见 `code-fix-batch-selfheal`），进度以非终态文案记原因 `no_effective_fix`，链继续推进下一批。

#### Scenario: 零有效修复拒合回

- **WHEN** 某批产物行全部为 `status: skipped`（或 worktree 分支相对建树点无提交且无未提交改动），且回归 `passed`
- **THEN** 框架 MUST NOT 合回、MUST NOT 置任何条目 `resolved`，worktree 被清理，该批条目写入 `chain_skipped`，链继续推进下一批（MUST NOT 终止链）

## ADDED Requirements

### Requirement: 收尾 salvage commit

批收尾判定「分支相对建树点无提交」时，编排 MUST 先执行 salvage 三元组检测：产物行存在 `status == "fixed"` ∧ 分支无提交 ∧ worktree 存在未提交改动（`git status --porcelain` 非空）。三元组同时满足时 MUST 将未提交改动自动提交到批分支（message 前缀 `orchestrator-salvage:`，附批号与 run_id），随后按正常路径继续回归/合回裁决，MUST NOT 直接按 `no_effective_fix` 拒合回。salvage 事件 MUST 写进度 current 与 warning 日志留痕。三元组任一不满足（尤其真零改动）MUST 维持既有拒合回语义，MUST NOT 空提交凑数。

#### Scenario: 搁浅批被 salvage 后合回

- **WHEN** 批 agent 产物行 20 条 `fixed`、分支零提交、worktree 存在未提交修改
- **THEN** 编排 MUST 自动以 `orchestrator-salvage:` message 提交这些修改到批分支，回归通过后正常合回核销，进度与日志留有 salvage 痕迹

#### Scenario: 真零改动维持拒合回

- **WHEN** 批产物行存在 `fixed` 声明、分支零提交、但 worktree 无任何未提交改动（声明与事实不符）
- **THEN** MUST 维持 `no_effective_fix` 拒合回语义（条目入 `chain_skipped`、清理 worktree、链继续），MUST NOT 空提交

### Requirement: 先 commit 再验证提示词契约

`agents/code-fix.md` MUST 包含契约段：每修复一条立即 `git commit`（分支上 commit 廉价且可回退）；后台/定向验证 MUST NOT 作为 commit 的前置条件；回合结束前 worktree 工作区必须干净（全部改动已 commit）。该契约段为软约束，机械保障由「收尾 salvage commit」承担。

#### Scenario: 契约段落机械可查

- **WHEN** 审阅 `agents/code-fix.md`
- **THEN** 存在「先 commit 再验证」契约段，且包含「逐条修复即 commit」「验证不阻塞 commit」「收尾工作区干净」三个要点
