# code-fix-lane delta：先 commit 再验证契约与 salvage 兜底

本变更改写 `code-fix-lane` 能力「全量回归门与合回」requirement 的「零有效修复拒合回」
分支（活源：`spec/changes/add-code-fix-batch-failure-selfheal/specs/code-fix-lane/spec.md`）：
拒合回判定前新增 salvage 检测前置分支；其余 bullet（回归原语、worktree 执行、套件锁、
门面透传、快照归属、merge-back 闸门、核销口径）语义逐字不变。

## MODIFIED Requirements

### Requirement: 全量回归门与合回

每批修复 SHALL 经全量回归通过后才合回主树，MUST NOT 在回归未通过时合回。

- 回归 MUST 复用 `core.regression.run_regression` 执行原语与项目 `verify.yaml` 的 `regression` 段契约。
- 回归 MUST 在**该批的 worktree 内**执行（针对该批修复后的代码）：执行根 = worktree，故 `run_regression` 的 `project_root` 参数取 worktree 路径。
- 回归执行 MUST 与主树共用同一把主机级套件锁：调用 MUST 显式传 `lock_root=<主树根>`，使锁文件为 `<主树根>/.fenix/full-suite.lock`，保证同一主机同一时刻只跑一套全量测试。
- 门面 `core/agent_runner/maintenance_runs.run_regression` SHALL 同时接受可选 `project_root`（缺省回落 `runner.project_root`）与 `lock_root`（缺省 `None`），二者透传至 `core.regression.run_and_write_regression` → `core.regression.run_regression`；既有调用点不传时语义逐字不变。
- worktree 内回归的快照随执行根落盘于 worktree（门禁用途），MUST NOT 被当作主树「测试回归」分面的数据源。
- 回归 `status == "passed"` 时 MUST 经 `worktree_manager.merge_back(wt)` 合回主树，MUST NOT 绕过既有 merge-back 闸门（merge-tree 预演 / WIP 重叠 / spec 目录在飞）。
- 合回成功后 MUST 把该批中**产物行 `status == "fixed"`** 的条目按 `item_id` 精确置 `resolved`，MUST NOT 置未参与该批的条目，MUST NOT 置被 agent 判为 `skipped` 的条目。
- **零有效修复拒合回**：批收尾判定时，若产物行无一条 `status == "fixed"`，或 worktree 分支相对建树点无任何提交**且 salvage 检测无可提交的未提交改动**（salvage 检测见 ADDED「收尾 salvage commit」）时，MUST NOT 合回、MUST NOT 置任何条目 `resolved`（`merge_back` 对「分支已是 HEAD 祖先」返回成功，无此守卫会把全 `skipped` 的批白洗成 `resolved`）；拒合回收尾 MUST 清理 worktree 并把该批条目写入进度快照 `chain_skipped`（链内跳过，语义见 `code-fix-batch-selfheal`），进度以非终态文案记原因 `no_effective_fix`，链继续推进下一批（零产物批按 halt 终止链会使最早队列头永久堵塞车道，违背批失败不堵塞的自愈目标）。

#### Scenario: 回归通过则合回并核销

- **WHEN** 第 1 批修复完成，产物行含 `status: fixed` 的条目，worktree 内全量回归 `status=passed`
- **THEN** 框架 MUST 把该批分支 merge-back 主树，并把该批 `fixed` 条目置 `resolved`（`skipped` 条目 MUST 保持 `open`），进度 `done` MUST 按实际置 `resolved` 的条数增加

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
