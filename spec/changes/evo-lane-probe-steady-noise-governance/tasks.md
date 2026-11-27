## Deliverables

```yaml
- path: core/agent_runner/lane_preflight.py
  kind: modify
- path: fenixd.py
  kind: modify
- path: core/self_review.py
  kind: modify
- path: tests/test_lane_preflight_steady_noise.py
  kind: new
```

## 1. 探针稳态边沿发射

- [ ] 1.1 core/agent_runner/lane_preflight.py：探针维护上次判定结论与稳态进入时刻；结论变化（含首判）即时打 WARNING，稳态同判不再逐拍重打，改每小时 1 条携带持续时长的心跳；判定返回值与回落冻结闸拦截语义零改动。
- [ ] 1.2 fenixd.py（_lane_preflight_consume 自检消费点）：改为仅在探针侧边沿/心跳拍发射，消除同拍双组件重复行。

## 2. 告警生命周期与提醒豁免

- [ ] 2.1 core/agent_runner/lane_preflight.py（告警登记/重武装段）：人工 handled 后同一稳态不重开告警（一次性终态登记），环境形态实测变化才按新边沿重开；告警正文生命周期承诺与实际行为一致。
- [ ] 2.2 core/self_review.py（_unhandled_escalation_aging）：对负载明示自动关闭（无需人工处置）语义的告警在「超 24h 未处理」提醒中豁免或降级，豁免按负载声明字段判定而非逐类型硬编码。

## 3. 测试

- [ ] 3.1 tests/test_lane_preflight_steady_noise.py：覆盖 首判即时告警/稳态同判静默/每小时心跳恰一条/结论变化即时告警/恢复边沿播报 五个分支，并断言判定返回值与拦截语义不回归。
- [ ] 3.2 tests/test_lane_preflight_steady_noise.py：覆盖 handled 后同稳态不重开、环境形态变化重开、提醒豁免仅命中自动关闭型三个分支。