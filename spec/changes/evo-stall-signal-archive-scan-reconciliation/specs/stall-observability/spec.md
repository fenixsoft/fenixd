# 能力规格：stall-observability（API 停滞信号观测）

## 概述

run 级与车道级 API 停滞信号的入账与触发规范：保证任何终态 run（无论是否已被保留清理归档）的停滞计量都能进入日累计与单轮升级判定，且累计面具备对账自证能力。

## ADDED Requirements

### Requirement: 扫描面含归档

停滞信号面的 run 档案扫描 MUST 覆盖 runs 目录顶层与 archive/：终态 run 被保留清理移入归档后，其停滞行仍 MUST 可被后续巡检轮入账；「终态落盘→归档」窗口窄于巡检节拍时 MUST NOT 造成信号漏报——含归档跨零点的日末终态 run，归档源的新鲜度过滤 MUST 与顶层同窗（沿用既有 48h 新鲜度界），MUST NOT 按 UTC 日桶对归档源额外收窄。归档源扫描量由既有新鲜度界与 runs 保留策略（归档副本非永久保留）共同约束。

#### Scenario: 归档件入账并触发预算信号
- **WHEN** 停滞 run 档案直接落入 archive/（顶层无文件）并触发巡检轮
- **THEN** 车道日累计入账，越过预算线时 lane_stall_daily_budget 信号落账

#### Scenario: 落盘即归档下一轮仍入账
- **WHEN** 终态 run 落盘后被保留清理立即移入 archive/、「终态→归档」窗口内无巡检轮
- **THEN** 下一巡检轮仍能从归档源入账并完成信号判定，不漏报

#### Scenario: 跨午夜归档不漏报
- **WHEN** 日末终态 run 的归档动作跨零点、其后巡检轮均属次日
- **THEN** 归档源仍按与顶层同款的新鲜度界评估该档案，单轮升级面可补报，不因 UTC 日桶过滤被排除

### Requirement: 对账自证

每巡检轮 MUST 将终态 run_metrics 停滞行合计（含当日 archive 内终态 run）与内存累计器对账：差额超过阈值（60 秒，即单条记账线）时 MUST 补发 lane_stall_daily_budget 信号留痕并注明对账来源。对账基准 MUST 与入账面同口径：success 终态行计入合计（入账面既有约定「success 豁免与否都要计」）、当日 mtime 过滤、latency_stall_total_seconds 缺键按 0。对账自证 MUST NOT 依赖对漏报根因的裁定，作为确定性兜底独立于扫描面修复生效。

#### Scenario: 差额超阈值补发
- **WHEN** 累计器与档案合计差额超 60 秒（如终态秒级归档漏计）
- **THEN** 补发 lane_stall_daily_budget 信号且 evidence 注明对账来源

#### Scenario: 基准同口径不制造假差额
- **WHEN** 当日存在停滞但 success 收场的 run（入账面计入、升级面豁免）
- **THEN** 对账基准同样计入其停滞行，差额为零，MUST NOT 因基准侧口径不齐而补发信号

### Requirement: 入账去重

同一 run 的同一停滞行 MUST NOT 因扫描面扩展或对账补发而重复入账；去重键沿用既有 run 级去重集合，跨扫描来源（顶层/归档/对账）保持一致；入账去重集的每轮收敛裁剪 MUST 以「顶层 ∪ archive」双源候选全集为收敛基。

#### Scenario: 三来源只入账一次
- **WHEN** 同一 run 档案先后经顶层扫描、归档扫描、对账补发三种来源触及
- **THEN** 其停滞行只入账一次，日累计不虚高

#### Scenario: 归档后收敛裁剪不双计
- **WHEN** run 在顶层已入账后被移入 archive/，入账去重集随轮收敛
- **THEN** 收敛基含归档候选，已入账条目不被裁掉重扫，同 run 不双计

### Requirement: 既有语义不变

停滞阈值（单轮记账 60 秒、升级 300 秒、车道日预算 30 分钟）、success 终态豁免（升级信号面）、UTC 日桶收拢、信号 kind 与 evidence 结构均 MUST 保持不变。

#### Scenario: 阈值与豁免无回归
- **WHEN** 既有停滞信号测试套件运行
- **THEN** 全部通过，阈值、success 豁免与日桶语义无行为变化
