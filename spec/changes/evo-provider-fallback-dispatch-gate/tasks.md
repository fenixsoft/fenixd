## Deliverables

```yaml
- path: core/agent_runner/lane_preflight.py
  kind: modify
- path: core/agent_runner/runner.py
  kind: modify
- path: tests/test_provider_fallback_dispatch_gate.py
  kind: new
```

## 1. 回落角色预检与派发冻结

- [ ] 1.1 core/agent_runner/lane_preflight.py：probe② 对「未分配显式链」角色按 harness 默认链做凭据可判定性检查，结果带 fallback 标记输出，无法判定时输出明确结果而非静默跳过；显式链角色探针行为不变
- [ ] 1.2 core/agent_runner/runner.py：在 `_run_agent` 共享 spawn 前置段（覆盖 arbiter/repair 直调车道等不经 `_execute_agent` 的路径，runner.py:2111/:3228）按探针结果对回落且默认链凭据不可用的角色执行首派发冻结（冻结角色范围与探针角色集一致），维护单条告警（含角色与回落链，按角色去重），配置热重载使凭据可用时解除冻结

## 2. 版本白名单全车道

- [ ] 2.1 core/agent_runner/runner.py：dsh 版本前置检查（check_health，检查逻辑复用不新写）挂 `_run_agent` 共享 spawn 前置段，覆盖 spec-review/dispute-judge 直调车道（结论按 adapter 级缓存复用，不逐 spawn 起子进程）；DNS 连通预检白名单（_DISPATCH_PROBE_LANES）的 dispatch 族排除维持不变；arbiter 前置闸已覆盖项保持
- [ ] 2.2 core/agent_runner/runner.py：显式放行配置项兜底（design Risks 承诺的误判兜底）——config 键经 ConfigLoader.get 点号键读取（无需改 config schema），冻结闸消费该键对回落派发放行

## 3. 测试

- [ ] 3.1 tests/test_provider_fallback_dispatch_gate.py：覆盖「回落角色首派发被拦截且告警单条」「显式链角色不受影响」「热重载凭据可用后解冻」「直调车道版本漂移被拦截」「放行配置项旁路」五场景
- [ ] 3.2 回归保护断言：dispatch 族 DNS 连通预检排除行为不变（_DISPATCH_PROBE_LANES 不扩）、维护车道连通预检行为不变、合法回落语义保留（D3 修订仅拦不可判定回落，回落到可用链仍放行）