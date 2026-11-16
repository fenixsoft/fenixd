## Deliverables

```yaml
- path: core/admin_monitor.py
  kind: modify
- path: tests/test_admin_monitor_orphan_effect.py
  kind: new
```

## 1. 生效核查代际感知

- [ ] 1.1 core/admin_monitor.py：_orphan_group_effect_evidence 在 STATE 短路（frozen 即未生效）之前增加「处置组完成时刻之后该 spec 的 gate transition 推进轨迹」核查（复用既有解冻族日志家族含轮转备份，轨迹须晚于处置组完成时刻且为合法 transition）；命中判「已生效、被新代际取代」——旧处置组转记已消解，不再升级人工；轨迹缺失或日志不可用维持现行 fail-closed 升级语义零变化
- [ ] 1.2 core/admin_monitor.py：「被新代际取代」分支为当前 frozen 状态开新信号条目并携带旧处置组引用与轨迹证据行引用，保持升级链可追溯

## 2. 测试

- [ ] 2.1 tests/test_admin_monitor_orphan_effect.py：三态锚定——处置后合法前移再冻结判已生效不升级且回链新代际；处置真未生效（处置完成后无轨迹）仍升级人工；日志轮转缺失 fail-closed 仍升级