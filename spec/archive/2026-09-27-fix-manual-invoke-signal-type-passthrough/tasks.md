## Deliverables

```yaml
- path: fenixd.py
  kind: modify
- path: core/admin_monitor.py
  kind: modify
- path: tests/test_manual_invoke_passthrough.py
  kind: new
```

## 1. daemon 消费侧透传

- [x] 1.1 `fenixd.py` `_check_admin_invoke_requests`：构造信号前经 `admin_store` 反查该 spec 最近一条未处置（非 handled）SIGNAL/ESCALATION 记录的 `signal_type`，写入信号 `underlying_signal_type` 字段（查不到为 None）；反查 MUST 排除 `signal_type == "manual-intervention"` 的记录（手动通道自产，含派发失败/agent_runner 不可用落的 ESCALATION），基于 `read_all()`（created 倒序）过滤实现；顶层 `signal_type` 保持 `manual-intervention`；字段写入处注释语义与消费点（admin_monitor 复位门）

## 2. 复位判定门扩展

- [x] 2.1 `core/admin_monitor.py`：处置收尾自动复位的前置检查与 `_reset_env_blocked_after_disposition` 守卫改为「`signal_type` 或 `underlying_signal_type` 任一命中 `DISPOSITION_AUTO_RESET_SIGNAL_TYPES` 即触发」；escalated 不复位、复位守卫、业务侧车字段不清零等既有语义保持不变；orphaned_state 独立复位路径不动

## 3. 测试

- [x] 3.1 新建 `tests/test_manual_invoke_passthrough.py`：存在未处置信号时透传底层类型；无可反查信号时缺省 None 不报错；存在上次手动派发失败遗留的 manual-intervention 未处置 ESCALATION 记录时反查跳过它（取真实底层类型或 None，不把 manual-intervention 当底层类型）；透传 env 族处置成功（result=resolved）命中自动复位；底层类型不在集合时不触发该路径；两次唤起 store 落痕仍按 manual-intervention、透传字段不参与节流判定
- [x] 3.2 存量回归：admin 唤起/处置相关既有测试全绿（`pytest tests/ -k "admin_invoke or disposition"` 口径自选，覆盖受影响模块）
