# Proposal — 维护车道接入 provider 退避链

## Why

2026-11-09 夜间 glm-5.3 周/月额度耗尽，事故有两处断点：①普通 agent 的 attempt 环切链闸门只读降噪后的 error 文本（已由 lead 手动修复）；②**六条 LLM 维护车道根本没有链 failover**——只取 `assignment[0]` 直连、`provider_marker` 链下标恒 0/1，429/拒模型后车道只能终态失败，链上配置的 deepseek 兜底对车道不可见。code-review 车道因此整夜 429：16:03:22Z 首跑撞 bigmodel 429，16:08:27Z 重派仍复跑链首再撞同一 429，重派额度耗尽。用户批复立项（full），本地 11:00 后执行。

## What Changes

- **R1 链路解析**：六条维护车道（administrator / arbiter / self-review / evolution / code-review / code-fix）解析完整 `agents.models.<role>` 链（保留各自既有角色回退顺序），按 circuit/switch/限流冷却跳过候选；`provider_marker` 如实写 `chain_index / chain_len`（新增 additive `attempt` 字段）。
- **R2 单 run 内链推进**：车道单 run 内对切换类错误（`unrecognized_model` / HTTP 5xx / 连接类 / 429）自动换链上下一个未冷却候选，候选上限 = 链长；429 命中 `PROVIDER_RATELIMIT_COOLDOWN_SECONDS`（300s）限流冷却，其余切换类走 switch 冷却；全链冷却 → `[model-chain-unavailable]` 廉价失败（不启进程）。
- **R3 归因双源**：切换判定复用①落地的 `runner._switch_signal_text`（`error` + `result_text` + `api_error_status`），锁死「不得读降噪文本反推、不得回填 `[claude-code:unrecognized_model]` 噪声行」口径。
- **R4 429 终局重派按链解析**：终局 429 = 全链皆败；重派消费复跑时重新解析链并跳过当前冷却候选（不再固定复用首跑链首），重派预算仍为 1，重派意图/日志携带链信息。
- **R5 兼容与 fail-open**：各车道返回值、manifest、终态归因、降级/告警路径不变；未配置 `agents.models` 时行为与现状完全一致（单候选回退模型）；run jsonl 保持单文件多 attempt 事件流。
- **R6 回归与知识回填**：新增 `tests/test_maintenance_lane_failover.py` 覆盖全部场景；回填 provider-models 知识域。

**BREAKING**：无。`provider_marker` 仅追加字段，读侧向后兼容。

## Capabilities

### New Capabilities

- `maintenance-lane-provider-failover`: 维护车道 provider 链选择、切换类错误换候选、429 限流冷却、全链耗尽语义、429 终局重派按链解析与观测契约。

### Modified Capabilities

- `failover-dispatch`: 现有「切换类错误驱动链前进」契约的适用面从 dispatch attempt 环扩展到维护车道单 run 候选环；`provider_marker` 的 `chain_index/chain_len` 在维护车道不再恒为 0/1。

## Impact

- `core/agent_runner/maintenance_runs.py`：新增共享 failover 助手，收敛 6 处重复组装块与 `_run_agent` 单次调用。
- `core/agent_runner/runner.py`：不改切链判定逻辑，仅复用 `_switch_signal_text` / `_select_chain_candidate` / 冷却与拒模型记账原语（如需暴露簿记接口则做最小 additive 改动）。
- `core/admin_monitor.py`：429 重派日志/意图携带链信息（复用既有重派配额与 Timer 语义，不改调度时延）。
- `tests/test_maintenance_lane_failover.py`（新增）、`tests/test_provider_failover.py`（既有用例回归）。
- 知识域 `spec/knowledge/domains/provider-models/`（failover-dispatch 能力页与 `_domain.md` 计数回填）。
