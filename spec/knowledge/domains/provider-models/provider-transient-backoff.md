<!-- knowledge: capability=provider-transient-backoff rev=1 sources=spec/archive/2026-09-13-fix-provider-transient-backoff -->

# 瞬时故障原地退避与同现场续跑

瞬断类失败先在同一 provider 上按退避表原地重试，预算耗尽才换链；全程保留 worktree 现场。

## 规则

- attempt 失败命中瞬断类错误（5xx / 超时 / 连接类等；`unrecognized_model` 例外，走确定性模型链 failover，见 [model-chain-health-probe](model-chain-health-probe.md)）时，先消耗原地重试预算：不递增 attempt 计数、不触发该 provider 的 switch 冷却、不改变 chain_cursor。
- 原地重试流程：写入 `transient_retry` 事件（含退避秒数与重试序号）→ 按 `agents.transient_backoff_schedule` 下一档秒数退避 → 以同一 provider 重跑该 attempt（新 run_id 后缀 `r{n}`、独立产物文件）；上一产物可提取 session_id 时以 `--resume` 续跑原会话。
- 原地预算耗尽（连续原地重试达到 schedule 长度，缺省 3 档）后转链推进：该 provider 进入 switch 冷却（300s）、chain_cursor 前进，下一 provider 以同一 worktree 新会话（无 `--resume`）发起。
- resume 死 session 兜底：`--resume` 后进程秒挂且错误含 `No conversation found with session ID` 时，清除该 session_id 以全新会话重试（不递增 attempt 计数）；连续 2 次 resume 失败后，本次 attempt 剩余重试全部改用全新会话。
- attempt 间现场保留适用于全部 agent_type：仍有重试额度（attempt 或原地重试）时保留 worktree（含其中 dev-server），下个 attempt/子重试复用同一目录与分支；无重试额度时按终态规则处置。
- 瞬断终态失败保留现场：run 以 error 终态且错误为瞬断类时，worktree 以 `keep_for_reuse` 登记为复用遗产（替代 `cleanup(success=False)`），后续派发经 `_take_reusable_worktree` 认领同一目录与分支并继承现场，长期无人认领由 `cleanup_stale_worktrees` 兜底；非瞬断终态失败维持现行清理行为。

## 溯源

- [2026-09-13 fix-provider-transient-backoff](spec/archive/2026-09-13-fix-provider-transient-backoff/) — 建立原地退避优先于换链的重试序、resume 死 session 兜底、全 agent_type 的 attempt 间现场保留与瞬断终态 keep_for_reuse 遗产登记
