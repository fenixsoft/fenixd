## Deliverables

```yaml
- path: core/admin_monitor.py
  kind: modify
- path: tests/test_admin_dispatch_dedup.py
  kind: new
```

## 1. 落地校验

- [ ] 1.1 core/admin_monitor.py：daemon_errors 信号 evidence 基底补齐——`_make_daemon_error_signal`（:3948）与 `_make_daemon_error_signal_merged`（:3964）组装 evidence 时附入最近一次同指纹 ERROR 原文摘录（含组件名，截断限长）；description 的「指纹 <fp[:8]>」前缀子串不变（跨重启已知指纹对账依赖，:3968-3970 注释），`_fp`/status_hash 判据不变。
- [ ] 1.2 core/admin_monitor.py：新增 daemon 级信号 spec 归属提取——派发判定前对 spec 为空的信号从 evidence 中的 ERROR 原文摘录提取归属：实现分支名（fenix/<spec>-<时间戳> 形态）正则与 spec 名直接匹配双线索，任一命中即归属；提取不到（含 evidence 无摘录的存量形态）返回空归属且后续流程不变。
- [ ] 1.3 core/admin_monitor.py：扩展在飞互斥判定入口（现 core/admin_monitor.py:2834、:4269、:4523 三处守卫）——daemon 级信号提取到归属 spec 且该 spec 存在在飞 admin run 时跳过本次派发：信号保持未消费（不 mark handled），附「被在飞 run 覆盖、待重评」注记（_handle_signal 车道按 `_persist_skipped_disposition` result="skipped" 既有形态补写，:4275-4284）；跳过语义仅适用于具检测循环重发生命周期的 daemon 级信号类型（当前唯一 None-spec 形态为 daemon_errors）。在飞 run 终态后自然重评（检测循环重发 / 摄取循环再武装，按信号所在车道）。
- [ ] 1.4 core/admin_monitor.py：兜底与回归保护——无归属或归属 spec 无在飞 run 时走现状 1:1 派发；_make_daemon_error_signal_merged（:3964）同轮多指纹合并与既有 D2b spec 键互斥语义不动。

## 2. 测试

- [ ] 2.1 tests/test_admin_dispatch_dedup.py：evidence 基底与归属提取——升级信号 evidence 含最近一次同指纹 ERROR 原文摘录且 description 仍以「指纹 <fp[:8]>」开头（跨重启已知指纹对账不回归）；摘录含 fenix/<spec>-<时间戳> 分支名或 spec 名时可正确归属；无线索时返回空归属；提取逻辑不改写信号其余字段。
- [ ] 2.2 tests/test_admin_dispatch_dedup.py：互查跳过——归属 spec 有在飞 admin run 时 daemon 级信号被跳过、不派发新 run、信号未 handled 且注记含「待重评」；模拟在飞 run 终态后信号可重新进入派发判定。
- [ ] 2.3 tests/test_admin_dispatch_dedup.py：行为不变回归——无归属信号照常派发；同轮多指纹合并与 spec 键在飞互斥既有行为不回归；合并信号 evidence 逐指纹摘要与 `_fp` 稳定拼接判据不变。