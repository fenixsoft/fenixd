# specs/stray-escalation-clock-persistence/spec.md

## ADDED Requirements

### Requirement: 散件盘点时钟持久化

主树未跟踪散件盘点的注册表（first_seen、指纹、路径集合）SHALL 持久化到运行时状态区，daemon 重启后 SHALL 恢复计时而非清零重来。

#### Scenario: 重启后滞留计时连续

- **WHEN** 某散件集合 first_seen 后 daemon 重启
- **THEN** 重启后的盘点以恢复的 first_seen 计算 elapsed
- **AND** 滞留达到 24 小时即触发 maintree_untracked_stray_escalated 升级，不因中途重启而重新宽限

#### Scenario: 持久化损坏降级

- **WHEN** 持久化文件缺失或损坏
- **THEN** 盘点回退现行为（内存注册表、重新宽限）并留一条告警
- **AND** 主盘点流程不阻断

### Requirement: 同指纹去重跨重启

同一路径集合的散件信号 SHALL 按指纹跨重启去重：集合未变化的周期盘点复用既有告警，不产生重复新告警。

#### Scenario: 重启不重复告警

- **WHEN** 同一散件集合在重启前后被连续盘点且集合未变化
- **THEN** 不产生第二条新告警，仅既有信号留痕更新

### Requirement: 失效路径惰性清理

持久化注册表载入时 SHALL 对盘上已消失的路径做惰性清理，不把历史路径当作存活散件参与计时与升级。

#### Scenario: 已清理散件不复燃

- **WHEN** 注册表中的某散件路径已被处置删除或归档
- **THEN** 下一轮载入时该条目被清除
- **AND** 其指纹不再参与后续去重与升级

### Requirement: 滞留升级触发有效性

滞留升级（elapsed≥1440 分钟）与体积升级 SHALL 在持久化时钟下可实际触发，验证以合成旧时间戳的注册表驱动升级路径命中。

#### Scenario: 合成时钟命中升级

- **WHEN** 注册表被注入 first_seen 早于 24 小时的条目并触发盘点
- **THEN** maintree_untracked_stray_escalated 信号产生
- **AND** 其后的归档/忽略/删除裁决执行器可正常消费该信号
