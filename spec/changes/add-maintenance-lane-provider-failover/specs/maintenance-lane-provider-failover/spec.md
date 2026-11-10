# 能力规格：maintenance-lane-provider-failover

## 需求

- **R1 链路解析与候选选择**：六条 LLM 维护车道（administrator / arbiter / self-review / evolution / code-review / code-fix）SHALL 经 `runner._get_agent_model_assignment(<role>)` 解析**完整**链（保留各车道既有回退顺序：administrator→`administrator`；arbiter→`arbiter`（无配置回退 `ARBITER_PINNED_MODEL` 常量）；self-review→`self-review`→`administrator`；evolution→`self-review`→`administrator`；code-review→`code-review`→`self-review`→`administrator`；code-fix→`code-fix`→`code-review`→`self-review`→`administrator`），并 MUST 按 `is_circuit_open` / `is_switch_cooldown` 跳过不可用候选、选首个可用候选。链为空时 MUST 保持既有回退模型（`_get_admin_model()` / `ARBITER_PINNED_MODEL`）单次执行语义。`provider_marker` MUST 记录实际 `chain_index` 与 `chain_len`（链长，非恒 1），MAY 追加 `attempt` 序号；未配置链的路径 MUST NOT 写 marker（与现状一致）。
- **R2 单 run 内换候选**：候选以切换类错误失败时，本 run MUST 换链上下一个未冷却候选重试，候选尝试上限 = 链长，MUST NOT 超出。429 限流 MUST 复用 `_record_switch_cooldown(provider, cooldown_seconds=PROVIDER_RATELIMIT_COOLDOWN_SECONDS)`（300s，本 SPEC 不改时长）；其余切换类按 switch 冷却。全链候选均不可用/冷却时 MUST 以 `[model-chain-unavailable]` 归因廉价失败并 MUST NOT 启动新进程。
- **R3 判定信号单源**：切换判定 MUST 复用 `runner._switch_signal_text(error, exc)` + `runner.classify_switch_error(...)`（`error` + `result_text` + `api_error_status` 三源）；MUST NOT 只读 `str(exc)` 降噪文本；MUST NOT 把 `[claude-code:unrecognized_model]` stderr 诊断噪声行作为切换依据（由模型名唯一决定，成功 run 同样在场）。
- **R4 非切换错误不换候选**：4xx 配额/鉴权（`PROVIDER_CIRCUIT_4XX`）、结果门禁失败、业务失败、超时 MUST NOT 触发换候选；异常 MUST 原样上抛，交由各车道既有降级/告警/升级路径处理。
- **R5 观测契约**：每次候选启动前写 `provider_marker`。发生换候选时 MUST 写一条日志，含车道（agent_type）、前候选、后候选与原因（429/unrecognized_model/5xx/conn）。车道终态指标 provider 维度 MUST 取最终成功候选。
- **R6 429 终局重派按链解析**：终端 429 归因 SHALL 携带链信息（`chain_len`、失败候选）；重派消费复跑时 MUST 重新解析链并按冷却跳过候选（MUST NOT 固定复用首跑链首），重派上限仍为 `RATELIMIT_REDISPATCH_MAX=1`。
- **R7 兼容与 fail-open**：各车道返回值结构、manifest 写点、终态归因、降级路径 MUST 不变；桩/替身 runner 缺 marker 写点或簿记方法时 MUST fail-open 不阻断 run；未配置 `agents.models` 时行为 MUST 与现状逐字段一致。

## 场景

#### Scenario: code-review 车道 429 换候选成功
- **WHEN** code-review 车道链为 `[bigmodel.cn/glm-5.3-flash, deepseek/deepseek-flash]`，首候选返回 rc=1 且 stderr 仅 `[claude-code:unrecognized_model]` 噪声行、429 文案只出现在 result 事件的 `result`/`api_error_status`
- **THEN** 本 run 内换第二候选取代成功，run jsonl 写两条 provider_marker（`chain_index=0/1, chain_len=2`），首候选进入 300s 限流冷却，车道返回成功且新增换候选日志

#### Scenario: 拒模型换候选并在链尾归因
- **WHEN** 候选以 HTTP 400 拒模型正文（只在 result 事件 `result` 字段）失败
- **THEN** 框架调用 `_record_unrecognized_model` 记账并换下一候选；若链尾候选仍被拒，错误文本带 `[model-chain-unavailable]` 归因供派发/告警读侧识别

#### Scenario: 全链冷却廉价失败
- **WHEN** 链上全部候选均处于 switch/限流冷却期
- **THEN** 车道不调用 `_run_agent`、不启动 claude 进程，直接以 `[model-chain-unavailable]` 归因失败并交既有降级路径

#### Scenario: 4xx 不换候选
- **WHEN** 候选以可解析 HTTP 404（配额/鉴权类）失败
- **THEN** 不换候选、异常原样上抛，车道既有降级/告警行为不变

#### Scenario: 业务失败不换候选
- **WHEN** 候选进程正常结束但结果门禁判失败或 run 超时
- **THEN** 不换候选、原样上抛，避免把业务失败误当 provider 故障烧链

#### Scenario: 未配置链保持现状
- **WHEN** `agents.models.<role>` 未配置
- **THEN** 车道沿用既有 `_get_admin_model()` 等回退模型单次执行，不写 provider_marker、不换候选，行为与现状逐字段一致

#### Scenario: 429 重派按链解析
- **WHEN** 终局归因为 429（全链候选均失败）且重派额度未耗尽
- **THEN** 冷却到期后重派复跑重新解析链并按冷却跳过候选，意图/日志携带 `chain_len` 与失败候选，重派至多一次

#### Scenario: marker 链下标真实
- **WHEN** 六条维护车道任一在配置了双候选链时执行
- **THEN** provider_marker 的 `chain_len=2` 且 `chain_index` 为实际使用候选下标；仅当角色链真实长度为 1 时才写 `chain_len=1`

## Deliverables

- path: core/agent_runner/maintenance_runs.py
  kind: modify
- path: core/agent_runner/runner.py
  kind: modify
- path: core/admin_monitor.py
  kind: modify
- path: tests/test_maintenance_lane_failover.py
  kind: new
- path: tests/test_provider_failover.py
  kind: modify
- path: spec/knowledge/domains/provider-models/failover-dispatch.md
  kind: modify
