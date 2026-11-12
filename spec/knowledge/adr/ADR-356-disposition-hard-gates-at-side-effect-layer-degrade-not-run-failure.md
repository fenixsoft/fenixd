# ADR-356：处置硬门接线于副作用层入口前置，降级是处置结论而非执行故障

date: 2026-11-12
status: accepted

## Context

黑名单扫描→证明器→证据类校验三级硬门需要选定接线层。候选：处置副作用层（`core/pm_engine/arbiter.py` `_apply_disposition_side_effects` 入口前置）vs run 层（`core/agent_runner/maintenance_runs.py` run_arbiter）。run 层硬门会把门失败折算为 run 失败——烧掉同签名重试配额，且把「处置不获准」误标为「执行故障」，语义错误。

## Decision

三级硬门接线在 `_apply_disposition_side_effects` 入口前置，任一级失败复用既有 `_on_escalate` 降级路径（报告原样转裁决包+台账留痕命中原因），run 记合法终态。降级是处置结论而非执行故障：不折算 run 失败、不触发同签名失败重试计数、不烧配额。报告契约新字段（rescue_evidence/scenario_fixes）不做 run 级硬校验（旧形态报告兼容不炸），由硬门在处置侧消费。

## Consequences

后续新增处置门（黑名单扩项、新证据类型、新证明器）一律在副作用层入口接线并沿用降级语义，禁止在 run 层拦截；run 契约保持向后兼容薄面，防御力集中于处置门。降级不烧配额意味着弱处置主张可以反复被门拒绝而由防抖机制（签名指纹）约束重试，处置门与调度配额解耦。
