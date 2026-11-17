## Deliverables

```yaml
- path: core/pm_engine/family.py
  kind: modify
- path: core/pm_engine/arbiter.py
  kind: modify
- path: tests/test_escalation_endpoint_loop_suppression.py
  kind: new
```

## 1. 咽喉守卫

- [x] 1.1 core/pm_engine/family.py：`_send_human_escalation_alert` 直派段（约 :2154-2180）对 chain_context 非空的链终点件跳过 arbiter_lane.submit_for_alert，零后台补叙（叙事生成链已随 consolidate-alerts-to-ops-page 1.2 退役），打 INFO 级抑制日志（含签名与 alert id）

## 2. 车道入口第二道防线

- [x] 2.1 core/pm_engine/arbiter.py：submit_for_alert（约 :621-635）入口检测 entry 含 chain 字段即记录跳过日志并短路，返回否定哨兵字符串 `"excluded"`（str 签名一致，调用方 family.py:2181-2188 日志词表静默），防未来新调用点绕过咽喉

## 3. 测试

- [x] 3.1 tests/test_escalation_endpoint_loop_suppression.py：覆盖「链终点件走完升级流程不产生 submit_for_alert 调用」「链队列满回落兜底件（chain_context=None）直派不受影响」「入口直调含 chain 字段 entry 被短路」三场景