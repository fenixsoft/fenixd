# spec-dispatch-queue-aging

## ADDED Requirements

### Requirement: 队列条目按等待时长老化
pm_engine `_run_queue` 的每个条目 SHALL 记录入队时间戳；`_process_queue` 与 `_on_spec_ready` 式比较路径 MUST 使用 `effective_priority = base + min(floor_levels, max(0, floor((elapsed - initial_wait) / step_down)))` 参与优先级判定（数值越大越低）。配置键 `pm.dispatch.aging.enabled/initial_wait_minutes/step_down_minutes/floor_levels`，默认 enabled=false 保持向后兼容。

#### Scenario: P6 条目获得窗口
- **WHEN** 活跃任务持续为 P4/P5，一个 base=P6 的队列条目已等待超过 initial_wait + step_down×1，aging 开启
- **THEN** 其 effective 降一级参与比较并在下个调度tick可获得派发机会

#### Scenario: 未达阈值行为完全不变
- **WHEN** 条目等待时间小于 initial_wait
- **THEN** effective==base，判定结果与现状一致

### Requirement: 老化边界约束
活动运行中的任务 MUST NOT 参与老化降级；单条目等效降级总量以 floor_levels 为上限；daemon 重启后重建的队列从零计时。同级条目间相对顺序 MUST 保持稳定（先入队先派发）不被老化扰动。

#### Scenario: 持久运行的 P4 不会被降级
- **WHEN** 某 implementer 已活跃运行 3 小时
- **THEN** 其在 _active_priorities 中仍为原值，不影响 min_active 判定语义

#### Scenario: 同级顺序稳定
- **WHEN** 两个同为 P6 且等效值相同的条目存在先后入队关系
- **THEN** 派发顺序遵循入队先后
