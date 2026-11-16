# ADR-373：回落不再静默——派发冻结与版本前置检查挂共享 spawn 前置段

date: 2026-11-16
status: accepted

## Context

ADR-313 裁定无分配回落合法且 adapter 层「禁以预检错误拒绝 spawn」，可观测仅为一次性 WARN 留痕（仅留痕不拦派发）。2026-11-09 两波车道级秒挂暴露该裁定的盲区：回落形态（无 key 的默认路由）全天 ≥23 个 run 零产出死亡、7 次死人开关触发，WARN 留痕拦不住任何派发。同日第二缺口：dsh 版本白名单拦截只在 `_execute_agent` 前置段生效，spec-review/dispute-judge 直调车道不经该方法，同一版本漂移在不同车道两种命运（dispatch 族被拦、直调车道 spawn 后死于 bundle 插件不兼容）。已落地的 arbiter 车道预检（harden-arbiter-lane-resilience）对无显式链角色明文跳过，恰好放过了全部事故形态。

## Decision

1. 回落不再静默：探针角色（arbiter/repair）未分配显式链时按 harness 默认链做三值凭据可判定判定（ok / missing / indeterminable；本地无解析面或解析异常输出明确「不可判定」，禁静默跳过）；verdict 非 ok 的角色首个派发被拦截并维护按角色去重的单条告警。
2. ADR-313 的合法回落语义保留、不构成 supersede：拦截仅针对「注定死亡的回落」（默认链凭据缺失/不可判定），回落到可用链仍放行；配置补齐经 TTL 重探自然解冻，误判由显式放行键 `agents.allow_harness_default_fallback` 人工兜底。冻结是派发层关口，adapter 层「不以预检错误拒绝 spawn」契约不变。
3. 车道级前置闸挂点裁定：凡需覆盖全部 agent 车道（含 arbiter/repair/spec-review/dispute-judge 等不经 `_execute_agent` 的直调车道）的派发前检查，一律挂 `_run_agent` 共享 spawn 前置段，禁挂 `_execute_agent` 前置段（对直调车道不可达）。版本前置检查（复用 adapter check_health，不新写）同段全车道覆盖；结论按 adapter 级 TTL 缓存复用，禁逐 spawn 重复起 `dsh --version` 探测子进程。
4. 范围划界：冻结角色范围与探针角色集一致（其余角色与交互式 run 不受影响）；DNS 连通预检白名单（_DISPATCH_PROBE_LANES）对 dispatch 族的排除维持不变；秒挂冷却与秒挂计数语义不变（拦截发生在 spawn 前、不产生秒挂 run）。

## Consequences

直调车道的版本漂移失败形态从 spawn 秒挂变为预检拒绝——失败更早、更便宜（零进程零产物，日志与告警面先行）。「凭据可判定」依赖本地配置形态，极端形态可能误判：误判代价是拦截 + 单条告警，人工放行键可立即恢复，优于静默秒挂；冻结闸自身故障 fail-open 放行，不成为新单点故障源。后续新增车道级派发前检查必须沿共享 spawn 前置段挂点，不得在 `_execute_agent` 增设同类闸。
