## Deliverables

```yaml
- path: core/code_fix.py
  kind: modify
- path: tests/test_code_fix_night_quiet_window.py
  kind: new
```

## 1. 落地校验

- [ ] 1.1 core/code_fix.py：checkpoint() 守卫块（switch_cooldown 分支同级，约 :2935-3010）新增每日静默窗判定——读 night_quiet_window 点号键（沿 _switch_cooldown_seconds :2646 的 config 访问模式，缺省 "04:15-04:45"，空串/off 禁用），本地时刻在窗内则返回 triggered=False、reason=night_quiet_window，武装/解除告警对齐 :2301/:2341 形态，evidence 含窗区间与下一可投递时刻。
- [ ] 1.2 core/code_fix.py：静默窗与既有冷却同时命中时可投递时刻取更晚者、互不复位；配置解析失败按无窗处理并 WARNING 一次；三路触发（_resubmit、event_bus 兜底、持有者回调）经 checkpoint() 单点全覆盖，补注释固定该不变量。

## 2. 测试

- [ ] 2.1 tests/test_code_fix_night_quiet_window.py：注入本地时钟覆盖窗内拦截/窗外放行/四点边界（04:14:59、04:15:00、04:44:59、04:45:00）；与 switch_cooldown 叠加取更晚；配置关闭后行为与现状一致；非法配置降级为无窗并告警。