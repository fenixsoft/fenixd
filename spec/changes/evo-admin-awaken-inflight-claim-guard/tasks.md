## Deliverables

```yaml
- path: core/admin_monitor.py
  kind: modify
- path: core/agent_runner/maintenance_runs.py
  kind: modify
- path: tests/test_admin_awaken_claim_guard.py
  kind: new
```

## 1. 认领守卫落地

- [ ] 1.1 core/admin_monitor.py：_invoke_administrator 提交段（submit 入队前）对 _has_active_admin_run_for_spec(spec) 做二次复查，命中走 _persist_skipped_disposition（mutex-skip）并 return False，保持「未送达」语义（指纹备忘回滚与巡检重评链路不改动）
- [ ] 1.2 core/admin_monitor.py：新增进程内 _admin_dispatch_claimed_specs 认领集合（锁保护，键=spec），submit 成功即登记；复查顺序=先 pending 查询后认领集合；让位命中时按 R5 记 info 日志与命中计数
- [ ] 1.3 core/agent_runner/maintenance_runs.py：run_administrator worker 的 finally 三路（成功/失败/异常）释放认领键，worker 启动后照旧落正式 pending DISPOSITION

## 2. 测试

- [ ] 2.1 tests/test_admin_awaken_claim_guard.py：并发唤起矩阵——同 spec 首 run 已启动（mutex-skip 回归）、首 run 仍在共享池队列（TOCTOU 窗认领命中被让位）、不同 spec 并行不受影响、invoke_manual 不被守卫拦截
- [ ] 2.2 tests/test_admin_awaken_claim_guard.py：认领释放与恢复——worker 启动失败/异常退出后认领释放且后续唤起放行；让位告警保持未送达语义、下一巡检周期自然重评