## ADDED Requirements

### Requirement: dsh 投影事件携带时间戳
DshEventProjector 投影产出的每条事件 MUST 携带到达时刻 timestamp，使既有延迟配对函数对 dsh 事件流产出非零样本。

#### Scenario: 投影事件带时间戳
- **WHEN** dsh 车道 run 产生事件并被投影
- **THEN** 每条投影事件含 timestamp 字段

#### Scenario: 延迟配对出样本
- **WHEN** 对含时间戳的 dsh 事件流执行 latency_samples_from_events
- **THEN** 产出与事件间隔一致的延迟样本（rounds>0）

### Requirement: 失明告警去重
延迟失明 WARNING MUST 按（harness,事件形态）去重、运行实例内一次性告警（生产每进程单 runner 实例拓扑下即进程内收敛），并如实描述根因（保留「失明」标记与 latency_rounds/turn_count extra 键测试锚点）。

#### Scenario: 不再逐 run 刷屏
- **WHEN** 同一（harness,事件形态）组合在同一运行实例内连续多 run 失明
- **THEN** 该实例内仅告警一次（生产单实例拓扑下即进程内仅一次）