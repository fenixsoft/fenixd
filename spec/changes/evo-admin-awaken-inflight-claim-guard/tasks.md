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

- [ ] 1.1 core/admin_monitor.py：_invoke_administrator 提交段（submit 入队前）对 _has_active_admin_run_for_spec(spec) 做二次复查，命中走 _persist_skipped_disposition（mutex-skip）并 return False，保持「未送达」语义（指纹备忘回滚与巡检重评链路不改动）；复查带双前置门——仅自动通道（signal_rec 非空，invoke_manual 豁免）且 signal["spec"] 非空（spec=None 哨兵不过滤、daemon 级信号不复查，对齐 :4333/:5989/:6327/:6694 既有口径）
- [ ] 1.2 core/admin_monitor.py：新增进程内 _admin_dispatch_claimed_specs 认领集合（锁保护，键=spec、值=属主令牌）；复查与登记同锁临界区原子完成，先登记后 submit、submit 抛出即同锁回滚；复查顺序=先 pending 查询后认领集合；让位命中时按 R5 记 info 日志与命中计数
- [ ] 1.3 core/agent_runner/maintenance_runs.py：run_administrator worker 的 finally 三路（成功/失败/异常）按令牌匹配释放认领键（不匹配 no-op；人工通道与同步回退 run 未登记，MUST NOT 按键误删他属认领），worker 启动后照旧落正式 pending DISPOSITION；认领集合访问用惰导入接线（先例 runner.py:9526、maintenance_runs.py:493），MUST NOT 模块级导入防循环导入

## 2. 测试

- [ ] 2.1 tests/test_admin_awaken_claim_guard.py：并发唤起矩阵——同 spec 首 run 已启动（mutex-skip 回归）、首 run 仍在共享池队列（TOCTOU 窗认领命中被让位）、不同 spec 并行不受影响、invoke_manual 不被守卫拦截、daemon 级信号（spec=None）在他 spec 在飞 run 期间不被误让位（spec 门回归）
- [ ] 2.2 tests/test_admin_awaken_claim_guard.py：认领释放与恢复——worker 启动失败/异常退出后认领释放且后续唤起放行；人工通道 run 完成不释放他属自动认领（令牌校验）；submit 抛出后登记回滚、同步回退分支登记/释放配对；让位告警保持未送达语义、下一巡检周期自然重评