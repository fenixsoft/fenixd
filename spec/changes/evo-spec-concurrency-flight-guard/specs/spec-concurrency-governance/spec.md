# Requirement: spec 并发 run 状态守卫

## Requirement 1: 审核收尾回退守卫

spec-review run 收口时（status 为 approved/repaired 需回退状态），系统 MUST 重读 spec 当前 status：若已为 implementing（存在在飞实现 run）或此后端状态，则 MUST NOT 回退到 ready，仅记录 in-flight 日志；幂等（当前 status 非 implementing 时零操作）。

### Scenario: 评审收尾不再回退在飞实现

- **GIVEN** spec 当前 status=implementing（implementer 已派发）
- **WHEN** 在飞 spec-review run 收尾（repaired）
- **THEN** status 保持 implementing，不触发 implementing→ready；记录「评审收尾遇在飞实现 run，跳过回退」INFO 日志

## Requirement 2: 派发前在飞评审校验

派发 implementer 前，系统 MUST 校验同 spec 无在飞 reviewer/repair run（存在 reviewing 状态或在飞 run 记录时顺延派发；在飞 run 收尾后重新判派）。

### Scenario: 在飞评审时派发顺延

- **GIVEN** spec 处于 ready 且存在在飞 spec-review run
- **WHEN** 调度器尝试派发 implementer
- **THEN** 派发被顺延（不创建实现 run），待 review 收尾后重判

## Requirement 3: 合并收尾 ready 态兜底

实现 run 合并完成后推进状态时，若 spec 当前 status=ready 且当前合并分支属已通过评审的实现 run 产物，系统 MUST 自动补记合法转移链（implementing→implemented）后推进 implemented；严禁以 ready→implemented 非法转移报错。

### Scenario: 兜底补记合法链

- **GIVEN** 实现 run 合并完成、spec 当前 status=ready（因竞态被回退过）
- **WHEN** 合并收尾推进 implemented
- **THEN** 系统自动执行 implementing→implemented（先补记 implementing 再推进），不产生 Invalid transition ERROR

## Requirement 4: 非实现合并不触发兜底

仅当合并确属实现 run 产物（携带通过评审证据/匹配 implementer_run 分支）时启用 ready 态兜底；纯文档/管理操作合并不触发。