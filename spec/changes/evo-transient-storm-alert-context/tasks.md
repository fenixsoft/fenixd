## Deliverables

```yaml
- path: core/agent_runner/provider_circuit.py
  kind: modify
- path: core/alert_lifecycle.py
  kind: modify
- path: tests/test_transient_storm_observability.py
  kind: new
```

## 1. 失败 attempt 元信息记账

- [ ] 1.1 core/agent_runner/provider_circuit.py：瞬断记账（record_transient_error）在指纹时间戳列表基础上，同时记录每次 attempt 的 spec、run_id、provider、时间戳（窗口剔除仍按时间，行为不变）

## 2. 触发时聚合注入

- [ ] 2.1 达阈值触发全局熔断时，构建窗口内 attempt 聚合列表（run_id/spec/provider/ISO 时间）
- [ ] 2.2 ERROR 日志在 fingerprint 后追加 failed attempts 聚合清单；升级信号（transient_break_storm）上下文携带聚合清单（对指纹归一化免疫）

## 3. 熔断自然过期自动核销

- [ ] 3.1 core/alert_lifecycle.py（或既有告警落盘处）：全局熔断自然过期（dispatch resumed）时自动核销对应 transient_break_storm 告警（handled=True、核销原因「熔断自然过期」留审计）
- [ ] 3.2 核销幂等：无对应告警或已核销时零操作；不引入新告警 kind（复用既有通道）

## 4. 测试

- [ ] 4.1 tests/test_transient_storm_observability.py：覆盖触发时聚合注入（含 run_id/provider 清单）、过期自动核销（handled+审计）、重复过期幂等
- [ ] 4.2 回归：既有的瞬断熔断语义（阈值/冻结 600s/退避）测试保持全绿