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

- [x] 1.1 core/pm_engine/dispatch/queue.py：`_entry_dispatchable` 的秒挂闸门（现约 :738，仅 implementer/fast-track 查 `_instant_fail_cooled`）以常量集合扩展到 planner-plan 与 verifier 两类 atype，命中保留既有队列语义（返回 False、不 pop、不耗预算）；确认 :694/:712 两个派发入口都过闸无旁路。
- [x] 1.2 core/pm_engine/dispatch/queue.py：秒挂闸门跳过留痕从 DEBUG 升 INFO（spec 名、被拦车道、剩余冷却秒数，参照同文件 :817-823 transient 首道闸的 INFO 先例）。
- [x] 1.3 core/admin_monitor.py：在既有 signal-kill 冷却检查点位（约 :4829/:5144/:6122）并列加 spec 作用域的 `_instant_fail_cooled` 判定与 INFO 跳过留痕；spec=null 的全局信号唤起保持放行。
- [x] 1.4 core/agent_runner/runner.py：修正冷却进入告警文案（约 :7884-7886）与 instant_fail_storm 告警条目 description（约 :7912-7914）中的门控面描述，与新门控面一致。

## 2. 到期复诵与冷却翻倍

- [x] 2.1 core/agent_runner/runner.py：`_record_instant_fail`（约 :7835-7888）在 `_instant_fail[spec]` 状态增记归一化故障指纹（路径/端口/run id 归一化，对齐 daemon_errors 指纹语义）与末次失败时刻；并补列复诵算术所需状态字段——冷却起点（或当前冷却时长）与翻倍次数（独立计数，勿与秒挂连击 count 混用；现状态仅 count/cooldown_until 两键，runner.py:7864-7865）。
- [x] 2.2 core/agent_runner/runner.py：到期清零路径（约 :7943-7960 查询侧 pop）改为先复诵后消费——末次失败时刻晚于冷却起点则不清零，翻倍次数 +1（上限 3 次，独立于秒挂连击 count）、冷却时长 min(×2, 2400s) 续写 cooldown_until，留 INFO 续冷却留痕；窗内零新失败才清零恢复。冷却起点 = 进入/续写冷却的写入时刻，严格大于方复诵（引发本次冷却的失败批次与起点同刻，不触发复诵）。复诵的查询侧读改写（+1/×2/续写）MUST 全程持 `_instant_fail_lock` 临界区（对齐 runner.py:7856-7862 丢更新修复先例，现查询侧为无锁读）。
- [x] 2.3 core/pm_engine/dispatch/backoff.py：恢复定时器适配——共用排程器 `_schedule_recovery_timer`（backoff.py:300-301 判重早退；秒挂/信号死法两通道共用）的判重放宽为「截止时刻变化即按新截止重排」，保证翻倍后的冷却窗有对应定时器；信号死法通道既有恢复排程行为 MUST NOT 回归。

## 3. 测试

- [x] 3.1 tests/test_instant_fail_cooldown_gate.py：覆盖门控面扩展——冷却生效时 planner-plan/verifier 派发被跳过且队列不 pop、冷却到期后自动重入调度、implementer/fast-track/repair 行为不回归、admin 全局信号唤起不受门控、spec 作用域处置唤起被门控。
- [x] 3.2 tests/test_instant_fail_cooldown_gate.py：覆盖到期复诵——窗内有新失败则翻倍且定时器按新截止重排、翻倍达 3 次/2400s 封顶、窗内零新失败正常清零恢复、续冷却留痕可断言。
- [x] 3.3 回归 test_pm_dispatch.py、test_verify_dispatch_single_flight.py、test_admin_dispatch_dedup.py 等既有派发套件全绿，确认门控扩展不破坏既有派发时序；另 MUST 回归 tests/test_transient_backoff.py（§6.1 直测 _record_instant_fail 计数/重置语义，:1123-1153）与 test_verify_lane_throughput.py，并覆盖信号死法冷却恢复定时器不回归（2.3 改的是两通道共用排程器）。