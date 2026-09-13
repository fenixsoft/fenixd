# Proposal: fix-provider-transient-backoff

## Why

2026-09-07 取证定案（24h 内 7 次 run 死于网关瞬断，损失约 190 分钟 run 时长 / 约 $36 重跑成本）：runner 对 provider 瞬断（unrecognized_model / 5xx / 连接错误）的重试策略与网关故障形态错配——attempt 撞瞬断立即换链并把链上好 provider 打进 300s 冷却，网关全局瞬断时 3 次 attempt 全烧、`chain_exhausted` 收场；dispatch 级重派从零开始（新 run_id / 新 worktree / 新会话），分钟级投入的产出全废；且 runner 拼 error 取 stderr 末 5 行，被 CLI v2.1.233+ 每请求写入的 `[claude-code:unrecognized_model]` 诊断噪音行污染，死因被系统性误标，派发层无法把瞬断与真实失败区分开。

## What Changes

- **attempt 层原地退避优先于换链**：switch 类错误（unrecognized_model / 5xx / 连接类）首次失败不再立即换链 + 300s 冷却，改为同 provider 原地指数退避（缺省 30/60/120s）重试；同 provider 且 worktree 复用时用 `--resume` 同 session 续跑；原地重试 ≥2 次仍失败才走现行换链逻辑。原地重试不递增 attempt 计数。
- **worktree 现场保留扩展到全部 agent_type**：attempt 间 worktree 复用从 implementer/fast-track/repair 扩展到 planner-plan/planner-judge/verifier 等；transient 类错误导致的终态失败改为 `keep_for_reuse`（替代 `cleanup(success=False)`），下轮派发经既有 `_take_reusable_worktree` 通道认领同现场。
- **dispatch 级瞬断闸门**：error 终态带 `[provider-transient]` 结构化标记；dispatch 读到该标记不立即重入队，按配置窗口排程等待后重派（复用 instant_fail_recovery 定时器模式）；新增全局维度熔断——同一错误指纹 10 分钟窗口内 ≥3 次 → 冻结派发并冷却。
- **错误归因降噪**：拼装 error 消息前过滤 `[claude-code:...]` stderr 诊断噪音行；过滤后无有效内容时回退 `Exit code: N` 形态。死因归因恢复可信（dashboard / 人工排查 / dispatch 分类共用）。
- **新配置键 + Dashboard 设置界面**（同步落地，不允许先 YAML 后界面）：原地退避序列、dispatch 重派等待、熔断阈值/窗口/冷却时长，全部进 Settings 面板 SystemPanel。

非目标（明确不做）：跨 provider 移植 session 后 `--resume`（session 按 CLAUDE_CONFIG_DIR 隔离，移植有兼容风险且边际收益小）；drain 配置调整（用户决策暂不改）；CLI 内部重试参数调整（400 形态不重试是 CLI 行为，runner 层补足）。

## Capabilities

### New Capabilities

- `provider-transient-backoff`: runner attempt 层对瞬断错误的原地指数退避重试与同现场续跑（resume / worktree 复用全 agent_type / transient 终态 keep_for_reuse）。
- `transient-dispatch-gating`: dispatch 层对 `[provider-transient]` 终态的排程等待重派、全局同错误指纹熔断。
- `error-attribution-denoise`: run error 消息拼装时过滤 CLI stderr 诊断噪音行，保证错误归因可信。
- `transient-controls-ui`: 瞬断治理新配置键的 Dashboard Settings 界面能力。

### Modified Capabilities

（无——既有 add-provider-failover / cli-retry-backoff / interrupt-recovery-preserve 的 spec 级行为不变，本变更是在其旁新增判定优先级与闸门。）

## Impact

- `core/agent_runner/runner.py`：attempt 循环重试语义、worktree 保留分支扩展、终态 keep_for_reuse 分支。
- `core/agent_runner/provider_circuit.py`：switch 类错误处置策略（原地退避调度）、全局错误指纹熔断。
- `core/agent_runner/session.py`：resume 条件扩展（原地重试场景强制允许 resume）。
- `core/agent_runner/liveness.py` / `core/pm_engine/dispatch.py`：transient 终态标记写侧与 dispatch 读侧排程。
- `core/worktree_manager.py`：keep_for_reuse 通道泛化（认领判定按 agent_type 放开）。
- `core/config.py`：新配置键定义与校验。
- `core/dashboard/static/src/pages/settings/components/SystemPanel.tsx`：设置界面。
- 风险面：重试语义与秒挂熔断（instant_fail_threshold 60s 判定 attempt 存活时长）的交互、worktree 保留与 stale 清扫的协同、预算闸门死亡豁免与新闸门的叠加。
