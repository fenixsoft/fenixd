# lifecycle-hygiene

## ADDED Requirements

### Requirement: verifier 内部重试链尊重冻结

verifier/判定阶段内部的 failover 重试链（judge attempt 换网关重派、场景执行内部重试）在每次重试启动前 MUST 检查所属 spec 的结构化 `frozen` 字段：为真时 MUST 立即终止该链路（不再派发 attempt、不换 provider），run 以失败收场并保留既有错误记录。

#### Scenario: 冻结后 judge 重试链终止

- **WHEN** 某 spec 处于 frozen 冻结态，其 verifier 阶段内部 judge attempt 1 被外部终止
- **THEN** 框架不派发 attempt 2/3（与 2026-09-02 实证的旧行为相反），链路以 attempt 1 失败收场

#### Scenario: 未冻结链路行为不变

- **WHEN** spec 未被冻结，judge attempt 1 失败
- **THEN** 既有 failover 重试（换网关等）语义完全不变

### Requirement: STATE 路径唯一化

`.fenix/STATE.md` 历史遗留空文件 MUST 被删除；框架内所有 STATE 读写 MUST 且 MUST 只指向项目根 `STATE.md`。路径解析不得依赖相对路径歧义（调用方显式传项目根路径或框架单源常量）。

#### Scenario: 空文件删除后读写唯一

- **WHEN** `.fenix/STATE.md` 不存在，StateMachine 以项目根 `STATE.md` 初始化并执行 update_spec
- **THEN** 写入落在项目根 `STATE.md`，`.fenix/` 下不再生成新的 STATE.md；既有自动化（重启恢复、admin 巡检）读到的状态一致

### Requirement: 预算对账偏差自动校正

daemon 完成一次 run 收尾对账时，若 `used` 与 runs 目录正常收工 run 数存在偏差，MUST 以 runs 实际计数为准自动校正 `used`（校正动作留 INFO 日志，含校正前后值与原因），MUST NOT 保留静默漂移的旧值。偏差判定与校正 MUST 复用既有对账口径（runs 产物保留上限、链耗尽 run 不落产物的既有豁免语义不变）。

#### Scenario: 偏差自动校正

- **WHEN** 对账发现某 spec `used=4` 而 runs 目录正常收工 run 数为 2（无保留上限/豁免因素）
- **THEN** `used` 被改写为 2，日志记录「校正 4→2」；后续预算闸门按 2 生效

#### Scenario: 豁免口径不受影响

- **WHEN** 偏差源于 runs 产物保留上限或死亡 run 豁免等既有豁免语义
- **THEN** 不触发校正（沿用既有 WARN 对账日志），预算计数保持豁免后的值
