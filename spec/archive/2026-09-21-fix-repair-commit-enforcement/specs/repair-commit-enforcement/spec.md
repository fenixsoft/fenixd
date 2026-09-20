# spec-repair-commit-enforcement

## ADDED Requirements

### Requirement: repair 成功以分支 git 事实为准
repair agent 报告 success 后，框架 MUST 在消费结果、进入 re-merge-back 之前，以分支的 git 事实复核 repair 是否真正完成。复核 MUST 至少包含三项：① 分支 tip 相对 repair 派发前已前进（存在至少一个新提交）；② 实现分支 worktree 内无未解决冲突（`git ls-files -u` 为空，且 git 认可无冲突标记残留）；③ 该 worktree 不处于未完成 merge 状态（无 `MERGE_HEAD`）。任一项不满足时，框架 MUST 判定 repair 未完成，MUST NOT 进入 re-merge-back，MUST 走 repair 链回退路径。

#### Scenario: 已解决但未提交的分支被判未完成
- **WHEN** repair agent 写 success 结果文件，但实现分支 tip 与派发前相同（无新提交）
- **THEN** 框架判定 repair 未完成，不执行 re-merge-back，走 fallback 全新重派，并把「repair 解决冲突后未提交」写入 merge 失败上下文

#### Scenario: 冲突未解决被判未完成
- **WHEN** repair agent 写 success 结果文件，但 worktree 内仍存在未合并条目（`git ls-files -u` 非空）
- **THEN** 框架判定 repair 未完成，不执行 re-merge-back，走 fallback 全新重派

#### Scenario: 残留未完成 merge 被判未完成
- **WHEN** repair agent 写 success 结果文件，但 worktree 仍处于未完成 merge（存在 `MERGE_HEAD`）
- **THEN** 框架判定 repair 未完成，不执行 re-merge-back，走 fallback 全新重派

#### Scenario: 真正提交的分支放行 re-merge-back
- **WHEN** repair agent 已把 main 合入分支、解决冲突并 commit，分支 tip 前进且无未合并条目、无 MERGE_HEAD
- **THEN** 框架判定 repair 成功，对该分支重新执行 merge-back

### Requirement: 回退上下文注入具体未完成事实
repair 因 git 事实复核未通过而回退时，框架 MUST 在注入下一轮重派的 merge 失败上下文中包含具体的未完成事实（如「分支无新提交」「存在未解决冲突」「存在未完成 merge」），MUST NOT 仅以笼统的 merge-back 失败原因重派。

#### Scenario: 未提交易被点明
- **WHEN** 因分支 tip 未前进而回退重派
- **THEN** 新 implementer 的失败上下文明确指出「repair 解决冲突后未提交 / 分支 tip 未前进」，而非仅「merge-back failed」

### Requirement: repair prompt 提交为强制终点
repair prompt MUST 把「解决冲突 → commit」定为在测试之前必须完成的强制终点，MUST NOT 允许 repair agent 在跑测试（尤其全量套件）之后才决定是否提交。prompt MUST 明确：测试无法在窗口内跑完时，仍 MUST 提交已解决的合并并如实标注验证边界。

#### Scenario: 提交先于测试
- **WHEN** 构建 repair prompt
- **THEN** 修复步骤顺序为「合并 → 解决冲突 → 提交」，测试步骤在其后，且明示提交为强制终点

#### Scenario: 测试超时仍提交
- **WHEN** repair agent 无法在窗口内跑完全量套件
- **THEN** prompt 要求其提交已解决的合并并在结论文本中标注未跑完的验证边界，而非因测试未完成而跳过提交

### Requirement: repair 测试范围收敛为定向回归
repair prompt MUST 把测试要求从「运行项目全量测试」收敛为「本次合并触及文件的定向回归 + 有界超时」，MUST NOT 要求 repair agent 以跑完项目全量套件作为提交前提。

#### Scenario: 定向回归替代全量套件
- **WHEN** 构建 repair prompt
- **THEN** prompt 要求运行与本次合并触及文件相关的定向测试并设定有界超时，不把全量套件作为提交前置条件

### Requirement: repair 开场清理残留 merge 现场
repair agent MUST 在开工第一步检测 worktree 是否残留上一轮未完成的 merge（存在 `MERGE_HEAD`），若存在则 MUST 先 abort 复位到当前分支干净 tip，再重新执行合入 main，MUST NOT 把上一轮遗留的半成品合并现场当作本轮起点。

#### Scenario: 残留 merge 先复位
- **WHEN** repair 开场检测到 worktree 存在 `MERGE_HEAD`（上一轮 repair 未提交即结束）
- **THEN** repair agent 先执行 merge abort 复位到干净 tip，再重新 `git merge main` 解决冲突

#### Scenario: 无残留 merge 正常开工
- **WHEN** repair 开场检测到无 `MERGE_HEAD`
- **THEN** repair agent 直接在当前分支 tip 上开始合入 main
