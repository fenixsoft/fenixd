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

- [ ] 1.1 core/pm_engine/family.py：`_send_human_escalation_alert` 直派段（约 :1788-1832）对 chain_context 非空的链终点件跳过 arbiter_lane.submit_for_alert，保留 narrative 补叙（链终点件降级为零补叙或仅 narrative），打 INFO 级抑制日志（含签名与 alert id）

## 2. 车道入口第二道防线

- [ ] 2.1 core/pm_engine/arbiter.py：submit_for_alert（约 :550-565）入口检测 entry 含 chain 字段即记录跳过日志并短路返回，防未来新调用点绕过咽喉

## 3. 测试

- [ ] 3.1 tests/test_escalation_endpoint_loop_suppression.py：覆盖「链终点件走完升级流程不产生 submit_for_alert 调用」「链队列满回落兜底件（chain_context=None）直派不受影响」「入口直调含 chain 字段 entry 被短路」三场景