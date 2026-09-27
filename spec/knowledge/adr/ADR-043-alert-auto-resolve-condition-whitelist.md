# ADR-043：告警自动闭环——trigger 埋点 + condition 白名单，未识别永不自动闭环

date: 2026-09-06
status: accepted

## Context

升级告警产生后与底层 spec 状态完全脱钩：spec 恢复、验证通过、到达终态都不会回写告警，人工在待处理列表里考古已失效的条件。

## Decision

- 告警写入时埋结构化 trigger（type/spec/condition）；自动闭环判定为纯函数模块，挂在 pm_engine 既有周期扫描——不新增线程/定时器，判定复用当轮扫描已读的 STATE.md 结果，告警全闭环时跳过写回（mtime 不变）。
- 自动闭环标注 = `handled=True` + `handled_by: auto-resolve` + `handled_at` + `resolve_note`（依据）；闭环扫描跳过一切 `handled=True` 条目，人工记录不可覆盖。
- condition 枚举白名单制：仅 `spec_terminal_or_unblocked` 起步；后续新告警类型须显式扩展 condition 才获得自动闭环资格，未识别的 condition 永不自动闭环（保守默认）。
- 存量告警由 daemon 首启一次性推断回填（按 signal_type + spec 字段存在性），与常态闭环共用同一代码路径，resolve_note 注明「存量回填」。
- 写回复用 AdminStore 的原子写 + 锁，不绕过；闭环只改 handled 族字段且逐条幂等。

## Consequences

- 告警生命周期与 spec 状态闭环，视图按 handled 分组降噪（自动解决/人工处理徽标区分）。
- 保守白名单会留下少量永久待处理告警——视图归入待处理即暴露问题本身，可接受；新告警类型需手动接入 trigger，接入点集中于告警发送一处。
