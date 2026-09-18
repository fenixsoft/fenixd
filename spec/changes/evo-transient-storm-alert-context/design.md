# Design: transient-storm-alert-context

## D1: attempt 元信息记账

core/agent_runner/provider_circuit.py `record_transient_error`：

```python
class TransientAttempt:
    spec: str
    run_id: str
    provider: str
    at: float

# 记账：self._transient_break_events[fingerprint] 现为时间戳列表，
# 扩展为 TransientAttempt 列表（时间用于滑窗剔除、元信息用于聚合）
```

窗口滑出仍按时间戳剔除（行为不变）；元信息随事件保留。

## D2: 触发时聚合注入

达阈值触发全局熔断（provider_circuit.py 熔断触发处）时：

1. 构建窗口内 attempt 聚合列表：`[{"run_id": ..., "spec": ..., "provider": ..., "at": <ISO>}]`（滑窗保活事件）
2. ERROR 日志追加：`failed attempts: [...]`
3. 升级信号上下文（transient_break_storm）的 evidence/description 追加聚合列表

聚合对 fingerprint 归一化免疫：即使指纹只剩 `<model>`，清单仍列出真实 provider/run_id。

## D3: 过期自动核销

全局熔断过期处理（provider_circuit `is_global_transient_break` 冷却清零处 / 过期事件分发处）：

1. 调用告警核销入口（alert lifecycle）：定位 signal_type=transient_break_storm 且时间域匹配本次熔断的告警
2. 标记 handled=True、写入核销审计（reason=熔断自然过期 + 聚合清单摘要）
3. 幂等：找不到对应告警/已核销 → 静默跳过

## D4: 测试策略

tests/test_transient_storm_observability.py：
- 注入聚合：mock 窗口事件 → 断言触发日志与告警上下文含 run_id/provider 清单
- 自动核销：mock 过期 → 断言告警 handled=True + 审计记录；重复过期幂等
- 未达阈值不触发（既有语义回归）