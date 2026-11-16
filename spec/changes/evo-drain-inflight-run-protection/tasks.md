## Deliverables

```yaml
- path: core/config.py
  kind: modify
- path: core/agent_runner/runner.py
  kind: modify
- path: core/agent_runner/maintenance_runs.py
  kind: modify
- path: core/admin_monitor.py
  kind: modify
- path: tests/test_drain_inflight_run_protection.py
  kind: new
- path: bin/fenixd_supervisor.py
  kind: reference
```

## 1. 排水窗扩容与一致性告警

- [ ] 1.1 core/config.py：agents.run_drain_max_seconds 缺省 60→300；按 :2424-2432 实际夹紧口径联动调整 admin.shutdown_drain_seconds 缺省/回退路径，使缺省部署有效排水窗≥300；在配置一致性校验段（:1375-1388 一带）追加分支：按同口径推导有效排水窗，低于申报值时输出含两个原始值与推导值的显式告警，不阻断启动。
- [ ] 1.2 bin/fenixd_supervisor.py：核对 SIGKILL 等待（shutdown+120，:158 一带）确实读取 admin.shutdown_drain_seconds 配置值——若为读取则无需改动、仅在 design 留对账说明；若存在硬编码则改为读配置。

## 2. code-review 车道响应重启旗标

- [ ] 2.1 core/agent_runner/maintenance_runs.py：code-review run 波次循环在每波次边界读取 broadcast_restart_checkpoint（core/agent_runner/runner.py:10249）落位的旗标文件；置位时完成当前波次（分片落盘+终态抢救文件写毕）后退出，不再开启下一波次。
- [ ] 2.2 core/agent_runner/runner.py：从 broadcast 侧导出旗标路径常量/读取 helper 单源，避免广播与读取两处字面路径漂移。

## 3. writeoff 锚即时续审

- [ ] 3.1 core/admin_monitor.py：把 writeoff 锚检查（现嵌每日周期函数，:2194-2325）抽成独立可周期调用的方法，挂接到 AdminMonitor 既有 5 分钟 tick；命中未核销锚即派发剃余续审；绕过 last_run_date 同日闸（:2100）的条件限定为「writeoff 锚在册」；保留夜窗顺延与既有单飞/互斥闸（:1741-1766 骨架）。
- [ ] 3.2 core/agent_runner/maintenance_runs.py：续审 run 的档案注记 reason 由硬编码 429 ratelimit（:2798）改为 writeoff_resume，与 core/admin_monitor.py:2260 对账键一致。

## 4. 测试

- [ ] 4.1 tests/test_drain_inflight_run_protection.py：覆盖①一致性门告警（shutdown=0 场景推导值告警留痕、不阻断）；②旗标置位后波次收尾退出、未置位时继续下一波次；③锚在册时周期扫描派发续审且绕过同日闸、锚核销后不再派发；④续审注记 reason=writeoff_resume。