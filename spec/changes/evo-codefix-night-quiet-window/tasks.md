## Deliverables

```yaml
- path: core/code_fix.py
  kind: modify
- path: fenixd.py
  kind: modify
- path: tests/test_code_fix_night_quiet_window.py
  kind: new
```

## 1. 落地校验

- [ ] 1.1 core/code_fix.py：checkpoint() 守卫块（switch_cooldown 分支同级，约 :2935-3010）新增每日静默窗判定——读 night_quiet_window 点号键（沿 _switch_cooldown_seconds :2646 的 config 访问模式，缺省 "04:15-04:45"，空串/off 禁用），本地时刻在窗内则返回 triggered=False、reason=night_quiet_window，武装/解除告警对齐 :2301/:2341 形态，evidence 含窗区间与下一可投递时刻。
- [ ] 1.2 core/code_fix.py：静默窗与既有冷却同时命中时可投递时刻取更晚者（返回 reason 取更晚者对应守卫）、互不复位；非法配置（解析失败或 end<=start 逆序）按无窗处理并 WARNING 一次；武装/解除告警按窗次（含日期）幂等、残留标识不拦截投递；四路触发（_resubmit :3370、审查收尾激活 core/agent_runner/maintenance_runs.py:1767、event_bus 兜底 :274、持有者回调 :3643）经 checkpoint() 单点全覆盖，补注释固定该不变量。
- [ ] 1.3 fenixd.py：CODE_FIX_RESULT_MESSAGES（:3890）补 night_quiet_window 中文文案条目（手动触发回链消费方）。

## 2. 测试

- [ ] 2.1 tests/test_code_fix_night_quiet_window.py：注入本地时钟覆盖窗内拦截/窗外放行/四点边界（04:14:59、04:15:00、04:44:59、04:45:00）；与 switch_cooldown 叠加取更晚；配置关闭后行为与现状一致；非法配置降级为无窗并告警（用例含 end<=start 逆序区间）；窗内手动触发 checkpoint(override_enabled=True) 回链 reason=night_quiet_window 断言。时间注入沿 tests/test_code_fix.py:1661 既有形态 patch 模块 time 属性。