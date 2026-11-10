<!-- knowledge: capability=maintenance-lane-provider-failover rev=1 sources=spec/changes/add-maintenance-lane-provider-failover -->

# 维护车道 provider 候选环（链 failover）

六条 LLM 维护车道与两条判官范式车道在单 run 内按配置的 provider 候选链自动换候选的能力：dispatch attempt 环之外的第二条 failover 面，判定/冷却/分类与 dispatch 环共用同一原语。

## 规则

- 适用八条车道：六条 LLM 维护车道（administrator / arbiter / self-review / evolution / code-review / code-fix）与两条判官范式车道（spec-review / dispute-judge）。`run_regression`（不经 LLM）与 `run_impl_ocr`（外部二进制）不经候选环。
- 链解析按各车道既有角色回退顺序 or-fold 取首个非空链：administrator→`administrator`；arbiter→`arbiter`；self-review / evolution→`self-review`→`administrator`；code-review→`code-review`→`self-review`→`administrator`；code-fix→`code-fix`→`code-review`→`self-review`→`administrator`；spec-review→`spec-review`；dispute-judge→`dispute-judge`。选候选按 circuit/switch/限流冷却跳过不可用者，取首个可用候选；候选尝试上限=链长，不超出。
- 链为空（未配置 `agents.models`）保持既有回退语义单次执行、不写 provider_marker、不换候选：维护车道回退 `_get_admin_model()` 默认网关形态、arbiter 回退 `ARBITER_PINNED_MODEL` 常量、判官范式车道回退 `DEFAULT_GATEWAY_MODEL` 默认网关。行为与无链形态逐字段一致。
- 切换类错误失败→本 run 内换链上下一个未冷却候选；429 记 300s 限流冷却（`PROVIDER_RATELIMIT_COOLDOWN_SECONDS`，复用 switch 冷却通道），拒模型/5xx/连接类记 switch 冷却。非切换错误（4xx 配额/鉴权、结果门禁失败、业务失败、超时）不换候选、异常原样上抛交各车道既有降级/告警/升级路径（上抛前挂载候选上下文，供车道归因 provider 维度）。
- 切换判定信号单源：复用 `runner._switch_signal_text` + `classify_switch_error`（error 文本 + result_text + `api_error_status` 三源）；不读降噪文本反推、不以 `[claude-code:unrecognized_model]` stderr 噪声行为切换依据。判定原语缺失 fail-loud（AttributeError，禁静默回退单发）；簿记面（marker 写点/冷却/拒模型记账/当日 attempt 计数）缺方法 fail-open 不阻断 run；已试下标经 `skip_indexes` 本地记账，簿记 fail-open 时选择器也不得重复选同一候选烧链。
- 全链候选均处于冷却/耗尽时廉价失败：抛文本含 `[model-chain-unavailable]` 的 `RuntimeError`、不启动新进程，交既有降级路径（admin 证据、code-review 停滞告警、evolution 失败记录）。链上确有候选尝试过时，聚合异常保留最后一次失败的结构化属性（429 终局归因与判官范式归因桥接依赖）；链尾候选为拒模型时按 dispatch 环同款语义注入「全链模型不可用」标注（派发读侧据此跳过同因重派）。
- 候选环本体单源在 runner（见 [ADR-343](../../adr/ADR-343-maintenance-lane-candidate-ring-single-source-in-runner.md)）：`AgentRunner._run_agent_with_chain_failover` 一次实现；维护车道经 `maintenance_runs._run_lane_agent_with_failover` 薄封装只传差异参数（roles 回退顺序、fallback_model、post_provider_env、max_turns、marker 专用名）；判官范式两方法直调同一环。禁止车道本地复制判定/冷却/选链逻辑。
- 判官范式镜像同步：`run_spec_review` 与 `run_dispute_judge` 为复制粘贴镜像方法，模型路由/换候选/marker 共性行为 MUST 两处同步（守卫测试断言两方法均经同一候选环、仅角色名/默认网关参数不同）；各自收口语义（cancelled / frozen / run-stall-budget / catch-all 归因回填与 finally 摘除 harness 品牌登记）不挪入候选环 helper。
- 车道专属 env 后置注入：`post_provider_env` 在每候选 provider env 组装（`_apply_provider_env`：ANTHROPIC_* 与 provider.env 合并）之后合并——evolution 的 `CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS="0"` 顺序不变量与 code-fix per-agent env 注入在换候选后逐候选保持。
- 会话与产物形态：候选间不续会话，每候选开新会话（车道从不传 resume_session_id，跨 provider session 不可复用）；单 run 单 jsonl 多 attempt 事件流，不引入 `-aN` 子 run；provider_marker additive `attempt` 字段读侧忽略即兼容。
- 观测契约：每候选启动前写 provider_marker，记录真实 `chain_index`/`chain_len` 与 attempt；换候选日志点名车道（lane_name = agent_type or marker_agent_type or spec_name，self-review/evolution 的 `_run_agent` 不传 agent_type 时由 marker 名/spec 名兜底）并含前/后候选与原因（429/unrecognized_model/5xx/conn）；车道终态指标 provider 维度取最终成功候选；判官范式车道 `AgentRunResult.provider_used`/`model_used` 取最终候选（默认网关回退路径 provider_used=None）。
- 429 终局重派按链解析：全链候选皆 429 终局时归因保留 `api_error_status=429` 等结构化属性；重派意图 additive 携带 `chain_len` 与失败候选列表（环未介入时省略该键，向后兼容）；重派消费复跑重新解析链并按当时冷却跳过候选，不固定复用首跑链首；重派预算仍为 `RATELIMIT_REDISPATCH_MAX=1`。
- 拒模型记账词表覆盖 stderr `[claude-code:unrecognized_model]` 形态与网关「Model not found: <model>」HTTP 400 正文形态（与切换类词表共用收窄正则单源 `MODEL_NOT_FOUND_TEXT_PATTERN`）。

## 代码锚点

- 候选环本体：`core/agent_runner/runner.py`（`AgentRunner._run_agent_with_chain_failover`；判官范式方法 `run_spec_review` / `run_dispute_judge`）
- 车道薄封装：`core/agent_runner/maintenance_runs.py`（`_run_lane_agent_with_failover` 及六车道调用点；`DEFAULT_GATEWAY_MODEL`）
- 429 重派链信息：`core/admin_monitor.py`（重派意图/消费携带 chain_len 与失败候选）
- 守卫测试：`tests/test_maintenance_lane_failover.py`（候选环单测、六车道回归、判官镜像契约）；`tests/test_provider_failover.py`（既有家族回归）

## 溯源

- 2026-11-10 add-maintenance-lane-provider-failover（spec/changes/add-maintenance-lane-provider-failover/） — 新建本页：八条车道接入单 run 候选环（链解析/换候选/限流冷却/全链耗尽/观测契约/429 重派按链解析/fail-open），判定与冷却复用 dispatch 环原语单源；验证轮补拒模型记账词表「Model not found」正文形态
