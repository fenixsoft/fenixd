## Deliverables

```yaml
- path: core/agent_runner/lane_preflight.py
  kind: modify
- path: tests/test_lane_preflight_credential_probe.py
  kind: new
```

## 1. 止血与探针治本

- [ ] 1.1 向项目 .fenix/systemd.env 追加 ANTHROPIC_BASE_URL 与 ANTHROPIC_AUTH_TOKEN（取值对齐工作车道 provider 链），systemd 重载并重启 daemon，验收以 /proc/<pid>/environ 出现 ANTHROPIC_* 键为准（机制通道 fenixd.py systemd_env 写入已存在，denylist 不拦 ANTHROPIC_* 前缀）
- [ ] 1.2 core/agent_runner/lane_preflight.py：env 三键（ANTHROPIC_BASE_URL/AUTH_TOKEN/API_KEY）嗅探 indeterminable 时按 30 分钟 TTL 缓存降级执行一次 CLI 短请求试呼判定，成功判 healthy、失败判 unhealthy 且 evidence 附试呼错误尾部，缓存命中期内不重复试呼；同步把「纯本地检查不发 API 请求」「MUST NOT 真发 API 请求」设计注释修订为「默认纯本地、嗅探不可判定时按 TTL 降级试呼」
- [ ] 1.3 core/agent_runner/lane_preflight.py：ensure_lane_env_alert 对同 dedup_key 已存在且创建时刻超 24 小时（复用 UNHANDLED_ESCALATION_AGING_HOURS 口径）的未处理告警，把 recommended_action 由「随恢复自动关闭、无需人工处置」切换为「需人工升级：repair 回落链凭据不可判定已超 24 小时」，未超时不改

## 2. 测试

- [ ] 2.1 tests/test_lane_preflight_credential_probe.py：覆盖 env 三键全空时触发且仅触发一次试呼（TTL 缓存生效）、试呼成功映射 healthy 与失败映射 unhealthy 且 evidence 含错误尾部、告警创建超 24 小时时 recommended_action 含「需人工升级」而未超时保持原文