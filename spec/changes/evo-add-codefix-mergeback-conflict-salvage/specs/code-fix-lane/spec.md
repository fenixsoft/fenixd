# code-fix-lane 规格（合回冲突定向救回）

## ADDED Requirements

### Requirement: 合回冲突定向救回
合回预演出真冲突时，系统 SHALL 在整批现场即弃前先执行一次定向救回：将批分支 rebase 到当前基线分支并重跑批回归；救回至多尝试 1 次。

#### Scenario: rebase 后回归通过
- **WHEN** 批分支 rebase 到当前基线成功且批回归通过
- **THEN** 重走合回流程，链正常出 resolved 终态，不整批入失败档案

#### Scenario: rebase 失败或回归仍不过
- **WHEN** rebase 仍冲突或重跑回归未通过
- **THEN** 进入 commit 组粒度回收，不再重试救回

### Requirement: 冲突组粒度回收
救回失败时系统 SHALL 按 commit 粒度 cherry-pick 回收非冲突提交，仅仍冲突提交对应的台账条目入失败档案并计 fail_count。

#### Scenario: 非冲突组回收成功
- **WHEN** 批分支存在与冲突文件无关的提交（如实测 14 提交中 13 个未触碰冲突文件）
- **THEN** 这些提交被 cherry-pick 回收，对应条目按 resolved 出账

#### Scenario: 仍冲突组入档案
- **WHEN** 某提交 cherry-pick 仍冲突
- **THEN** 其对应条目入失败档案计 fail_count，走既有预算重试

### Requirement: 救回时序与留痕
系统 SHALL 保证救回发生在分支清理之前（分支引用全程可用），并 SHALL 对救回各阶段（rebase/二次回归/cherry-pick/最终结局）留日志。

#### Scenario: 救回在清理前执行
- **WHEN** 合回真冲突触发救回
- **THEN** 批分支引用在救回全程存在，_safe_cleanup 在救回终局后才执行

#### Scenario: 救回全程留痕
- **WHEN** 救回执行（无论成败）
- **THEN** 各阶段有 INFO/WARNING 日志，最终结局（整批救回/部分回收/兜底全弃）单行汇总

### Requirement: defer 路径不受影响
wip_gate_blocked（主树未提交 WIP 预检阻断）SHALL 继续走 defer 零预算路径，不触发救回。

#### Scenario: WIP 预检阻断
- **WHEN** 合回前预检因主树未提交 WIP 阻断
- **THEN** 仍走 defer 零预算路径，不消耗救回次数与 fail_count 预算