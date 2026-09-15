## Deliverables

```yaml
- path: core/admin_monitor.py
  kind: modify
- path: core/config.py
  kind: modify
- path: tests/test_admin.py
  kind: modify
- path: tests/test_stuck_signal_hygiene.py
  kind: new
```

## 1. 活跃度预检

- [ ] 1.1 core/admin_monitor.py：新增 _run_process_alive（从最近 run 文件解析 agent 子进程 pid + os.kill(pid, 0) 探活；无 pid 跳过）；_detect_stuck 叠加该检查（进程存活即非 stuck）

## 2. 信号去重与静默期

- [ ] 2.1 落 signal 记录前查 latest_signal(spec, signal_type, cooldown_minutes) → 存在则不重复落记录（5 连发场景压缩为 1）
- [ ] 2.2 处置 resolved 后静默期：_detect_* 产信号前查最近 resolved 处置时间，admin.stuck_silence_minutes 内跳过
- [ ] 2.3 core/config.py：admin.stuck_silence_minutes（默认 120）

## 3. 测试

- [ ] 3.1 tests/test_stuck_signal_hygiene.py：活跃进程 + 活跃文件 → 0 误报；resolved 后静默期内不复发；真实 stuck（无进程+无文件活跃+无近期 resolved）仍产生信号
- [ ] 3.2 同 (spec, signal_type) 冷却窗口内只落 1 条信号记录；tests/test_admin.py 既有 stuck 断言回归不过即修