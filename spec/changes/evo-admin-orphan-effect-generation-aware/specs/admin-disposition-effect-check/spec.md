# admin-disposition-effect-check 规格（delta）

## ADDED Requirements

### Requirement: 孤儿处置生效核查须代际感知
处置组终态后的生效核查 SHALL NOT 仅凭 spec 当前状态快照判定处置未生效；STATE frozen=True 判「未生效」分支内 SHALL 先核查处置组完成时刻（组内最新记录 created；处置记录无独立终态时间字段）之后是否存在指向该 spec 的合法推进轨迹成功行，任一命中即判「已生效、被新代际取代」。

- 轨迹证据源 SHALL 为状态推进留痕日志家族（fenixd.log 及轮转备份，尾部限量 + mtime 剪枝复用既有读面），匹配契约：`Transition:` 与 `Gate transition:` 两族成功行前缀均认；from→to 属合法迁移（VALID_TRANSITIONS / GATE_TRANSITIONS）；spec 名与本组 spec 精确锚定；行时间戳落在 [处置组完成时刻, now]；channel 不限（auto/manual/recovery）。非成功行（Cannot transition / Invalid transition / Idempotent / Frozen-stripped 等）SHALL NOT 构成轨迹。
- 判「被新代际取代」时：旧处置组 SHALL 转记为已消解终态留痕（附轨迹证据行引用，不带 escalate=true）并回链新代际条目，SHALL NOT 升级人工；旧组关联 SIGNAL 记录 SHALL mark_signal_handled 收口；新代际条目 SHALL 使用独立于旧组 signal_type 的类型键、以开立即终态/handled 的留痕形态落账（携带旧组引用与轨迹证据行），SHALL NOT 进入未处理人工告警面、SHALL NOT 触发人工升级或仲裁调查。
- 推进轨迹缺失或日志窗口不可用时 SHALL 维持现行 fail-closed 升级语义（行为零变化）。

### Requirement: 生效核查证据源
STATE 当前状态快照 SHALL NOT 作为生效核查的唯一证据源；处置组完成时间戳（组内最新记录 created）与状态推进留痕日志家族（含轮转备份）为代际判别的第一证据源。

#### Scenario: 处置生效后 spec 被新一轮验证再冻结
- **WHEN** 处置组终态后该 spec 出现处置组完成时刻之后的合法推进轨迹（如 `Gate transition: <spec> blocked → testing`（channel=recovery）复位、`Transition: <spec> testing → verified`（channel=auto）前移），且当前 STATE frozen=True
- **THEN** 判「已生效、被新代际取代」：旧组转记已消解、旧组关联信号 mark_signal_handled 收口、新代际条目开立并双向回链，不产生人工告警，不触发重复仲裁调查

#### Scenario: 处置确实未生效
- **WHEN** 处置组完成时刻之后无任何指向该 spec 的合法推进轨迹
- **THEN** 维持升级人工，行为与现状一致

#### Scenario: 日志轮转丢失、轨迹不可考
- **WHEN** 日志窗口不可用，或候选集内无该 spec 的轨迹成功行
- **THEN** 维持升级人工（fail-closed）

#### Scenario: 轨迹早于处置组完成时刻
- **WHEN** 候选行时间戳早于处置组完成锚点（如复位行在终态记录落账之前、锚后无前移的形态）
- **THEN** 不构成轨迹证据，维持 fail-closed 判定

#### Scenario: 非成功行不构成轨迹
- **WHEN** 日志候选行为 Cannot transition / Invalid transition / Idempotent / Frozen SPEC stripped 等非成功形态
- **THEN** 不计入轨迹，维持 fail-closed 判定

#### Scenario: 已消解组不回环
- **WHEN** 旧组已转记消解且旧组关联信号已收口后，孤儿扫描再次遍历该组
- **THEN** 扫描按关联信号未处理查询不再命中而跳过，不重复转记、不重复开立新代际条目（新代际条目类型键独立于旧组 sig_type）
