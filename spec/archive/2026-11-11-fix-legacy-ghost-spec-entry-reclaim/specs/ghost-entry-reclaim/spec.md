## ADDED Requirements

### Requirement: 幽灵条目自动对账清退

系统 SHALL 在 daemon 启动回填期及 full_scan 周期对 STATE 中全部非终态条目（终态 `pushed` 豁免）执行幽灵指纹判定：仅当条目同时满足（1）`spec_has_content` 为 False、（2）git 全历史对 `spec/changes/<name>` 零提交、（3）注册距今不少于 30 分钟，系统 SHALL 将其判定为幽灵条目并执行结构性清退——从 STATE 原子移除该条目、逐条台账留痕（含三项指纹证据），并以单条聚合告警列出本轮全部清退条目。任一条件不满足的条目 SHALL NOT 被清退或改动。

#### Scenario: 孪生幽灵条目被清退
- **WHEN** STATE 中存在条目状态为 blocked 且 frozen、`spec/changes/<name>` 目录不存在、git 全历史对该路径零提交、注册已超 30 分钟（如 `fix-planner-scenario-entry-schema-selfcheck`）
- **THEN** 该条目从 STATE 移除，台账落 `ghost-entry-reclaimed` 留痕，聚合告警包含该条目与三项证据

#### Scenario: 有实质内容的条目不命中
- **WHEN** 条目的 `spec/changes/<name>/` 下存在 proposal.md 等任一实质内容文件（如 arbiter 最小成文物化产物）
- **THEN** 该条目不被清退，既有评审/晋升链路不受影响

#### Scenario: 有 git 历史的条目不命中
- **WHEN** 条目目录当前不存在但 git 全历史对 `spec/changes/<name>` 有提交（曾立项后目录被误删）
- **THEN** 该条目不被清退，维持既有链路处置

#### Scenario: 新注册条目豁免
- **WHEN** 条目注册距今不足 30 分钟且目录暂时缺失
- **THEN** 本轮不清退，留待后续轮次对账

### Requirement: 清退可配置且留痕可审计

系统 SHALL 提供配置开关（`gates.ghost_entry_reclaim`，默认开启）；关闭时对账入口 SHALL 直接跳过、零副作用。每轮清退 SHALL 先收集全部命中再批量执行；spec 名含非法路径成分的条目 SHALL 保守跳过并告警、SHALL NOT 清退。聚合告警 SHALL 幂等防重（同指纹未处理告警在场时不重复告警）。

#### Scenario: 开关关闭时零副作用
- **WHEN** `gates.ghost_entry_reclaim` 配置为 off，daemon 启动或 full_scan 到达
- **THEN** 不执行指纹判定与清退，STATE 无任何变更

#### Scenario: 幂等重放
- **WHEN** 对账第二轮到达，此前命中的幽灵条目已被移除
- **THEN** 零清退、零重复聚合告警，正常条目零影响
