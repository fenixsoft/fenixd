## Deliverables

```yaml
- path: core/agent_runner/lane_preflight.py
  kind: modify
- path: tests/test_lane_preflight_credential_probe.py
  kind: new
```

## 1. 止血与探针治本

- [ ] 1.1 止血注入（按项目清单，勿落在 fenixd 本项目上假绿）：fenix-desktop .fenix/systemd.env 追加 ANTHROPIC_BASE_URL 与 ANTHROPIC_AUTH_TOKEN（取值对齐工作车道 provider 链；env 稿在场，追加后 systemd 重载并重启该 daemon）；dsh-plugins 先落 .fenix/systemd.env 稿并确认 systemd 单元 EnvironmentFile 引用在位后同款注入，引用不在位则按 design 风险段回退为探针 unhealthy 话术提示（不阻断）；fenixd 本项目 .fenix/systemd.env 已有 10 个 ANTHROPIC_* 键活体在位，无需动作。验收以各该 daemon /proc/<pid>/environ 出现 ANTHROPIC_* 键为准（机制通道 fenixd.py systemd.env 幂等追加先例已存在，denylist 不拦 ANTHROPIC_* 前缀）
- [ ] 1.2 core/agent_runner/lane_preflight.py：env 三键（ANTHROPIC_BASE_URL/AUTH_TOKEN/API_KEY）嗅探 indeterminable 时按 30 分钟 TTL 缓存降级执行一次 CLI 短请求试呼判定，成功判 healthy、失败判 unhealthy 且 evidence 附试呼错误尾部，缓存命中期内不重复试呼。约定：①试呼 TTL 缓存 MUST 为进程级共享单例（模块级）——消费方有三处且各持独立 LanePreflightCache 实例：回落冻结闸 TTL 过期同步重探（runner.py:7068 get_or_probe，闸 TTL 300s）、daemon 60s 周期 tick（fenixd.py:1362）、启动自检（fenixd.py:1342），共享单例保证全进程每 30 分钟至多一次试呼，否则闸 300s 节拍使试呼频率 6 倍于设计意图；②试呼 MUST 带短超时（复用 PROBE_HEALTH_TIMEOUT_S 口径），超时/异常按 unhealthy + evidence 错误尾部 fail-open，MUST NOT 无界阻塞回落冻结闸派发入口；③同步把「纯本地检查不发 API 请求」「MUST NOT 真发 API 请求」设计注释修订为「默认纯本地、嗅探不可判定时按 TTL 降级试呼」——修订仅限默认链（probe_default_chain_credentials）语义，probe_lane_health ②级显式链角色本地解析仍保持不发 API 请求约束不变
- [ ] 1.3 core/agent_runner/lane_preflight.py：ensure_lane_env_alert 对同 dedup_key 已存在且创建时刻超 24 小时（复用 UNHANDLED_ESCALATION_AGING_HOURS 口径）的未处理告警，把 recommended_action 由「随恢复自动关闭、无需人工处置」切换为「需人工升级：repair 回落链凭据不可判定已超 24 小时」，未超时不改。写入路径注意：append_if_absent 命中在案未处理条目即零写跳过（单发语义），不会更新既有条目——话术切换须按 dedup_key 定位未处理条目经 AdminStore update 就地改写（幂等，超 24h 后重复 tick 不重复改写/计数）

## 2. 测试

- [ ] 2.1 tests/test_lane_preflight_credential_probe.py：覆盖 env 三键全空时触发且仅触发一次试呼（TTL 缓存生效）、试呼成功映射 healthy 与失败映射 unhealthy 且 evidence 含错误尾部、告警创建超 24 小时时 recommended_action 含「需人工升级」而未超时保持原文