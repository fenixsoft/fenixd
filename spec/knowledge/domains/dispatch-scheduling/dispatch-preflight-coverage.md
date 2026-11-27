# 派发预检全车道覆盖（回落冻结与版本白名单）

<!-- knowledge: capability=dispatch-preflight-coverage rev=2
     sources=spec/changes/evo-provider-fallback-dispatch-gate,spec/changes/evo-repair-lane-credential-probe-fix,spec/changes/evo-lane-probe-steady-noise-governance -->

车道派发前置检查的全车道一致性层：provider 预检探针覆盖回落角色（本地嗅探不可判定时降级试呼取证）、回落形态中注定死亡的派发在 spawn 前冻结拦截、探针观测面按稳态边沿降噪、dsh 版本白名单前置检查覆盖全部 agent 车道——同一环境缺陷在不同车道有一致的拦截命运，而非 spawn 后秒挂。

## 规则

- **回落角色凭据可判定探针**：provider 预检探针对「未分配显式 provider 链」的角色（回落 harness 默认配置形态）不静默跳过——按默认链做与显式链同构的凭据可判定检查，结论为三值 verdict：`ok`（凭据齐备，回落到可用链仍合法）、`missing`（路由可判定但凭据缺失）、`indeterminable`（本地无解析面：dsh 回落 spawn 不携带 `--patch`、凭据由 dsh 侧 profile 默认档承载；claude 环境无默认路由痕迹即 OAuth/CLI 默认档形态；或解析自身异常）。verdict 随探针结果 `fallback_verdicts` 字段输出（仅含回落形态角色），无法判定时输出明确「不可判定」结论而非跳过；显式链角色的探针仍为纯本地解析，不发 API 请求。
- **默认链凭据降级试呼**：env 三键（base URL / auth token / api key）嗅探全空的 indeterminable 形态下，探针按 TTL 缓存（30 分钟，进程级共享单例——回落冻结闸 300s 重探、daemon 60s 周期 tick、启动自检三类消费方共享，全进程每 30 分钟至多一次）降级执行一次 CLI 短请求试呼取证：成功判 ok、失败/超时/异常判 unhealthy 且 evidence 附试呼错误尾部；试呼带短超时（`PROBE_HEALTH_TIMEOUT_S` 口径），MUST NOT 无界阻塞回落冻结闸派发入口；缓存命中期内不重复试呼（探针自身不烧钱、不触发限流）。试呼裁决翻转按探针结论变化（新边沿）处理。
- **回落链凭据供给通道**：repair/arbiter 回落链凭据不可判定的止血走既有 systemd.env 承载机制——向项目 `.fenix/systemd.env` 追加 ANTHROPIC_* 凭据键（denylist 不拦 ANTHROPIC_*，对齐工作车道 provider 链），daemon 重启后进程环境出现该类键、探针转 healthy 并自动关闭在案告警；systemd 单元 EnvironmentFile 引用不在位的部署注入不生效，探针维持 unhealthy 话术提示。
- **回落首派发冻结**：探针角色（arbiter/repair——冻结角色范围与探针角色集一致，其余角色与交互式 run 不受影响）同时满足「未分配显式链（判定单源 `get_agent_model_assignment`）+ 默认链 verdict 非 ok」时，首个派发在共享 spawn 前置段被拦截：不 spawn、先于 runs 目录创建与产物落盘（零进程零产物，不产生秒挂 run），拒派文案带 `[provider-fallback-frozen]` 归因标记与修复指引，经 RuntimeError 走既有失败语义收口（0 rounds、不烧 API 配额）。拦截同时维护单条告警：signal_type `provider_fallback_frozen`、dedup_key 按角色去重（同一角色冻结周期只一条），后续命中 bump 既有条目 `hit_count` 而非新建；告警直写 AdminStore 不入处置链（防自环，同车道环境告警先例）。
- **解冻对称语义（三放行路径自动关闭在案告警）**：配置热重载使默认链凭据变为可用（TTL 重探 verdict=ok）、角色补配显式链、显式放行键 `agents.allow_harness_default_fallback` 打开（经 ConfigLoader 点号键读取、Python truthy 口径，误判场景人工兜底）任一成立即放行，并自动关闭该角色在案冻结告警（无在案条目零写回）。冻结状态进程内即可，无需持久化。
- **闸自身故障 fail-open**：冻结闸自身逻辑异常放行并 WARNING，不成为新单点故障源（探针体内部异常已由探针按 unhealthy 兜底）；探针结论经独立 TTL 缓存消费（缺省 300s，与 arbiter 前置闸同源口径），配置变更经 TTL 重探自然感知。
- **探针稳态边沿发射**：探针周期判定「同判」（`(ok, fallback_verdicts, reasons 归一集)` 三元全同）时不逐拍重打同文 WARNING；判定结论变化（含进程启动首判）即时发射；稳态期以每小时至多 1 条携带持续时长的心跳维持可观测性（持续时长 monotonic 时基计，稳态记忆进程级单例锁保护）。任一位漂移（unhealthy 同判但失败形态变化——如 CLI 缺失变为凭据缺失叠加）按新边沿即时发射，防形态漂移被同判静默吞掉。「部署形态不可判定」按显式稳态处理：判定结论与回落冻结闸拦截语义保持现状，仅观测面按稳态降噪。
- **双发射点一致**：agent_runner 探针体与 daemon 自检消费点共享同一稳态判定（边沿/心跳拍标记随探针结果携带），同一判定拍至多一条 WARNING 日志。
- **lane_env 告警生命周期对齐稳态**：lane_env_unavailable 告警在人工 handled 后，同一稳态持续期间 MUST NOT 被任何告警登记调用方重开（闸收口在 ensure_lane_env_alert 入口，覆盖 daemon 启动自检/周期 tick 与 arbiter run infra 失败路径两个登记方）；判定改变（环境形态实测变化或试呼裁决翻转）才按新边沿重新登记。稳态不重开闸 MUST NOT 拦截 AdminStore 定位改写路径——同 dedup_key 告警创建时刻超 24 小时（`UNHANDLED_ESCALATION_AGING_HOURS` 口径）时 recommended_action 就地翻转为「需人工升级」话术（幂等改写，未超时不改），破无人值守挂账死锁。告警正文承诺的生命周期语义（如「随恢复自动关闭」「无需人工处置」）必须与实际关闭/重开行为一致。
- **版本白名单全车道一致**：dsh 版本前置检查（复用 adapter `check_health`：版本白名单 + Bundle 挂载探测，不新写检查逻辑）挂 `_run_agent` 共享 spawn 前置段，覆盖全部经该段的车道——含 spec-review/dispute-judge 等不经 `_execute_agent` 的直调车道；同一版本漂移在所有车道一致拦截（拒派文案带 `[harness-health-gate]` 前缀），而非 spawn 后死于 bundle 插件不兼容。claude 通道无 `check_health` 成员零动作放行（duck-typing 同既有口径）。结论按 adapter 级 TTL 缓存复用（TTL 内多次 spawn 只起一次探测子进程，禁逐 spawn 起 `dsh --version` 子进程；子进程短超时同 `PROBE_HEALTH_TIMEOUT_S`；体内异常收口为结构化拒派文案）。
- **检查范围划界**：DNS 连通预检白名单（`_DISPATCH_PROBE_LANES`）对 dispatch 族的排除维持不变（独立机制，本能力不触碰）；arbiter 前置闸已覆盖项保持。秒挂冷却与秒挂计数语义不变——冻结拦截发生在 spawn 之前，不产生可计数的秒挂 run。

## 关键行为

回落角色派发到达 `_run_agent` → 冻结闸按角色消费探针 verdict（TTL 缓存）→ 非 ok 即拦截（拒派 + 单条告警计数）→ 默认链凭据补齐/显式链分配/放行键打开后放行并自动关闭告警。env 嗅探不可判定时探针按 30 分钟 TTL 降级试呼一次取证，裁决翻转即新边沿即时播报并重新武装告警登记。版本漂移时版本闸在 spawn 装配后、进程启动前拦截全部车道 → 预检拒绝替代 spawn 秒挂。稳态期同判不逐拍刷日志（边沿 + 每小时心跳），告警不因人工 handled 后的同判稳态重开。

## 代码锚点

- 主实现：`core/agent_runner/lane_preflight.py`（probe_default_chain_credentials 三值判定与降级试呼、fallback_verdicts 输出、稳态边沿标记、ensure_lane_env_alert 登记闸与 provider_fallback_frozen 告警生命周期）、`core/agent_runner/runner.py`（_provider_fallback_dispatch_gate 与 _shared_adapter_health_gate，均挂 _run_agent 共享 spawn 前置段）、`fenixd.py`（启动自检与周期 tick 消费点）
- 配置单源：`core/agent_runner/runner.py:PROVIDER_FALLBACK_ALLOW_KEY`（agents.allow_harness_default_fallback 显式放行键）
- 守卫测试：`tests/test_provider_fallback_dispatch_gate.py`、`tests/test_lane_preflight_credential_probe.py`、`tests/test_lane_preflight_steady_noise.py`

## 溯源

- 2026-11-16 evo-provider-fallback-dispatch-gate（spec/changes/evo-provider-fallback-dispatch-gate/） — 新建本能力：probe② 扩展回落角色三值凭据判定（不再静默跳过）、回落首派发冻结与按角色单条告警（修订 add-harness-default-key-fallback「仅留痕不拦派发」裁定）、显式放行键兜底、版本白名单前置检查挂共享 spawn 前置段覆盖直调车道（DNS 连通预检排除维持不变）
- 2026-11-27 evo-repair-lane-credential-probe-fix（spec/changes/evo-repair-lane-credential-probe-fix/） — 修订：默认链凭据嗅探不可判定时按 30 分钟 TTL 降级试呼取证（进程级共享单例、短超时、失败按 unhealthy fail-open，替代「纯本地检查不发 API 请求」的永久不可判定死路）、回落链凭据供给走 systemd.env ANTHROPIC_* 注入通道、lane_env 告警挂账超 24 小时 recommended_action 翻转为需人工升级（AdminStore update 就地改写、幂等）（动因：repair 车道凭据两级配置均缺显式链、探针纯本地判定 permanent indeterminable、告警挂账 62 小时「无需人工处置」话术与超时无升级通道形成死锁）
- 2026-11-27 evo-lane-probe-steady-noise-governance（spec/changes/evo-lane-probe-steady-noise-governance/） — 修订：探针稳态边沿发射（同判三元全同不逐拍重打、每小时心跳带持续时长、形态漂移即新边沿）、双发射点一致（同判定拍至多一条 WARNING）、lane_env 告警同判稳态不重开闸（ensure_lane_env_alert 入口收口、update 改写路径放行）与正文承诺对齐实际生命周期（动因：CLI 默认档部署逐拍双发射点 WARNING 约 1.6MB/天挤占日志留存、人工 handled 后同判稳态三度重开假工单；判定结论与冻结闸拦截语义零改动）
