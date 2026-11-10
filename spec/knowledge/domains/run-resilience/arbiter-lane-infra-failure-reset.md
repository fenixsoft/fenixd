<!-- knowledge: capability=arbiter-lane-infra-failure-reset rev=2 sources=spec/changes/harden-arbiter-lane-resilience -->

# arbiter 车道故障分级与 infra 复位

arbiter/repair 裁决车道的 run 失败按 infra/judgment 分级：环境秒挂（0 rounds、环境指纹命中）走 infra 通道——不进死人开关、不升级人工、资格保留，探针转 healthy 自动复位；两级前置自检在派发前拦截车道不可用（零状态变更）。judgment 失败资格治理（连败→dead-man 永久单次）语义不变。

## 规则

- 分级单源 `classify_lane_failure`：infra 判据满足任一——`run_arbiter` 信封 `rounds` 显式键 ≤0（rounds 是内部 turns 计数透传真值，MUST NOT 从 error 文案反解；键缺席保守判 judgment，旧信封零行为变化）；或 error/stderr 命中环境指纹集 `LANE_INFRA_FINGERPRINTS`（`MISSING_CREDENTIAL` / `No such file or directory` / `skipping profile bundle`，指纹可覆盖正 rounds）。预算耗尽（tokens/wallclock）恒判 judgment——那是真实车道的真实消耗，`_on_run_failed` 先行短路不经分级器。分级器自身不可用时按 judgment 语义保守处理（新机制故障不得改变死人开关行为）。
- infra 通道 `_on_infra_failed`：计数 `_infra_failure_counts` 独立于 judgment 连败计数（上限 `arbiter.max_consecutive_infra_failures`，缺省=既有连败上限同值）；写台账 kind=`infra-failed`（action 注明「环境不可用，待健康探针复位后重试」）；不加 `_deadmanned`、不升级人工 alert——WARNING 日志 + `lane_env_unavailable` 告警（dedup_key 单发）。达上限同样只记台账+告警：infra 计数是观察性的（healthy 复位使连败数常驻低位），资格保留是设计主旨。infra 路径返回终态字 `infra-failed`；异步路径（`_process_trigger`）忽略返回值零影响。
- 车道前置探针 `probe_lane_health` 两级检查：①CLI 可达——`agent.harness` 选型 → `HARNESS_EXECUTABLE_NAMES` → `precheck_harness_executable`（which 单源，与 dispatch 派发前置共用）→ adapter `check_health`（duck-typing；dsh=版本白名单+bundle 挂载探测，claude 通道无此成员零动作）；②凭据路由可解析——`agents.models.<arbiter|repair>` 显式链首选 provider 本地解析出非空 baseurl+apikey（纯本地检查，MUST NOT 发 API 请求），无显式链跳过不报。两级全 fail-open：探针自身异常按 unhealthy 处置并 WARNING，不抛出、不阻塞 daemon。
- 派发前置闸 `_preflight_gate`：探针结论走 TTL 缓存（`LanePreflightCache`，`arbiter.preflight_ttl` 缺省 300s，TTL 内复用、超时重探、热更新重建缓存）。闸置于两派发入口最前（`submit_trigger` 的 dedup/补绑/复现标记消费之前、`process_chain_handoff` 入口）。unhealthy → 拦截且零状态变更：不写 `_active`、不消费复现标记、不落台账、不计配额——submit_trigger 返回既有终态字 `deduped`（零新契约，信号靠既有触发面复报/回扫候选重扫自然回喂，不新增持有队列）；process_chain_handoff 返回 `infra-failed` 并回填 `_chain_failure_reason`。healthy → 放行并触发复位（触发点③）。disabled/excluded 先行短路：关闭态零侵扰，探针只在真实派发意图上把关。
- 复位消费 `on_lane_healthy`：清全部 infra 计数 + INFO「车道健康，infra 计数复位」；judgment 连败计数（`_failure_counts`）与 dead-man 永久语义（`_deadmanned` + 台账 dead-man 读侧）不动。计数为空时静默返回（周期探针高频复用不刷屏）。触发点三处：daemon 启动探针、主循环 60s 周期重探（挂 1s tick 时间门，禁内存定时器）、派发前置 healthy。
- 车道环境告警生命周期单点化：`ensure_lane_env_alert` / `resolve_lane_env_alert` 共用同 signal_type+dedup_key（任一路径开的告警任一路径都能关）；直写 AdminStore 不入处置链（防自环：处置链无法处置自己车道的死讯）；恢复关闭由 fenixd 周期探针承接（≤60s），`on_lane_healthy` 不碰告警（单一职责）。常态 healthy 零播报；曾 unhealthy 后首个 healthy 周期记一条 INFO 恢复留痕。
- 链消费（escalation_chain `_run_arbiter_phase`）：outcome=`infra-failed` 分支不循环重派、不上升链终点、不升级人工、不烧拍板配额（count_arbiter_ruling 仅在拍板出口计）；写 `chain-infra-deferred` 链事件按 deferred 让行范式留痕（不走 defer_in_flight——那是互斥让行专用形态，infra 停机无被让行对象）。信号闭环靠既有触发面复报/回扫候选重扫自然回喂。
- 台账读侧兼容：消费者只认 kind=dead-man（`_ledger_sigs(kinds={"dead-man"})`），infra-failed 行对 dead-man 判定/回扫排除完全不可见；仅 infra-failed 在案的同签名照常自主处置（无永久例外）。台账 append-only：infra-failed 是追加行，不破坏既有读纪律。
- 测试密闭性：arbiter 车道测试 MUST 预种探针缓存（healthy/unhealthy 显式结论），MUST NOT 依赖宿主 CLI/凭据环境；judgment 失败测试形态=报告写盘但 outcome 非法（turns=1 有往返）；`{"run": "raise"}` 形态判 infra（rounds=0）。

## 代码锚点

- 主实现：core/agent_runner/lane_preflight.py（classify_lane_failure 分级单源、probe_lane_health 两级探针、LanePreflightCache TTL 缓存、ensure_lane_env_alert 与 resolve_lane_env_alert 告警生命周期）
- infra 通道与前置闸：core/pm_engine/arbiter.py（_on_infra_failed、_preflight_gate、on_lane_healthy）
- 链消费分支：core/pm_engine/escalation_chain.py:_run_arbiter_phase（infra-failed → chain-infra-deferred）
- daemon 接线：fenixd.py（_startup_lane_preflight_check、_lane_preflight_consume）
- 配置单源：core/config.py:get_arbiter_config（max_consecutive_infra_failures / preflight_ttl 白名单键）
- 守卫测试：tests/test_arbiter_lane_resilience.py

## 溯源

- 2026-11-09 harden-arbiter-lane-resilience（spec/changes/harden-arbiter-lane-resilience） — 确立 infra/judgment 分级（classify_lane_failure 单源 + rounds 信封透传禁文案反解）、infra 通道资格保留（不进死人开关不升级人工）、probe_lane_health 两级前置自检与 TTL 闸拦截（deduped/infra-failed 零状态变更）、on_lane_healthy 三触发点复位、链 infra-failed 分支 deferred 留痕、台账读侧兼容回归（tests/test_arbiter_lane_resilience.py S1-S6 + preflight S1-S5）
- 2026-11-10 harden-arbiter-lane-resilience（spec/changes/harden-arbiter-lane-resilience） — 复核重蒸馏：规则段去历史叙述改纯当前态表述、补代码锚点段、结构对齐能力页契约；与盘上实现及 2026-11-10 验证报告（17/17 场景全绿）逐条核对零漂移，规则实质无变化
