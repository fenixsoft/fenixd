## Deliverables

```yaml
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
- path: spec/changes/add-maintenance-lane-provider-failover/findings.md
  kind: new
- path: spec/knowledge/domains/provider-models/failover-dispatch.md
  kind: modify
- path: spec/knowledge/domains/provider-models/_domain.md
  kind: modify
- path: spec/knowledge/domains/spec-lifecycle/spec-review-agent.md
  kind: modify
- path: spec/knowledge/index.md
  kind: modify
```

设计真相源：本 change `design.md` + `spec/knowledge/domains/provider-models/failover-dispatch.md`。前置依赖：2026-11-09 事故修复 ①（`runner._switch_signal_text` 与 attempt 环双源闸门）已在 main；本 SPEC 处理维护车道 + 判官范式车道（spec-review / dispute-judge）②，不改 ④ 冷却时长。

# Tasks — 维护车道接入 provider 退避链

## 1. 调查与归因

- [x] 1.1 现场取证到 findings.md：从 `.fenix/runs`（含 `archive/`）复采 2026-11-09 夜间 `code-review-1794240196`/`1794240502`、`admin-*-1794231891`/`-1794231896`、`arbiter-*-1794231901`、`review-2026-11-10` 的 provider_marker，记录 `chain_index=0/chain_len=1`、429 文案所在事件（`assistant.api_error_status=429`、`result.result`）、及其与 ① 修复的边界（① 只管 dispatch attempt 环）；附「链配置双候选但车道只跑链首」的对照证据。

## 2. 共享 failover 助手

- [x] 2.1 `core/agent_runner/runner.py` 新增候选环 `AgentRunner._run_agent_with_chain_failover(...)`：入参含 `run_id`、`spec_name`、`agent_type`、`assignment`、`prompt`、`cwd`、`provider_env`/`post_provider_env`、`max_turns`；内部按 `_select_chain_candidate` 选候选（跳过 circuit/switch/限流冷却）、组装 provider env（`_apply_provider_env` → `post_provider_env`）→ `_write_provider_marker(..., chain_index, chain_len, attempt)` → `_run_agent`（解包 5 元）；失败用 `_switch_signal_text(error, exc)` + `classify_switch_error(...)` 判定，429 调 `_record_switch_cooldown(..., cooldown_seconds=PROVIDER_RATELIMIT_COOLDOWN_SECONDS)`，拒模型调 `_record_unrecognized_model`，换下一候选；候选上限 = 链长；成功返回 5 元组 + 实际 `provider_name/model_override`；全链冷却/耗尽抛含 `[model-chain-unavailable]` 的 `RuntimeError`（R1/R2/R3/R6）。
- [x] 2.2 `core/agent_runner/maintenance_runs.py` 新增薄封装 `_run_lane_agent_with_failover(...)`：解析角色回退顺序 `assignment`、回退模型、既有 env 合并与 marker 落盘参数、`max_turns` → 调 runner 候选环；`_write_lane_provider_marker` 扩展 `chain_index`/`chain_len`/`attempt` 参数（默认 `0/1/None` 保兼容），移除硬编码并透传 `runner._write_provider_marker`（R1/R5）。
- [x] 2.3 helper 单测（tests/test_maintenance_lane_failover.py）：双候选链首候选 429（result 事件结构化）→ 换第二候选成功；全冷却时不调 `_run_agent` 直接 `[model-chain-unavailable]`；HTTP 404 不换候选原样上抛；业务失败/超时不换候选；桩 runner 缺簿记方法 fail-open（R2/R4/R7）。
- [x] 2.4 判官范式共用性单测：直接断言 `run_spec_review` 与 `run_dispute_judge` 均经同一候选环（如 monkeypatch 候选环计数/入参），且未配置 `agents.models` 时两处仍走 `DEFAULT_GATEWAY_MODEL` 单次执行、不写 marker。

## 3. 六车道接入

- [x] 3.1 `run_administrator` 改接 helper（fallback `model_override = runner._get_admin_model()`，保留 `max_turns=runner._get_config("agents.max_turns",300)` 与 `spec_name`/`agent_type="administrator"` 传参）。
- [x] 3.2 `run_arbiter` 改接 helper（fallback `ARBITER_PINNED_MODEL`，不新增 max_turns 显式传参）。
- [x] 3.3 `run_self_review` 与 `run_evolution` 改接 helper（self-review > administrator 链；evolution 的 `CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS="0"` 经 `post_provider_env` 在每候选 `_apply_provider_env` 之后注入）。
- [x] 3.4 `run_code_review` 改接 helper（role 链 code-review > self-review > administrator；`max_turns=None`；helper 重抛异常 MUST 保留 `api_error_status`/`result_text`/`stderr_lines` 属性供 429 重派归因）。
- [x] 3.5 `run_code_fix` 改接 helper（role 链 code-fix > code-review > self-review > administrator；marker 仍写 `spec_name="code-review-fix"`、`agent_type="code-fix"`）。
- [x] 3.6 六条维护车道各自回归用例：双候选链下首候选 429 换候选成功、provider_marker 记录真实 `chain_index`/`chain_len`（含 `attempt`）、返回值 5 元结构与既有降级/告警路径逐字段不变（R1/R5/R7）。
- [x] 3.7 `run_spec_review` 改接候选环（角色链 `spec-review`，回退 `DEFAULT_GATEWAY_MODEL`；保留派发前结果文件清理、成功 `AgentRunResult(provider_used/model_used)`、except 四型与 finally 摘品牌登记）。
- [x] 3.8 `run_dispute_judge` 改接候选环（角色链 `dispute-judge`，回退 `DEFAULT_GATEWAY_MODEL`；保留派发前 unlink 旧裁决、收工补写 run stamp、result gate 与品牌登记收口），与 3.7 镜像同步。
- [x] 3.9 判官范式车道回归用例：spec-review / dispute-judge 各一条「双候选链首候选 429 → 换第二候选成功 + marker 真实链下标 + provider_used 为最终候选」；镜像契约断言两处均调用同一 helper。

## 4. 429 重派按链解析

- [x] 4.1 `run_code_review` 终局 429 时重派意图（`ratelimit_redispatch` 事件 / `_schedule_ratelimit_redispatch` 调用）增 `chain_len` 与失败候选信息；`core/admin_monitor.py` 的 `_consume_ratelimit_redispatch` 复跑前重新解析链并按当时冷却状态跳过候选（不固定复用 `assignment[0]`）；`RATELIMIT_REDISPATCH_MAX=1` 与 300s 冷却不变（R6）。
- [x] 4.2 测试：重派意图含链信息；复跑模拟首候选冷却期 → 实际使用第二候选。

## 5. 回归验证

- [x] 5.1 定向套件全绿：`tests/test_provider_failover.py`、`tests/test_provider_circuit.py`、`tests/test_transient_backoff.py`、`tests/test_maintenance_lane_failover.py`、`tests/test_run_agent_call_site_arity.py`、spec-review/dispute-judge 相关既有用例、admin_monitor/code-review 相关用例。
- [x] 5.2 全量 `python3 -m pytest tests -q` 绿；确认无新增 `threading.Timer`/后台线程（复用既有调度节拍）；确认 manifest/terminal-salvage/证据读侧对多 attempt 单文件仍取末条口径。（对账收口：`bin/run_full_suite.py --timeout 3600 --baseline main` 三轮取证——首轮 1746 失败为并发 pytest 的 basetemp 互删环境噪音；修替身窄签名（`tests/test_api_stall_disposition.py` 意图登记 stub 补 `chain_len/failed_candidates` 形参、`tests/test_daily_self_review.py` 六处 `_run_agent` stub 补 `agent_type` 形参）后收敛至 2 失败，baseline 对账归类**存量**（main 同败：fake-double-fidelity `_ClosedExecutor` 替身保真、logger-no-bypass `core/dsh_session_tidy.py:72` `fenix.` 层级非 `fenixd.`，两处均非本 SPEC 改动文件），**零引入回归**；Timer/线程零新增；读侧末条口径三处核实（dashboard provider_marker 取最后、`_read_terminal_message` 取末个 result、manifest 聚合 upsert 未触碰）。全量证据：worktree `.history/full_suite_5_2*.log`，对账结论同步主树 verify-evidence。）

## 6. 知识回填

- [x] 6.1 更新 `spec/knowledge/domains/provider-models/failover-dispatch.md`：维护车道与判官范式车道纳入链 failover、provider_marker 真实链下标（不再恒 0/1）、429 重派按链解析；同步 `spec/knowledge/domains/spec-lifecycle/spec-review-agent.md` 的模型路由段（判官范式车道按链选择）；同步 `spec/knowledge/index.md` 计数与时间戳。

## 验证修复（原地打回第 1 轮）

- [ ] 先复核失败有效性：逐条核对 `spec/changes/add-maintenance-lane-provider-failover/verification-report.md` 中失败场景的期望断言（状态字面量/选择器/前置数据）与产品实际行为是否相符——断言与产品不符属场景缺陷，修场景文件；确属产品行为不符才修产品代码
- [ ] 按复核结论修复：场景缺陷改场景文件，真实产品 Bug 改产品代码
- [ ] 修复后重跑验证确认通过
