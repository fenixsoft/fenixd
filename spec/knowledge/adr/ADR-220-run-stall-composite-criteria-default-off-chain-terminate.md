# ADR-220：run 停滞判停必须复合判据、缺省关闭、命中即终止整个重试链

date: 2026-10-04
status: accepted

## Context

agent run 会出现「provider 往返极慢或停滞但进程活着」的成本空耗形态。对这类 run 内停滞做自动判停时，绝对次数单一阈值不可用：慢 provider 下正常成功的 run 本身可含多次超过 60 秒的往返（实测同日健康串行 run stalls 达 11 次），按「达到 N 次即杀」会把止损变成浪费放大器——杀掉的是健康 run 并触发重跑；反过来阈值放宽又对真停滞失去判别力。

## Decision

run 内停滞判停只允许复合判据：判据一为 run 内连续 N 次（`agents.run_stall_budget_stalls`，缺省 5）达到 120 秒的 API 往返；判据二为完成样本不少于下限且 stall 占比达到一半、并超过 M 分钟（`agents.run_stall_budget_window_minutes`，缺省 10）无产物 mtime 进展；两判据任一命中即判停。整个预算缺省关闭（`agents.run_stall_budget_enabled` 缺省 false），灰度开启。判停读取旁挂既有流式循环 latency 采样点，不新增轮询通道；统计口径为 run 级累积，跨 attempt 与 in-place retry 重派不重置。命中判停必须终止整个重试链：不瞬态重试、不 in-place retry 重派、不触发 provider 链切换——止损命中后再自动重派即被放大，MUST NOT。

## Consequences

- 停滞空耗 run 在有界时间内被强杀收场（杀前 WIP checkpoint 保全），不再吃掉 30 分钟级墙钟与美元级沉没成本。
- 误杀残余风险仍在（慢而健康的 run 理论上可命中判据一），兜底为复合判据本身（健康往返清零连续计数、产物进展重置无进展窗）加缺省关闭灰度观察。
- 后续任何 run 级停滞判定（新车道、新 agent 类型）MUST 沿用复合判据口径，禁绝对次数单一阈值；新增强停机制 MUST 命中即终止重试链，禁只杀单 attempt 而放行自动重派。
