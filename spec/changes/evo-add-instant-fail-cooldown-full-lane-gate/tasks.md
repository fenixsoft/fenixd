## Deliverables

```yaml
- path: core/pm_engine/dispatch/queue.py
  kind: modify
- path: core/admin_monitor.py
  kind: modify
- path: core/agent_runner/runner.py
  kind: modify
- path: core/pm_engine/dispatch/backoff.py
  kind: modify
- path: tests/test_instant_fail_cooldown_gate.py
  kind: new
```

## 1. 冷却门控面扩展

- [ ] 1.1 core/pm_engine/dispatch/queue.py：`_entry_dispatchable` 的秒挂闸门（现约 :738，仅 implementer/fast-track 查 `_instant_fail_cooled`）以常量集合扩展到 planner-plan 与 verifier 两类 atype，命中保留既有队列语义（返回 False、不 pop、不耗预算）；确认 :694/:712 两个派发入口都过闸无旁路。
- [ ] 1.2 core/pm_engine/dispatch/queue.py：秒挂闸门跳过留痕从 DEBUG 升 INFO（spec 名、被拦车道、剩余冷却秒数，参照同文件 :817-823 transient 首道闸的 INFO 先例）。
- [ ] 1.3 core/admin_monitor.py：在既有 signal-kill 冷却检查点位（约 :4829/:5144/:6122）并列加 spec 作用域的 `_instant_fail_cooled` 判定与 INFO 跳过留痕；spec=null 的全局信号唤起保持放行。
- [ ] 1.4 core/agent_runner/runner.py：修正冷却进入告警文案（约 :7884-7886）的门控面描述，与新门控面一致。

## 2. 到期复诵与冷却翻倍

- [ ] 2.1 core/agent_runner/runner.py：`_record_instant_fail`（约 :7835-7888）在 `_instant_fail[spec]` 状态增记归一化故障指纹（路径/端口/run id 归一化，对齐 daemon_errors 指纹语义）与末次失败时刻。
- [ ] 2.2 core/agent_runner/runner.py：到期清零路径（约 :7943-7960 查询侧 pop）改为先复诵后消费——末次失败时刻晚于冷却起点则不清零，连击 +1（上限 3 次）、冷却时长 min(×2, 2400s) 续写 cooldown_until，留 INFO 续冷却留痕；窗内零新失败才清零恢复。
- [ ] 2.3 core/pm_engine/dispatch/backoff.py：恢复定时器适配——`_schedule_recovery_timer_locked` 的判重早退放宽为「截止时刻变化即按新截止重排」，保证翻倍后的冷却窗有对应定时器。

## 3. 测试

- [ ] 3.1 tests/test_instant_fail_cooldown_gate.py：覆盖门控面扩展——冷却生效时 planner-plan/verifier 派发被跳过且队列不 pop、冷却到期后自动重入调度、implementer/fast-track/repair 行为不回归、admin 全局信号唤起不受门控、spec 作用域处置唤起被门控。
- [ ] 3.2 tests/test_instant_fail_cooldown_gate.py：覆盖到期复诵——窗内有新失败则翻倍且定时器按新截止重排、翻倍达 3 次/2400s 封顶、窗内零新失败正常清零恢复、续冷却留痕可断言。
- [ ] 3.3 回归 test_pm_dispatch.py、test_verify_dispatch_single_flight.py、test_admin_dispatch_dedup.py 等既有派发套件全绿，确认门控扩展不破坏既有派发时序。