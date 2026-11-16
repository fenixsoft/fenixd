# Design: quota-reset-dispatch-freeze

## Context

现状：core/agent_runner/provider_circuit.py:86-96 三种冷却全为固定时长，429 报文中的重置时间戳（「限额将在 … 重置」）无人解析；派发消费闸门在 core/agent_runner/runner.py（约 :2473/:5144）与 core/pm_engine/dispatch/queue.py；infra breaker 通道（core/pm_engine/infra_breaker.py）明示仅 v1 接驳 spec-review 链路。2026-11-09~11-10 事件：12.5h 窗口 13/13 连灭。

## Goals / Non-Goals

- Goals：重置时刻驱动的 provider 冻结；冻结期派发廉价失败；告警单条化。
- Non-Goals：不改自省调度（last_run_date 防风暴设计保持）；不改既有固定冷却时长语义（只取 max）；不做多 provider 配额预测。

## Design

1. **解析（provider_circuit.py）**：RATE_LIMIT（code 1310 等）失败分支解析报文重置时间戳；解析成功→冷却到期 = max(现值, 重置时刻)；解析失败/无时间戳→维持现状固定冷却。冻结状态沿用既有 provider 冷却结构，不新增存储形态。
2. **闸门消费（runner.py、queue.py）**：派发前既有 provider 冷却检查处，命中冻结即廉价失败（返回明确原因，不计失败重试与预算计数），并经 infra breaker 通道维护单条汇总告警（扩展 breaker 的 link 维度以支持 provider 级条目）。
3. **告警生命周期**：汇总告警在冻结解除时走既有告警收口路径；重复命中只更新计数不新建。

## Risks / Trade-offs

- 重置时间戳格式变化：解析失败回退固定冷却，行为不劣于现状。
- 廉价失败与预算记账的边界：明确「拦截不计失败」，避免冻结期反而烧预算计数；单测覆盖。

## Migration

无数据迁移；解析即时生效于新失败事件。