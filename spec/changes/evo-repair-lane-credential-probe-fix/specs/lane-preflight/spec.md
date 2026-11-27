# 能力规格：车道前置探针凭据判定与告警升级

## 需求

1. 凭据注入：daemon 运行环境对 repair 回落链可判定——按病灶项目清单注入（fenixd 本项目 .fenix/systemd.env 已有 10 个 ANTHROPIC_* 键活体在位，无需动作）：fenix-desktop .fenix/systemd.env 追加 ANTHROPIC_BASE_URL 与 ANTHROPIC_AUTH_TOKEN（对齐工作车道 provider 链，env 稿在场）；dsh-plugins 先落 env 稿并确认 systemd 单元 EnvironmentFile 引用在位后同款注入，引用不在位则按 design 风险段回退为探针 unhealthy 话术提示。重启后各该 daemon /proc/<pid>/environ 出现 ANTHROPIC_* 键，探针判定转 healthy。
2. 探针降级试呼：lane_preflight 的 env 三键嗅探结果为 indeterminable 时，按 TTL 缓存（30 分钟，进程级共享单例——回落冻结闸 300s 重探、daemon 60s 周期 tick、启动自检三类消费方共享，全进程每 30 分钟至多一次）降级执行一次 CLI 短请求试呼：成功判 healthy、失败判 unhealthy 且 evidence 附试呼错误尾部；试呼带短超时（复用 PROBE_HEALTH_TIMEOUT_S 口径），超时/异常按 unhealthy fail-open，MUST NOT 无界阻塞回落冻结闸派发入口；缓存命中期内不重复试呼（避免探针自身烧钱/触发限流）；「纯本地检查不发 API 请求」设计注释同步修订为「默认纯本地、嗅探不可判定时按 TTL 降级试呼」（修订仅限默认链语义，显式链角色本地解析仍不发 API 请求）。
3. 告警话术条件化：同 dedup_key 告警存在且创建时刻超 24 小时（复用 UNHANDLED_ESCALATION_AGING_HOURS 口径）时，recommended_action 由「随恢复自动关闭、无需人工处置」改为「需人工升级：repair 回落链凭据不可判定已超 24 小时」；未超时不改。写入经 AdminStore update 就地改写（append_if_absent 单发语义零写跳过不更新既有条目），幂等。

## 验收

- 病灶项目（fenix-desktop；dsh-plugins 视 systemd 单元引用在位与否）注入凭据并重启 daemon 后，lane_env_unavailable 告警随探针 healthy 自动关闭，日志 unhealthy 刷屏停止（fenixd 本项目凭据已在位，以探针持续 healthy 复核）。
- env 三键全空的测试环境下，探针触发且仅触发一次试呼（缓存生效），试呼结果正确映射 healthy/unhealthy。
- 人为构造超 24 小时未处理告警时，recommended_action 含「需人工升级」。