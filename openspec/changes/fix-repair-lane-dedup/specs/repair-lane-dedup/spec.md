# spec-repair-lane-dedup

## ADDED Requirements

### Requirement: reset 路径同根子 fix 存在时抑制重实现
spec_bug_found 的 reset 路径（recovery 重发导致）在目标为 fix spec 且已存在同根非终态子 fix 时，MUST 保持该 spec 的 bug-found 状态不重置为 ready、不派发其实现器；仅在 error 字段注明"修复由子 fix <名称> 承载"。无子或子均已终态时，既有 reset 行为不变。

#### Scenario: 有非终态子 fix 时重置被抑制
- **WHEN** fix spec X 处于 bug-found 且其同根子 fix（fix-fix-X）处于 ready
- **THEN** X 保持 bug-found，implementer 不派发，error 注明由子 fix 承载

#### Scenario: 子终态后解封
- **WHEN** fix-fix-X 到达 done/pushed 后 X 再次被 re-trigger
- **THEN** 守卫不生效，既有 reset/重派行为照常

### Requirement: spawn 路径在重实现在飞时跳过派生
judge 判定 bug-found 后派生子 fix 前，若被验对象本身是 fix spec 且其自身状态为 ready/implementing（重实现已在飞或已排队），MUST 跳过派生子 fix，并在被验对象的 error/evidence 注明"修复由在飞重实现承载"；无在飞重实现时派生行为不变。

#### Scenario: 重实现在飞时跳过派生
- **WHEN** fix spec X 验证判 bug-found 且 X 自身状态为 implementing（重实现在飞）
- **THEN** 不派生 fix-fix-X，X.error 注明由在飞重实现承载

#### Scenario: 非在飞时照常派生
- **WHEN** fix spec X 验证判 bug-found 且 X 处于 testing（验证态，无在飞重实现）
- **THEN** 照常派生子 fix

### Requirement: 派发级同根互斥
调度器派发 fix spec 实现器前 SHALL 检查同根兄弟是否存在 actionable 修复活动（兄弟 status 为 implementing，或 ready 且队列含其实现器条目，或存在活跃 impl/verify agent）；存在则保持本 spec ready 跳过本轮派发。仅 ready 且无队列条目不计为 actionable（防僵死 ready 永久阻塞）。

#### Scenario: 双 ready 历史现场不重复派发
- **WHEN** 同根两个 fix spec 均为 ready（历史双通道遗留现场），其一实现器已被派发
- **THEN** 另一个保持 ready 跳过派发，不产生并行实现

#### Scenario: 僵死 ready 不阻塞
- **WHEN** 同根兄弟 ready 但无队列条目、无活跃 agent
- **THEN** 不视为 actionable，本 spec 正常派发

### Requirement: 零行为差异回退保证
当被验/待派发对象为非 fix spec，或同根无任何非终态兄弟，或子 fix 均已终态时，三守卫 MUST 完全不生效，既有 reset/spawn/派发行为逐字段一致。

#### Scenario: 正常单链路径零差异
- **WHEN** 普通 spec（非 fix 前缀）走完 reset/spawn/派发全流程
- **THEN** 行为与守卫引入前逐字段一致
