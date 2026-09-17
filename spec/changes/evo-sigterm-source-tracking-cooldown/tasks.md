## Deliverables

```yaml
- path: core/agent_runner/runner.py
  kind: modify
- path: core/agent_runner/provider_circuit.py
  kind: modify
- path: tests/test_sigterm_source_tracking.py
  kind: new
```

## 1. 落地校验

- [ ] 1.1 core/agent_runner/runner.py：子进程终结捕获处按 returncode/shutting_down/产物 interrupted 标记/父进程存活反查信号来源（daemon-drain/external-kill/unknown），错误文本注入来源标签，run 产物与告警 evidence 可追溯
- [ ] 1.2 core/agent_runner/provider_circuit.py：新增信号死法（143/-9）熔断计数通道（阈值 3 + 冷却窗口，恢复自动），admin/impl/处置 run 路由覆盖，不再无限瞬态重试
- [ ] 1.3 core/agent_runner/runner.py：产物硬门格式拒绝打独立归类（不落 provider-transient 指纹，不走瞬态重试），错误文本保真透出

## 2. 测试

- [ ] 2.1 tests/test_sigterm_source_tracking.py：外部 SIGKILL/SIGTERM 死法 → 错误含信号来源标签且不归 [provider-transient]（2026-09-16 两个 admin run 回放夹具）
- [ ] 2.2 tests/test_sigterm_source_tracking.py：shutting_down/产物 interrupted → 维持 [shutdown-interrupted]（不回归既有守卫）
- [ ] 2.3 tests/test_sigterm_source_tracking.py：143/-9 连续达阈值 → 熔断冷却启动、冷却期不重试、到期自动恢复
- [ ] 2.4 tests/test_sigterm_source_tracking.py：provider 网络抖动瞬态 → 既有退避不变
- [ ] 2.5 tests/test_sigterm_source_tracking.py：产物硬门格式拒绝 → 独立归类、不污染瞬态指纹
- [ ] 2.6 回归：tests/test_provider_circuit.py、test_agent_runner.py、test_agent_runner_gate.py 通过