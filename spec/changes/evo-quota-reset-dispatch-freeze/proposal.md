# Proposal: quota-reset-dispatch-freeze

## Why

供应商配额耗尽（RATE_LIMIT 429，code 1310）的报文自带重置时间（2026-11-10 事件原文「限额将在 2026-11-10 10:43:04 重置」），但框架侧无任何解析：core/agent_runner/provider_circuit.py:86-96 的三种冷却（RATELIMIT 300s、switch 300s、4xx 熔断 1800s）全为固定时长，core/ 全域无重置时间读取。后果已量化：2026-11-09 13:34:06Z 至 11-10 02:03:20Z 的 12.5 小时配额窗口内，13 个派发 run 全部失败且全含 RATE_LIMIT，「≈300s 冷却到期→再试→再死」反复（admin-m3-audio 四连败间隔 21s/4m41s/2m11s）；48h 窗归档 148 run 中终态 error 56、含 RATE_LIMIT 18，其中 repair run 白烧 882.8s/86 轮、planner-plan 白烧 41 轮。arbiter infra-failed 分级保护了失败计数器与死人开关资格，但 run 预算无保护。

配额耗尽系反复形态（在途 SPEC 已记录 11-09 夜间另一场 glm-5.3 额度耗尽），重置时刻明明在报文里，是低成本高收益的止损缺口。范围说明：自省调度（last_run_date 推进）系既有防风暴设计且失败不前移 last_run_at、次日回顾已实际覆盖，不在本 SPEC 范围。

## What Changes

- **重置时间解析（core/agent_runner/provider_circuit.py）**：RATE_LIMIT 类失败解析报文内重置时间戳，provider 冷却到期时间取 max(既有固定冷却, 重置时刻)，冻结该 provider 派发至重置时刻。
- **派发闸门消费（core/agent_runner/runner.py、core/pm_engine/dispatch/queue.py）**：冻结期间命中该 provider 的派发廉价失败，不逐 run 刷失败告警，改为维护单条汇总告警（复用 infra breaker 通道并扩展其 link 维度——现状仅接驳 spec-review 链路）。
- **单测**：覆盖冻结生效至重置、冻结期派发廉价失败与告警单条化、重置早于固定冷却时按固定时长。

## Capabilities

### provider-quota-awareness

见 specs/provider-quota-awareness/spec.md。

## Impact

- core/agent_runner/provider_circuit.py 冷却计算新增重置时刻来源（不改变既有固定冷却语义，只取 max）。
- core/agent_runner/runner.py 与 core/pm_engine/dispatch/queue.py 派发前检查新增一个分支。
- infra breaker 通道扩展 link 维度，既有 spec-review 用法不受影响。