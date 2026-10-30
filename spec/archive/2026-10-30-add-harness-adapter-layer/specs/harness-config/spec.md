## ADDED Requirements

### Requirement: agent.harness 全局配置

config MUST 支持 `agent.harness` 键，合法值 `claude|dsh`，缺省 `claude`。非法值 MUST 回退 `claude` 并产生告警日志。项目级与用户级双层深合并语义与既有配置键一致。

#### Scenario: 缺省行为

- **WHEN** config.yaml 不含 `agent.harness` 键
- **THEN** 解析结果为 `claude`，所有车道经 claude adapter 派发，行为与现状一致

#### Scenario: 非法值回退并告警

- **WHEN** `agent.harness` 配置为 `codex`（未支持值）
- **THEN** 解析回退 `claude` 且日志出现含「不支持」字样的告警，daemon 不中断

### Requirement: dsh 值 fail-fast（本阶段）

在本 SPEC 交付后、add-dsh-adapter-integration 交付前，`agent.harness: dsh` MUST 被 dispatch 前置健康检查拦截并给出明确错误（「dsh adapter 未部署」），MUST NOT 静默回退 claude。

#### Scenario: dsh 值被健康检查拦截

- **WHEN** `agent.harness: dsh` 且 dsh_adapter 未注册，触发任一车道 dispatch
- **THEN** dispatch 以明确错误失败，错误信息含「dsh adapter 未部署」，无任何 run 被以 claude 通道代跑

### Requirement: Dashboard 设置界面同步

Dashboard 设置页 MUST 提供 `agent.harness` 的查看与修改（系统级面板），保存走 settings_routes 并受同一校验约束；热重载后新值对下次 dispatch 生效，在飞 run 不受影响。

#### Scenario: 设置页修改与热重载

- **WHEN** 在 Dashboard 设置页将 harness 从 claude 改为 dsh 并保存（dsh adapter 未部署阶段）
- **THEN** 保存请求被校验拦截并返回明确错误；配置值不变

#### Scenario: 新配置带界面（既定规则）

- **WHEN** 检查 config.template.yaml 与 Dashboard 设置页
- **THEN** `agent.harness` 键在模板中有注释说明且设置页存在对应控件，两处能力同步存在
