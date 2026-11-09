<!-- knowledge: capability=arbiter-lane-infra-failure-reset rev=1 sources=spec/changes/harden-arbiter-lane-resilience -->

# arbiter 车道故障分级与 infra 复位

arbiter 调查 run 失败按 infra/judgment 分级：环境秒挂（0 rounds、环境指纹）走 infra 通道——不进死人开关、不升级人工、资格保留，探针转 healthy 自动复位；前置自检在派发前拦截车道不可用（零状态变更）。裁决失败资格治理（judgment 连败→dead-man 永久单次）语义不变。

## 现行规则

- 事故背景（2026-11-09）：dsh bundle 不兼容（`skipping profile bundle`）+ `MISSING_CREDENTIAL` 致四签名 0 rounds 秒挂（单 run 0.002s），旧语义全部落入连败→dead-man 永久人工；环境恢复后 dead-man 资格无法恢复，四签名人工停滞 8h。
- 分级单源 `classify_lane_failure`（core/agent_runner/lane_preflight.py）：信封 `rounds` 显式键 ≤0 → infra；`rounds` 键**缺席**保守判 judgment（旧信封/测试替身零行为变化）；error/stderr 命中环境指纹（`MISSING_CREDENTIAL` / `No such file or directory` / `skipping profile bundle`）→ infra（可覆盖正 rounds）。`rounds` 是 `run_arbiter` 信封透传的内部 turns 计数真值，MUST NOT 从 error 文案反解。预算耗尽恒判 judgment（`_on_run_failed` 先行短路，调用方判）。异常分级器不可用时按 judgment 语义保守处理（不因新机制故障改变死人开关行为）。
- infra 通道（`_on_infra_failed`）：独立计数 `_infra_failure_counts`（上限 `arbiter.max_consecutive_infra_failures`，不烧 judgment 连败资格）；台账 kind=`infra-failed`（五段完整，root_cause 补全集含此 kind）；**不**加 `_deadmanned`、**不**升级人工——WARNING 日志 + `lane_env_unavailable` 告警（dedup_key 单发）。达上限同样只记台账+告警：计数为观察性（闸 healthy 复位使连败数常驻低位），资格保留是设计主旨。异步路径终态字 `infra-failed`（_process_trigger 零影响）；0 rounds 秒挂形态经 `run_arbiter` 异常路径 rounds=0 / 早退路径 empty 信封 rounds=0 两处落。
- 前置自检 `probe_lane_health` 两级：①CLI 可达——`agent.harness` 选型 → `HARNESS_EXECUTABLE_NAMES` → `precheck_harness_executable`（which 单源，与 dispatch 派发前置共用）→ adapter `check_health`（duck-typing；dsh=版本白名单+bundle 挂载探测，claude 通道无此成员零动作）；②凭据路由——`agents.models.<arbiter|repair>` 显式链首选 provider 本地解析出非空 baseurl+apikey（纯本地检查，MUST NOT 发 API 请求）；无显式链跳过不报。两级全 fail-open：探针自身异常按 unhealthy+WARNING，不抛出。
- 派发前置闸 `_preflight_gate`（TTL 缓存 `LanePreflightCache`，`arbiter.preflight_ttl` 缺省 300s，热更新重建缓存）：unhealthy → 拦截点位于一切 dedup/复现标记消费之前，零状态变更（不写 `_active`、不消费补绑/复现标记、不落台账、不计配额）——submit_trigger 返回既有终态字 `deduped`（零新契约），process_chain_handoff 返回 `infra-failed` 并回填 `_chain_failure_reason`；healthy → 放行并触发复位（触发点③）。disabled/excluded 先行短路：关闭态零侵扰，探针只在真实派发意图上把关。
- 复位消费 `on_lane_healthy`：清全部 infra 计数 + INFO「车道健康，infra 计数复位」；judgment 连败（`_failure_counts`）与 dead-man 永久语义（`_deadmanned` + 台账 dead-man 读侧）**不动**。计数为空时静默返回（周期探针高频复用不刷屏）。触发点三处：daemon 启动探针、主循环 60s 周期重探（挂 1s tick 时间门，禁内存定时器）、派发前置 healthy。
- 告警生命周期单点化：`ensure_lane_env_alert` / `resolve_lane_env_alert` 在 lane_preflight.py，arbiter infra 路径与 fenixd 探针共用同 signal_type+dedup_key（任一路径开的告警任一路径都能关）；直写 AdminStore 不入处置链（防自环：链无法处置自己车道的死讯）；恢复关闭由 fenixd 周期探针承接（≤60s），on_lane_healthy 不碰告警（单一职责）。常态 healthy 零播报（曾 unhealthy 后首个 healthy 周期记一条 INFO 恢复留痕）。
- 链消费（escalation_chain `_run_arbiter_phase`）：outcome=`infra-failed` 分支——不循环重派、不上升链终点、不升级人工、不烧拍板配额（count_arbiter_ruling 仅在拍板出口计）；`_write_chain_event(kind="chain-infra-deferred")` deferred 范式留痕（不走 defer_in_flight——那是互斥让行专用形态，infra 停机无被让行对象）。信号闭环靠既有触发面复报/回扫候选重扫自然回喂。
- 台账读侧兼容：消费者只认 kind=dead-man（`_ledger_sigs(kinds={"dead-man"})` 与 DEADMAN_LEDGER_KINDS），infra-failed 行对 dead-man 判定/回扫排除完全不可见（零行为变化）；仅 infra-failed 在案的同签名照常自主处置（无永久例外）。
- 测试密闭性：arbiter 车道测试 MUST 预种探针缓存（healthy 或 unhealthy 显式结论），MUST NOT 依赖宿主 CLI/凭据环境；judgment 失败形态=报告写盘但 outcome 非法（turns=1 有往返），`{"run": "raise"}` 形态在新分级下是 infra（rounds=0）。

## 溯源

- 2026-11-09 harden-arbiter-lane-resilience（spec/changes/harden-arbiter-lane-resilience） — 确立 infra/judgment 分级（classify_lane_failure 单源 + rounds 信封透传禁文案反解）、infra 通道资格保留（不进死人开关不升级人工）、probe_lane_health 两级前置自检与 TTL 闸拦截（deduped/infra-failed 零状态变更）、on_lane_healthy 三触发点复位、链 infra-failed 分支 deferred 留痕、台账读侧兼容回归（tests/test_arbiter_lane_resilience.py S1-S6 + preflight S1-S5）
