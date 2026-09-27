## MODIFIED Requirements

### Requirement: 空闲判定语义

「空闲」MUST 定义为**同时**满足：`agent_runner` 无活跃 run（覆盖 planner / implementer / verifier / judge 全部 run 形态）、无在飞评审 run、**无在飞 impl-ocr 车道（`ocr_lane_busy()` 为假）**、admin 处置 worker 池无在途任务。任一来源非空即 MUST 判定为非空闲。判定 MUST 复用既有内部状态（如 `_active_runs`），MUST NOT 通过扫描外部进程列表反推。OCR 车道维度判定异常时 MUST 按非空闲处理（宁紧勿松，与既有维度策略一致）。

#### Scenario: 活跃 run 期间判定为非空闲

- **WHEN** 存在任一进行中的 agent run（含 planner 出题、verifier 验证）
- **THEN** 空闲判定为假，不计入连续空闲时长

#### Scenario: 在飞 OCR 车道判定为非空闲

- **WHEN** 无 agent run 活跃，但 `_ocr_lane_inflight` 存在在飞 impl-ocr 车道（车道线程运行中）
- **THEN** 空闲判定为假，不计入连续空闲时长，陈旧自愈不 touch restart_request

#### Scenario: OCR 车道在飞全程不被自愈重启

- **WHEN** daemon 代码已陈旧且其余维度均空闲，车道于 T0 启动并持续运行超过 idle_confirm_seconds（120s）
- **THEN** T0 至车道收尾（含 finally 清理）期间 restart_request 不被自愈写入，在飞车道 run 不被 SIGTERM 杀死

#### Scenario: 车道收尾后恢复空闲累计

- **WHEN** 车道完成并已从 `_ocr_lane_inflight` 清理，代码仍陈旧
- **THEN** 空闲判定为真，连续空闲时长自车道收尾起重新累计，达到阈值后按既有机制正常触发

#### Scenario: admin 处置在途判定为非空闲

- **WHEN** 无 agent run 活跃，但 admin 处置 worker 池有在途任务
- **THEN** 空闲判定为假，不计入连续空闲时长

#### Scenario: 双源皆空判定为空闲

- **WHEN** 无 agent run 活跃、无在飞评审 run、无在飞 OCR 车道且 admin 处置池无在途任务
- **THEN** 空闲判定为真，开始累计连续空闲时长
