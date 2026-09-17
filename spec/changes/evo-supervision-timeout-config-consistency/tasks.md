## Deliverables

```yaml
- path: core/config.py
  kind: modify
- path: core/agent_runner/liveness.py
  kind: modify
- path: .fenix/config.template.yaml
  kind: modify
- path: tests/test_supervision_timeout_consistency.py
  kind: new
```

## 1. 落地校验

- [ ] 1.1 core/config.py：新增统一下限派生（下限 = 生效 run_timeout + max_extensions × extension_seconds），effective_supervision_absolute_max_seconds 消费之；配置校验阶段不一致即 fail-fast 阻断（ERROR + 修正建议），取代仅告警兜底
- [ ] 1.2 core/agent_runner/liveness.py：liveness.py:777-789 兜底口径改调同一派生函数，删除手写口径常数
- [ ] 1.3 core/config.py：热更新路径同享一致性校验，不一致拒绝新配置回滚旧值；可选自动对齐（抬升 absolute_max 并持久化）
- [ ] 1.4 .fenix/config.template.yaml：absolute_max_seconds 注释对齐约束（≥ run_timeout + 续期总额）并给出示例值

## 2. 测试

- [ ] 2.1 tests/test_supervision_timeout_consistency.py：下限派生值正确（15000+2×1800=18600）
- [ ] 2.2 tests/test_supervision_timeout_consistency.py：config 校验层与 liveness 兜底层口径一致（断言相等）
- [ ] 2.3 tests/test_supervision_timeout_consistency.py：absolute_max < 下限 → 启动阻断（fail-fast）且 ERROR 含两侧值与修正建议
- [ ] 2.4 tests/test_supervision_timeout_consistency.py：热更新不一致 → 拒绝并回滚；自动对齐 → 持久化后无 ERROR
- [ ] 2.5 回归：tests/test_config.py、test_system_settings_config.py、test_liveness_hang_discrimination.py 通过