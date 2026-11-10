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
- path: spec/knowledge/index.md
  kind: modify
```

设计真相源：本 change `design.md` + `spec/knowledge/domains/provider-models/failover-dispatch.md`。前置依赖：2026-11-09 事故修复 ①（`runner._switch_signal_text` 与 attempt 环双源闸门）已在 main；本 SPEC 只处理维护车道 ②，不改 ④ 冷却时长。

# Tasks — 维护车道接入 provider 退避链

## 1. 调查与归因

- [ ] 1.1 现场取证到 findings.md：从 `.fenix/runs`（含 `archive/`）复采 2026-11-09 夜间 `code-review-1794240196`/`1794240502`、`admin-*-1794231891`/`-1794231896`、`arbiter-*-1794231901`、`review-2026-11-10` 的 provider_marker，记录 `chain_index=0/chain_len=1`、429 文案所在事件（`assistant.api_error_status=429`、`result.result`）、及其与 ① 修复的边界（① 只管 dispatch attempt 环）；附「链配置双候选但车道只跑链首」的对照证据。

## 2. 共享 failover 助手

- [ ] 2.1 `core/agent_runner/maintenance_runs.py` 新增 `_run_lane_agent_with_failover(...)`：入参含 `runner`、`run_id`、`spec_name`、`agent_type`、`assignment`、`prompt`、`cwd`、`env_overrides`、`post_provider_env`、`max_turns`、`fallback_model`；内部按 `runner._select_chain_candidate` 选候选（跳过 circuit/switch 冷却）、`_apply_provider_env` → `post_provider_env` → `_write_lane_provider_marker(..., chain_index, chain_len, attempt)` → `_run_agent`（解包 5 元）；失败用 `runner._switch_signal_text(error, exc)` + `runner.classify_switch_error(...)` 判定，429 调 `_record_switch_cooldown(..., cooldown_seconds=PROVIDER_RATELIMIT_COOLDOWN_SECONDS)`，拒模型调 `_record_unrecognized_model`，换下一候选；候选上限 = 链长；全链冷却/耗尽抛含 `[model-chain-unavailable]` 的 `RuntimeError`（R1/R2/R3/R6）。
- [ ] 2.2 `_write_lane_provider_marker` 扩展 `chain_index`/`chain_len`/`attempt` 参数（默认 `0/1/None` 保兼容），移除硬编码，透传 `runner._write_provider_marker`（R1/R5）。
- [ ] 2.3 helper 单测（tests/test_maintenance_lane_failover.py）：双候选链首候选 429（result 事件结构化）→ 换第二候选成功；全冷却时不调 `_run_agent` 直接 `[model-chain-unavailable]`；HTTP 404 不换候选原样上抛；业务失败/超时不换候选；桩 runner 缺簿记方法 fail-open（R2/R4/R7）。

## 3. 六车道接入

- [ ] 3.1 `run_administrator` 改接 helper（fallback `model_override = runner._get_admin_model()`，保留 `max_turns=runner._get_config("agents.max_turns",300)` 与 `spec_name`/`agent_type="administrator"` 传参）。
- [ ] 3.2 `run_arbiter` 改接 helper（fallback `ARBITER_PINNED_MODEL`，不新增 max_turns 显式传参）。
- [ ] 3.3 `run_self_review` 与 `run_evolution` 改接 helper（self-review > administrator 链；evolution 的 `CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS="0"` 经 `post_provider_env` 在每候选 `_apply_provider_env` 之后注入）。
- [ ] 3.4 `run_code_review` 改接 helper（role 链 code-review > self-review > administrator；`max_turns=None`；helper 重抛异常 MUST 保留 `api_error_status`/`result_text`/`stderr_lines` 属性供 429 重派归因）。
- [ ] 3.5 `run_code_fix` 改接 helper（role 链 code-fix > code-review > self-review > administrator；marker 仍写 `spec_name="code-review-fix"`、`agent_type="code-fix"`）。
- [ ] 3.6 每车道回归用例：双候选链下首候选 429 换候选成功、provider_marker 记录真实 `chain_index`/`chain_len`（含 `attempt`）、返回值 5 元结构与既有降级/告警路径逐字段不变（R1/R5/R7）。

## 4. 429 重派按链解析

- [ ] 4.1 `run_code_review` 终局 429 时重派意图（`ratelimit_redispatch` 事件 / `_schedule_ratelimit_redispatch` 调用）增 `chain_len` 与失败候选信息；`core/admin_monitor.py` 的 `_consume_ratelimit_redispatch` 复跑前重新解析链并按当时冷却状态跳过候选（不固定复用 `assignment[0]`）；`RATELIMIT_REDISPATCH_MAX=1` 与 300s 冷却不变（R6）。
- [ ] 4.2 测试：重派意图含链信息；复跑模拟首候选冷却期 → 实际使用第二候选。

## 5. 回归验证

- [ ] 5.1 定向套件全绿：`tests/test_provider_failover.py`、`tests/test_provider_circuit.py`、`tests/test_transient_backoff.py`、`tests/test_maintenance_lane_failover.py`、`tests/test_run_agent_call_site_arity.py`、admin_monitor/code-review 相关用例。
- [ ] 5.2 全量 `python3 -m pytest tests -q` 绿；确认无新增 `threading.Timer`/后台线程（复用既有调度节拍）；确认 manifest/terminal-salvage/证据读侧对多 attempt 单文件仍取末条口径。

## 6. 知识回填

- [ ] 6.1 更新 `spec/knowledge/domains/provider-models/failover-dispatch.md`：维护车道纳入链 failover、provider_marker 真实链下标（不再恒 0/1）、429 重派按链解析；同步 `spec/knowledge/index.md` 计数与时间戳。
