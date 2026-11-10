# 验证报告：harden-arbiter-lane-resilience

> ⚠️ 本报告由框架于 2026-11-10T03:19:56Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-11-10T03:19:56.106565+00:00+run-result@mtime1794280796157918826

## 结论：✅ 通过（verified）

**状态：verified — 17/17 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 17/17 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 17 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 9.23M |
| 本链增量 Token（输出） | 0.13M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| classify-lane-failure-matrix | 能力 arbiter-infra-failure-reset R1：classify_lane_failure 判定矩阵。infra 判据（满足任一）：信封 rounds 显式键 ≤0；环境指纹命中（MISSING_CREDENTIAL / No such file or directory / skipping profile bundle，可覆盖正 rounds）。rounds 键缺席保守判 judgment（旧信封零行为变化）；正 rounds 无指纹判 judgment。指纹集单源 LANE_INFRA_FINGERPRINTS 三条与事故面逐条对应。预算耗尽不在分级器判定（调用方先行短路，由 budget-exhausted 场景专测）。 | pass | 0/6 | - |
| run-arbiter-rounds-passthrough | 能力 arbiter-infra-failure-reset R1：run_arbiter 信封 rounds 透传。正常路径信封 rounds=内部 turns 真值（禁文案反解的结构基础）；异常路径（_run_agent 抛带 MISSING_CREDENTIAL 指纹异常）信封 rounds=0 且 error 携带指纹。分级按信封真值判定。 | pass | 0/5 | - |
| infra-channel-no-deadman | 能力 arbiter-infra-failure-reset S1：0 rounds + MISSING_CREDENTIAL 指纹连续失败超上限（3 次 > 缺省 2）→ 台账全为 infra-failed、_deadmanned 为空、无人工升级件；车道环境告警单发（dedup）；台账 action 注明待健康探针复位；同签名资格保留（第 4 次仍可入队）。附 0 rounds 无异常形态（信封 rounds=0 路径）同样 infra-failed。 | pass | 0/7 | - |
| judgment-roundtrip-deadman-regression | 能力 arbiter-infra-failure-reset S2 回归：有 API 往返的失败（turns=1 真实车道失败形态）连续达上限 → 现行 dead-man 永久升级语义不变；台账无 infra-failed（有往返 MUST NOT 误判 infra）。 | pass | 0/6 | - |
| budget-exhausted-judgment-deadman | 能力 arbiter-infra-failure-reset S3：run 预算耗尽（token 用量超 budget_tokens）恒判 judgment 走 dead-man，不误判 infra——预算耗尽是真实车道真实消耗。 | pass | 0/6 | - |
| lane-healthy-reset-infra-counts | 能力 arbiter-infra-failure-reset S4：infra 停机计数在案后探针转 healthy（on_lane_healthy）→ infra 计数全清 + INFO 留痕；judgment 连败计数与 dead-man 永久语义不动；同签名恢复自主处置再触发照常入队。计数为空时复位静默（周期探针高频复用零噪音）。 | pass | 0/7 | - |
| ledger-readside-infra-transparent | 能力 arbiter-infra-failure-reset S5/R4：历史台账含 infra-failed 行对读侧完全透明——dead-man 行照常命中永久例外（submit 触发 recurrence-escalated 不再派发）；仅 infra-failed 在案同签名照常入队（无永久例外、不阻回扫）；台账解析 infra-failed 行原样保留（append-only 不丢行）。 | pass | 0/5 | - |
| chain-infra-terminal-no-escalation | 能力 arbiter-infra-failure-reset S6：链交接 run infra 失败三面——①process_chain_handoff 返回终态字 infra-failed 且回填 run_id；②链驱动消费 infra-failed：不循环重派、不上升人工、deferred 范式留痕（chain-infra-deferred 事件）、不烧拍板配额（arbiter_rulings 计 0）；③前置探针 unhealthy 时链交接零状态变更让行（拦截返回 infra-failed + _chain_failure_reason、零台账）。 | pass | 0/11 | - |
| probe-lane-health-two-level | 能力 agent-lane-preflight R1：probe_lane_health 两级检查矩阵（密闭 patch precheck，不依赖宿主环境）——两级全过 ok；CLI 缺失 unhealthy 且 reasons 含 PATH 文案；显式链 provider baseurl/apikey 缺失 → arbiter/repair 双角色 unhealthy；凭据齐全不报；无显式链跳过不报（默认网关形态）；claude 通道无 adapter check_health 零动作放行。 | pass | 0/8 | - |
| probe-failopen-exception-unhealthy | 能力 agent-lane-preflight R4：探针自身异常 fail-open——precheck 内部抛异常时 probe_lane_health MUST NOT 抛出、按 unhealthy 处置且 reasons 含「探测异常」文案，不阻塞调用方。 | pass | 0/4 | - |
| preflight-ttl-cache-single-probe | 能力 agent-lane-preflight S4：探针结论 TTL 缓存——LanePreflightCache TTL 内多次取用只探一次；TTL=0 每次取用重探；invalidate 强制重探。车道闸侧同语义：TTL 内两次派发只探一次；preflight_ttl 热更新（300→600）下次取用按新 TTL 重建缓存。 | pass | 0/7 | - |
| preflight-gate-intercept-zero-state | 能力 agent-lane-preflight R3/S5：unhealthy 拦截期零状态变更——submit_trigger 在 dedup/复现标记消费之前被拦截，返回既有终态字 deduped，不写 _active、不计 infra 配额、不落台账、不入队、WARNING「派发前置自检拦截」留痕；process_chain_handoff 同样拦截返回 infra-failed 并回填 _chain_failure_reason。 | pass | 0/8 | - |
| preflight-gate-healthy-pass-reset | 能力 agent-lane-preflight S2 + arbiter-infra-failure-reset R3 触发点③：探针 healthy → 派发放行（submit_trigger 返回 queued）且此前 infra 停机计数被闸复位；关闭态（arbiter.enabled=false）先行短路零侵扰——探针不把关、不产生告警副作用。 | pass | 0/6 | - |
| lane-env-alert-lifecycle-fenixd | 能力 agent-lane-preflight R2/R4 接线面：fenixd 启动/周期探针——unhealthy 告警单发（同 unhealthy 周期 dedup_key 单发）、探针转 healthy 自动关闭（handled_by=auto-resolve）+ 边沿 INFO + 旗标复位；常态 healthy 零播报零告警；周期重探挂 60s 时间门（门内不重复探测）、启动探测同步推进周期门（禁内存定时器的结构性面）；AdminStore 故障时消费链 fail-open（WARNING 不击穿主循环）；周期探针 healthy 触发在场车道 infra 计数复位（能力一 R3 触发点）。 | pass | 0/9 | - |
| arbiter-config-new-keys-whitelist | 配置面（两能力共用）：ConfigLoader.get_arbiter_config 白名单扩展两新键——arbiter.max_consecutive_infra_failures（缺省=既有连败上限 2）与 arbiter.preflight_ttl（缺省 300）；显式值正整数归一（5/60）；非法值（0/负数/bool/浮点）回退缺省不抛异常；白名单外键不外透（旋钮必须经本单源）。 | pass | 0/8 | - |
| lane-resilience-testsuite-green | 交付测试面：tests/test_arbiter_lane_resilience.py（本 SPEC 交付的回归文件，覆盖两能力 S1-S6+S1-S5）全文件 pytest 运行全绿（41 用例），锚定 -q 形态「41 passed」输出子串与退出码 0。与相邻回归场景同 resource_group 互斥（防并行 pytest basetemp 互扰）。 | pass | 0/2 | - |
| adjacent-lanes-regression-green | 回归点：本 SPEC 触碰面（arbiter.py / escalation_chain.py / config.py / maintenance_runs.py / lane_preflight.py 消费方）相邻测试文件全绿——test_arbiter_lane / test_arbiter_guardrails / test_arbiter_backlog_sweep / test_escalation_chain / test_config / test_maintenance_ledger 六文件 211 用例。HOME 重定向临时目录隔离宿主用户级 ~/.fenix/config.yaml（防宿主 provider 引用形态污染告警计数类断言，2026-11-09 verifier env 归因教训修正）。与交付测试面同 resource_group 互斥。 | pass | 0/2 | - |

## 本轮场景集变更

当前稳定场景集共 28 个（第 1 轮）。

- 无理由缺失 11 个场景，已以持久化集补齐：preflight-module-contract-failopen、arbiter-config-whitelist-infrastructure-keys、lane-resilience-testsuite-coverage-floor、infra-failure-channel-no-deadman、judgment-channel-deadman-regression、ledger-readside-infra-failed-transparent、preflight-unhealthy-intercept-submit-zero-state、preflight-unhealthy-intercept-chain-handoff、preflight-healthy-dispatch-pass-and-infra-reset、chain-infra-terminal-no-escalation-deferred-trace、preflight-wiring-fenixd-no-memory-timer
- 新增场景 arbiter-config-new-keys-whitelist（重新规划，第 1 轮）
- 新增场景 budget-exhausted-judgment-deadman（重新规划，第 1 轮）
- 新增场景 chain-infra-terminal-no-escalation（重新规划，第 1 轮）
- 新增场景 infra-channel-no-deadman（重新规划，第 1 轮）
- 新增场景 judgment-roundtrip-deadman-regression（重新规划，第 1 轮）
- 新增场景 lane-env-alert-lifecycle-fenixd（重新规划，第 1 轮）
- 新增场景 lane-healthy-reset-infra-counts（重新规划，第 1 轮）
- 新增场景 ledger-readside-infra-transparent（重新规划，第 1 轮）
- 新增场景 preflight-gate-healthy-pass-reset（重新规划，第 1 轮）
- 新增场景 preflight-gate-intercept-zero-state（重新规划，第 1 轮）
- 新增场景 probe-failopen-exception-unhealthy（重新规划，第 1 轮）
- 新增场景 probe-lane-health-two-level（重新规划，第 1 轮）
- 新增场景 run-arbiter-rounds-passthrough（重新规划，第 1 轮）
- 无理由缺失且备份缺定义的场景 11 个定义不可恢复，已剔除：arbiter-config-whitelist-infrastructure-keys、chain-infra-terminal-no-escalation-deferred-trace、infra-failure-channel-no-deadman、judgment-channel-deadman-regression、lane-resilience-testsuite-coverage-floor、ledger-readside-infra-failed-transparent、preflight-healthy-dispatch-pass-and-infra-reset、preflight-module-contract-failopen、preflight-unhealthy-intercept-chain-handoff、preflight-unhealthy-intercept-submit-zero-state、preflight-wiring-fenixd-no-memory-timer

> ⚠️ 本轮 planner 产出缺少既有场景且无理由，已以持久化集补齐后继续验证（不中断验证）。

