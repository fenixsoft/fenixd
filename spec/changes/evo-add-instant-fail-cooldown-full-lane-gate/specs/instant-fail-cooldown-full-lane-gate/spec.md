# instant-fail-cooldown-full-lane-gate Specification

## Purpose

秒挂冷却从「三车道白名单」扩展为按故障面门控（出题/验证/管理员 spec 作用域派发全部过闸），并给到期恢复加故障复诵与翻倍，使进程启动类基础设施故障的熔断在其故障面内真实生效、不再到期即重进故障循环。

## Requirements

### Requirement: 冷却门控覆盖出题与验证派发

planner-plan 与 verifier 的派发判定 MUST 在秒挂冷却生效期被跳过：命中时保留既有队列语义（不 pop、不耗预算、冷却到期后自动重入调度）；implementer/fast-track/repair 既有过闸行为 MUST NOT 变化。

#### Scenario: 冷却期内 planner 派发被跳过

- **WHEN** 某 spec 处于秒挂冷却窗口且有 planner-plan 派发请求
- **THEN** 该派发被跳过且留 INFO 级日志（spec 名、车道、剩余冷却秒数），队列条目保留待冷却到期后重判

#### Scenario: 冷却期内 verifier 派发被跳过

- **WHEN** 某 spec 处于秒挂冷却窗口且有 verifier 派发请求
- **THEN** 该派发被跳过并留 INFO 级留痕，验证链在冷却到期后恢复推进

#### Scenario: 门控面既有行为不回归

- **WHEN** 冷却生效且存在 implementer/fast-track/repair 派发请求
- **THEN** 行为与现网一致（跳过），且其通过/跳过路径的既有测试不回归

### Requirement: 管理员仅 spec 作用域纳管

管理员派发的秒挂门控 MUST 只作用于带 spec 归属的处置唤起，与既有 signal-kill 冷却检查同点位并列判定；daemon_errors 全局信号（spec=null）唤起 MUST NOT 被秒挂冷却拦截。

#### Scenario: spec 作用域处置唤起被门控

- **WHEN** 某 spec 处于秒挂冷却且产生该 spec 作用域的管理员处置唤起
- **THEN** 唤起被跳过并留 INFO 级留痕，冷却到期后按既有升级语义恢复

#### Scenario: 全局自救通道保持放行

- **WHEN** daemon_errors 全局信号（spec=null）在任一 spec 的冷却期内唤起管理员
- **THEN** 唤起照常执行，不被任何 spec 的秒挂冷却拦截

### Requirement: 到期复诵与冷却翻倍

冷却到期恢复 MUST 先做复诵判定：冷却窗内该 spec 仍有新秒挂记录（末次失败时刻晚于冷却起点）则不清零，改按翻倍时长续冷却（最多翻倍 3 次、单次冷却封顶 2400 秒）并重排恢复定时器；窗内零新失败才清零恢复。翻倍判定 MUST 在查询侧状态清除前完成消费。

#### Scenario: 到期即重派故障循环被抑制

- **WHEN** 冷却到期时刻前最后 300 秒内该 spec 仍有秒挂失败入账（如 2026-10-14 的 1791953098 形态）
- **THEN** 不恢复派发，冷却时长翻倍并重排定时器，留 INFO 级续冷却留痕

#### Scenario: 故障消失后正常恢复

- **WHEN** 冷却到期且窗内零新秒挂
- **THEN** 计数清零、恢复调度，行为与现网到期恢复一致

#### Scenario: 翻倍有上限

- **WHEN** 连续复诵翻倍达到 3 次或单次冷却已达 2400 秒
- **THEN** 不再递增，按封顶时长继续冷却并在到期后按复诵语义重判

### Requirement: 门控跳过留痕可观测

秒挂闸门的每次跳过 MUST 记 INFO 级日志（含 spec 名、被拦车道、剩余冷却秒数），不再只记 DEBUG。

#### Scenario: 门控生效可从日志核验

- **WHEN** 冷却期内任一车道派发被秒挂闸门拦截
- **THEN** 生产日志出现对应 INFO 留痕，无需靠行为反推