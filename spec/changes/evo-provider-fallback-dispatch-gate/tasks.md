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
- [ ] 1.2 core/agent_runner/runner.py：派发前置段按探针结果对回落且默认链凭据不可用的角色执行首派发冻结，维护单条告警（含角色与回落链），配置热重载使凭据可用时解除冻结

## 2. 版本白名单全车道

- [ ] 2.1 core/agent_runner/runner.py：dsh 版本白名单检查（约 :3631 前置段）覆盖 spec-review/dispute-judge 直调车道，连通预检白名单的 dispatch 族排除项同步移除，arbiter 前置闸已覆盖项保持

## 3. 测试

- [ ] 3.1 tests/test_provider_fallback_dispatch_gate.py：覆盖「回落角色首派发被拦截且告警单条」「显式链角色不受影响」「热重载凭据可用后解冻」「直调车道版本漂移被拦截」四场景