## ADDED Requirements

### Requirement: 外部 testing 跃迁即时派发

watch 通道（秒级 checksum 轮询）检测到 SPEC 状态跃迁进入 `testing` 且该 SPEC 命中无驱动判定（spec_is_undriven）时，系统 MUST 立即触发 verifier 派发（复用 `_recover_testing` 等价的 re-trigger 逻辑），不得等待 30 分钟周期 full_scan 兜底。实现 MUST 复用既有恢复路径与判定语义，不新增 PMEngine 事件类型。

#### Scenario: dashboard 直写解冻后秒级派发
- **WHEN** dashboard 进程经告警裁决外写 STATE 使某 SPEC blocked → testing，且该 SPEC 无在飞验证/Administrator run
- **THEN** watch 通道在秒级轮询周期内触发 verifier 派发，实测延迟远小于 poll_interval_minutes

#### Scenario: 有驱动的 testing 不重复派发
- **WHEN** watch 通道观察到 testing 跃迁，但该 SPEC 已有在飞 Administrator run 或已有排队条目（无驱动判定不命中）
- **THEN** 不触发派发，状态维持原样，等待在飞 run 自然推进

### Requirement: 派发通道与兜底网共存

即时派发失败（如引擎瞬时不可用）时系统 MUST 保持在飞互斥与无驱动判定语义不被破坏，30 分钟周期 full_scan 的 `_recover_testing` 兜底重试 MUST 继续可用。即时通道 MUST NOT 绕过或破坏既有互斥检查（_has_active_admin_run_for_spec 等）。

#### Scenario: 即时派发失败由兜底网重试
- **WHEN** watch 通道触发派发时派发调用失败（引擎忙/瞬时异常）
- **THEN** 无状态损坏、无重复 run 残留，下一轮 30 分钟 full_scan 扫到无驱动 testing 态后成功补派发
