# planner-generation-throttle — planner 阶段跨管线生成节流

## ADDED Requirements

### Requirement: 阶段级并发上限

配置键 `verify.planner_max_concurrent`（正整数 N）生效时，全框架同时处于「planner 出题中」的 run 数 MUST ≤ N（跨 verify 管线的阶段级信号量，超出者排队等待）；配置为 0 或缺省时 SHALL 不节流（现状：并发度仅受派发层 `agents.max_concurrent` 约束）。派发层全局并发语义 MUST 保持不变（本限制是管线内新增的第二道门，不改动 `parallelism-config`/`priority-parallel-scheduler` 既有要求）。

#### Scenario: 上限生效

- **WHEN** `verify.planner_max_concurrent: 1` 且两个 verify 管线同时进入阶段1
- **THEN** 同一时刻至多 1 个 planner run 在执行，另一个排队等待（持槽等待），先到者完成后后者开始

#### Scenario: 缺省不节流

- **WHEN** 配置缺省/为 0 且三个 verify 管线同时进入阶段1
- **THEN** 三个 planner 并发执行（与现状一致）

### Requirement: 设置页开关与注解

设置页「并发度」页签（ParallelSettingsPanel）SHALL 提供「planner 生成节流」开关（关闭为缺省）+ 上限数值输入；开关旁注解 SHALL 简要说明作用与代价，供用户知情选择。配置键与 UI 能力同步落地（不允许先 YAML 后界面）。注解须覆盖三点：①限制的是全框架同时在出题的 planner 数量；②作用=降低多 planner 同打 LLM 网关的长尾延迟概率；③代价=验证吞吐（排队 spec 等待更久）。

#### Scenario: 开关持久化

- **WHEN** 用户在并发度页签开启节流并设上限为 1，保存后刷新页面
- **THEN** 开关状态与数值回显一致，daemon 侧读到 `verify.planner_max_concurrent: 1` 并生效

#### Scenario: 注解可见

- **WHEN** 用户查看并发度页签的节流开关
- **THEN** 注解文本包含上述三点（作用/收益/代价），非纯裸开关

### Requirement: 节流等待不触发卡死误报

持槽等待信号量的 spec（verifier 已派发、planner 排队中）MUST NOT 被 recovery watch 判为 dispatch_stalled 或 stuck——其派发已发生、run 活跃，仅生成阶段在排队。等待期间 SHOULD 有可观测日志（如「planner 节流排队中: spec」）供时间轴审计。

#### Scenario: 排队不被误判

- **WHEN** `verify.planner_max_concurrent: 1` 且 spec B 的 planner 在信号量上等待超过 followup 窗口
- **THEN** spec B 不产生 dispatch_stalled 信号、不唤起 Administrator、状态不回退

#### Scenario: 排队可观测

- **WHEN** spec B 开始等待信号量
- **THEN** 日志记录排队事件（含 spec 名与当前占用者数量），时间轴可检索

### Requirement: 冻结复用与取消路径不受节流影响

场景冻结复用路径（跳过出题）MUST NOT 获取信号量（无 planner run 即无节流）；planner run 被人工取消时 MUST 释放信号量（不泄漏占位导致后续 spec 永久排队）。

#### Scenario: 冻结复用零节流

- **WHEN** spec 已有冻结场景集，重入验证直接复用跳过出题
- **THEN** 信号量未被获取，其他 spec 的 planner 并发度不受影响

#### Scenario: 取消释放信号量

- **WHEN** planner run 在持信号量执行中被人工取消
- **THEN** 信号量释放，排队的下一个 planner 正常开始
