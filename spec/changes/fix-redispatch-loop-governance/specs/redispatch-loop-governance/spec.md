# redispatch-loop-governance

## ADDED Requirements

### Requirement: 同因重派熔断

对同一 spec 的**同因**重派 MUST 有熔断：连续重派达阈值时冻结该 spec 转人工处置并发人工升级告警，MUST NOT 无限热派。

「同因」MUST 有机械判据（design 给出精确口径），至少覆盖：

- 连续多轮 run 以 `partial` 收工且**缺口集合不变**；
- 连续多轮判失败且**归因文案指纹相同**（归一化后的稳定串）。

熔断阈值 MUST 为可配置项（新增配置键 MUST 同步提供 Dashboard 设置界面——见项目约定「新增配置项必须带 Dashboard 界面」）。

#### Scenario: 同因重派达阈值即冻结

- **WHEN** 同一 spec 连续 N 轮以相同缺口集合（同因）被判重派
- **THEN** spec 被冻结（`frozen=True` + `status=blocked`）并发出人工升级告警，MUST NOT 再派发新一轮

#### Scenario: 不同因不误熔断

- **WHEN** 连续多轮 run 的缺口集合或归因指纹**各不相同**（每轮确有新进展）
- **THEN** MUST NOT 触发熔断，按既有重试通道继续

#### Scenario: 熔断可人工解除

- **WHEN** 人工处置后解冻
- **THEN** 同因计数清零，重试从零起算（对齐既有 `unfreeze_spec` 的计数清零语义）

### Requirement: 重派时成果继承

`partial` 收敛**不成立**（确有未申报缺口）、或收敛成立但卡在后续门导致需要重派时，重派 MUST 继承上一轮的 worktree 现场与分支成果，MUST NOT 从零重建（新 worktree、从 main 起）。

现行 `keep_for_reuse` 只在失败/取消路径触发；run 层报成功（`result.success=True`）时走 `cleanup(success=True)`，worktree 被清理、无遗产可复用——本变更 MUST 消除这一不对称。

#### Scenario: 同因重派不重建 worktree

- **WHEN** 某轮 run 收工后 spec 被判需要重派
- **THEN** 下一轮认领上一轮的 worktree 与分支（继承已提交成果与未提交现场），MUST NOT 新建 worktree

#### Scenario: 继承不影响成功路径清理

- **WHEN** run 成功且 spec 正常推进（不重派）
- **THEN** 既有 `cleanup(success=True)` 语义不变（worktree 清理、分支保留供 merge-back）

### Requirement: 与既有预算/豁免机制不冲突

同因重派熔断 MUST NOT 与既有实现预算（`_impl_run_budget_used` / `agents.impl_run_budget`）或死亡 run 豁免（`_exempt_dead_run_budget`）互相覆盖：三者语义正交，MUST 各自独立记账。

#### Scenario: 熔断不吞预算计数

- **WHEN** 同因重派触发熔断
- **THEN** 该 spec 的 `_impl_run_budget_used` 保持熔断前的真实值（MUST NOT 被重置或清零），熔断原因与预算状态在冻结 error 文案中均可读

#### Scenario: 死亡豁免不被误用

- **WHEN** 重派因同因熔断而中止
- **THEN** MUST NOT 走死亡 run 豁免路径（该路径语义为「run 无收工结果」，与同因重派无关）

### Requirement: 不使用绝对行号锚定

任务与交付物 MUST 以函数名 / 字段名 / 配置键锚定。

#### Scenario: 任务锚点为符号名

- **WHEN** 审阅 tasks.md
- **THEN** 每项任务以函数名或字段名定位
