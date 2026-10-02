<!-- knowledge: capability=provider-fault-fuse rev=1 sources=spec/archive/2026-09-02-fix-stashpop-deadlock-and-provider-fuse -->

# provider 故障熔断（4xx 滚动窗口熔断）

对持续返回 4xx 的 provider 做熔断保护：快速失败、不计 spec 重试、冷却后半开探针自动恢复。

## 规则

- agent_runner 对同一 provider 维护熔断状态：滚动窗口（默认 5 分钟）内累计 HTTP 4xx（400/401/404）达阈值（默认 3 次）即标记 `circuit_open`，进入冷却期（默认 30 分钟）；窗口/阈值/冷却时长为代码常量或可配置项。
- 熔断期间任何需要该 provider 的派发（implementer/verifier/planner，拦截与放行口径一致）直接返回明确错误（`provider circuit open: <name> (HTTP <code> x <count>)`，含冷却剩余时间或到期时间），不再启动 claude 进程。
- 熔断期失败不计入 spec 的 `_retry_count` / `_merge_streak`，不触发状态机回到 ready（spec 保持当前状态），不产生新 worktree / autostash——避免故障窗口内反复重派与现场积累。
- 冷却期结束后首个派发尝试作为半开探针：网关返回 200 → 闭合熔断（circuit closed）并正常执行；仍 4xx → 重新进入冷却期继续拦截。
- 5xx 与网络错误不触发本熔断，按瞬断退避与链切换语义处理（见 [provider-transient-backoff](provider-transient-backoff.md)）。
- 故障可见性：spec 的 error 字段、admin_monitor 告警、dashboard 运行错误列均能区分「provider 熔断（含 name、HTTP code、次数）」与「spec 自身实现问题」，便于人工判断是充值/换模型还是修代码。

## 溯源

- 史前复原 — 迁移期已存在的基线：provider 4xx 类故障触发熔断：熔断期请求快速失败并计次，verifier/planner 侧拦截与放行口径一致
- 2026-09-02 fix-stashpop-deadlock-and-provider-fuse（spec/archive/2026-09-02-fix-stashpop-deadlock-and-provider-fuse） — 固化滚动窗口阈值与冷却参数、熔断期派发失败不计 spec 重试不回状态、半开探针自动恢复与三通道故障可见性契约
