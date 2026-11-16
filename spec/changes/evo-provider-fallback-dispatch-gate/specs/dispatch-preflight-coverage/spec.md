# dispatch-preflight-coverage Specification

## ADDED Requirements

### Requirement: 回落角色的凭据可判定探针

provider 预检探针 MUST 覆盖回落 harness 默认配置的角色（未分配显式 provider 链）：按默认链做凭据可判定性检查；无法判定时 MUST 输出明确探针结果，MUST NOT 静默跳过。

#### Scenario: 回落角色凭据缺失被探出

- **WHEN** repair 角色未分配显式链、将回落到无凭据的默认路由
- **THEN** 探针输出「回落链凭据不可用/不可判定」的明确结果，供派发闸消费

#### Scenario: 显式链角色探针行为不变

- **WHEN** 角色已分配显式 provider 链
- **THEN** 既有探针行为不变

### Requirement: 回落角色首派发冻结与单条告警

回落形态（角色未分配显式链且默认链凭据不可判定/缺失）的角色，其首个派发 MUST 被拦截并发出单条告警（含角色名与回落链信息）；MUST NOT 逐 run 重复告警；显式链角色 MUST NOT 被误伤。

#### Scenario: 回落角色首派发被拦截

- **WHEN** repair 角色回落默认链且默认链凭据缺失，首个派发请求到达
- **THEN** 派发被拦截（不产生秒挂 run），告警面出现一条含角色与回落链的告警；后续命中更新该告警计数而非新建

#### Scenario: 显式链角色正常派发

- **WHEN** 角色已分配显式链且凭据可用
- **THEN** 派发不受回落冻结影响

### Requirement: 版本白名单覆盖直调车道

dsh 版本白名单拦截 MUST 覆盖全部 agent 车道，包括 spec-review/dispute-judge 直调车道（连通预检白名单不再排除 dispatch 族）；同一版本漂移在不同车道 MUST 有一致的拦截行为。

#### Scenario: 直调车道版本漂移被拦截

- **WHEN** dsh 版本超出兼容白名单，spec-review 车道发起派发
- **THEN** 派发被版本前置检查拦截（与 dispatch 族车道行为一致），而非 spawn 后死于插件不兼容