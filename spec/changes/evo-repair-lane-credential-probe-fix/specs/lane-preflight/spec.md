# 能力规格：车道前置探针凭据判定与告警升级

## 需求

1. 凭据注入：daemon 运行环境对 repair 回落链可判定——项目 .fenix/systemd.env 追加 ANTHROPIC_BASE_URL 与 ANTHROPIC_AUTH_TOKEN（对齐工作车道 provider 链），重启后 /proc/<pid>/environ 出现 ANTHROPIC_* 键，探针判定转 healthy。
2. 探针降级试呼：lane_preflight 的 env 三键嗅探结果为 indeterminable 时，按 TTL 缓存（30 分钟）降级执行一次 CLI 短请求试呼：成功判 healthy、失败判 unhealthy 且 evidence 附试呼错误尾部；缓存命中期内不重复试呼（避免探针自身烧钱/触发限流）；「纯本地检查不发 API 请求」设计注释同步修订为「默认纯本地、嗅探不可判定时按 TTL 降级试呼」。
3. 告警话术条件化：同 dedup_key 告警存在且创建时刻超 24 小时（复用 UNHANDLED_ESCALATION_AGING_HOURS 口径）时，recommended_action 由「随恢复自动关闭、无需人工处置」改为「需人工升级：repair 回落链凭据不可判定已超 24 小时」；未超时不改。

## 验收

- 注入凭据并重启 daemon 后，lane_env_unavailable 告警随探针 healthy 自动关闭，日志 unhealthy 刷屏停止。
- env 三键全空的测试环境下，探针触发且仅触发一次试呼（缓存生效），试呼结果正确映射 healthy/unhealthy。
- 人为构造超 24 小时未处理告警时，recommended_action 含「需人工升级」。