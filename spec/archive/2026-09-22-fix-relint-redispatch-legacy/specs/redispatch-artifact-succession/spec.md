# redispatch-artifact-succession

## ADDED Requirements

### Requirement: 打回路径一致登记分支遗产

SPEC 因「run 层成功但 spec 层判失败」被打回重派时，实现成果 MUST 可被后继 run 继承。所有此类打回路径 MUST 一致地登记分支遗产（`worktree_manager.register_legacy`）。

适用路径（覆盖 status 回退到 `ready` 且分支含有效提交的打回）：

- 交付物守卫缺件打回（`_redispatch_for_missing`）——既有已实现；
- tasks.md 收口复检违规打回（`_redispatch_tasks_relint`）——**本变更补齐**；
- merge-back 失败回退、repair fallback——既有已实现或经 repair 车道保留现场。

不适用的路径 MUST 以显式理由说明（如零变更哨：分支零提交，无遗产可登记）。

#### Scenario: relint 打回后遗产可认领

- **WHEN** tasks.md 收口复检违规触发 `_redispatch_tasks_relint`，spec 回 `ready` 并重派
- **THEN** 该 run 的分支被 `register_legacy` 登记；下一轮 `worktree_manager.create` 经 `_take_reusable_worktree` 认领同一分支，继承首轮已提交成果

#### Scenario: 无分支时安全跳过

- **WHEN** 触发 relint 打回但 `result.branch` 为空或缺失
- **THEN** 跳过遗产登记，重派照常进行（fail-open），MUST NOT 抛异常阻断处置

### Requirement: 打回路径的一致性可验证

四条打回路径的遗产登记 MUST 有机械可验的一致性——存在测试或契约断言，使「新增一条打回路径时忘记登记遗产」可被检出（防同类缺口再次出现）。

#### Scenario: 一致性断言存在

- **WHEN** 审查打回相关测试
- **THEN** 存在断言覆盖「每条适用打回路径都调用了 `register_legacy`」，或覆盖「打回后 `_legacy` 在册可认领」

### Requirement: 不作为唯一继承手段

遗产登记 MUST NOT 是成果继承的唯一手段：`partial` 收敛不成立的重派形态由 `fix-redispatch-loop-governance` 的 worktree 保留覆盖；本变更只补齐**分支遗产**这一层。二者 MUST 语义正交、MUST NOT 互相覆盖。

#### Scenario: 与 worktree 保留正交

- **WHEN** 某轮 run 同时满足「需要 worktree 保留」与「relint 打回需登记分支遗产」
- **THEN** 两条机制各自生效且不冲突（worktree 现场由前者保留、分支线索由后者登记）

### Requirement: 不使用绝对行号锚定

任务与交付物 MUST 以函数名锚定。

#### Scenario: 任务锚点为符号名

- **WHEN** 审阅 tasks.md
- **THEN** 每项任务以函数名定位
