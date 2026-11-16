# 派发预检全车道覆盖（回落冻结与版本白名单）

<!-- knowledge: capability=dispatch-preflight-coverage rev=1
     sources=spec/changes/evo-provider-fallback-dispatch-gate -->

车道派发前置检查的全车道一致性层：provider 预检探针覆盖回落角色、回落形态中注定死亡的派发在 spawn 前冻结拦截、dsh 版本白名单前置检查覆盖全部 agent 车道——同一环境缺陷在不同车道有一致的拦截命运，而非 spawn 后秒挂。

## 规则

- **回落角色凭据可判定探针**：provider 预检探针对「未分配显式 provider 链」的角色（回落 harness 默认配置形态）不静默跳过——按默认链的本地解析面做与显式链同构的凭据可判定检查（baseurl/apikey 非空判定，纯本地不发 API 请求），结论为三值 verdict：`ok`（凭据齐备，回落到可用链仍合法）、`missing`（路由可判定但凭据缺失）、`indeterminable`（本地无解析面：dsh 回落 spawn 不携带 `--patch`、凭据由 dsh 侧 profile 默认档承载；claude 环境无默认路由痕迹即 OAuth/CLI 默认档形态；或解析自身异常）。verdict 随探针结果 `fallback_verdicts` 字段输出（仅含回落形态角色），无法判定时输出明确「不可判定」结论而非跳过；显式链角色的既有探针行为不变。
- **回落首派发冻结**：探针角色（arbiter/repair——冻结角色范围与探针角色集一致，其余角色与交互式 run 不受影响）同时满足「未分配显式链（判定单源 `get_agent_model_assignment`）+ 默认链 verdict 非 ok」时，首个派发在共享 spawn 前置段被拦截：不 spawn、先于 runs 目录创建与产物落盘（零进程零产物，不产生秒挂 run），拒派文案带 `[provider-fallback-frozen]` 归因标记与修复指引，经 RuntimeError 走既有失败语义收口（0 rounds、不烧 API 配额）。拦截同时维护单条告警：signal_type `provider_fallback_frozen`、dedup_key 按角色去重（同一角色冻结周期只一条），后续命中 bump 既有条目 `hit_count` 而非新建；告警直写 AdminStore 不入处置链（防自环，同车道环境告警先例）。
- **解冻对称语义（三放行路径自动关闭在案告警）**：配置热重载使默认链凭据变为可用（TTL 重探 verdict=ok）、角色补配显式链、显式放行键 `agents.allow_harness_default_fallback` 打开（经 ConfigLoader 点号键读取、Python truthy 口径，误判场景人工兜底）任一成立即放行，并自动关闭该角色在案冻结告警（无在案条目零写回）。冻结状态进程内即可，无需持久化。
- **闸自身故障 fail-open**：冻结闸自身逻辑异常放行并 WARNING，不成为新单点故障源（探针体内部异常已由探针按 unhealthy 兜底）；探针结论经独立 TTL 缓存消费（缺省 300s，与 arbiter 前置闸同源口径），配置变更经 TTL 重探自然感知。
- **版本白名单全车道一致**：dsh 版本前置检查（复用 adapter `check_health`：版本白名单 + Bundle 挂载探测，不新写检查逻辑）挂 `_run_agent` 共享 spawn 前置段，覆盖全部经该段的车道——含 spec-review/dispute-judge 等不经 `_execute_agent` 的直调车道；同一版本漂移在所有车道一致拦截（拒派文案带 `[harness-health-gate]` 前缀），而非 spawn 后死于 bundle 插件不兼容。claude 通道无 `check_health` 成员零动作放行（duck-typing 同既有口径）。结论按 adapter 级 TTL 缓存复用（TTL 内多次 spawn 只起一次探测子进程，禁逐 spawn 起 `dsh --version` 子进程；子进程短超时同 `PROBE_HEALTH_TIMEOUT_S`；体内异常收口为结构化拒派文案）。
- **检查范围划界**：DNS 连通预检白名单（`_DISPATCH_PROBE_LANES`）对 dispatch 族的排除维持不变（独立机制，本能力不触碰）；arbiter 前置闸已覆盖项保持。秒挂冷却与秒挂计数语义不变——冻结拦截发生在 spawn 之前，不产生可计数的秒挂 run。

## 关键行为

回落角色派发到达 `_run_agent` → 冻结闸按角色消费探针 verdict（TTL 缓存）→ 非 ok 即拦截（拒派 + 单条告警计数）→ 默认链凭据补齐/显式链分配/放行键打开后放行并自动关闭告警。版本漂移时版本闸在 spawn 装配后、进程启动前拦截全部车道 → 预检拒绝替代 spawn 秒挂。

## 代码锚点

- 主实现：core/agent_runner/lane_preflight.py（probe_default_chain_credentials 三值判定、fallback_verdicts 输出、provider_fallback_frozen 告警生命周期）、core/agent_runner/runner.py（_provider_fallback_dispatch_gate 与 _shared_adapter_health_gate，均挂 _run_agent 共享 spawn 前置段）
- 配置单源：core/agent_runner/runner.py:PROVIDER_FALLBACK_ALLOW_KEY（agents.allow_harness_default_fallback 显式放行键）
- 守卫测试：tests/test_provider_fallback_dispatch_gate.py（回落首派发拦截+告警单条、显式链不误伤、非探针角色不受影响、热重载解冻、放行键旁路与在案告警关收、直调车道版本拦截、dispatch 族既有行为不变）

## 溯源

- 2026-11-16 evo-provider-fallback-dispatch-gate（spec/changes/evo-provider-fallback-dispatch-gate/） — 新建本能力：probe② 扩展回落角色三值凭据判定（不再静默跳过）、回落首派发冻结与按角色单条告警（修订 add-harness-default-key-fallback「仅留痕不拦派发」裁定）、显式放行键兜底、版本白名单前置检查挂共享 spawn 前置段覆盖直调车道（DNS 连通预检排除维持不变）
