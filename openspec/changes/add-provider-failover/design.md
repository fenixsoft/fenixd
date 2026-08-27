# Design: add-provider-failover

## Context

今日故障形态：两家 provider 在同一窗口分别以 `unrecognized_model`（inferaiapi 的 deepseek-v4-flash 与 aliyun 的 deepseek-v4-flash-0731）拒绝全部请求。现有架构中：provider 分配在 `_get_agent_model_assignment` 静态取单值；熔断（fix-stashpop 引入）仅统计可解析 4xx 且冷却期"抑制派发"，无"换一家继续"的路径；run 结果与产物无 provider 记录，事后只能从 run jsonl stderr 猜。

## Goals / Non-Goals

**Goals:**
- 角色 provider 可配置为按序候选链，链上自动故障转移
- 切换类错误（unrecognized/5xx/网络）驱动链前进，4xx 配额类维持既有熔断语义不变
- 切换后仍 resume 原会话，上下文零损失
- 每次 attempt 的 provider/model 落盘可查

**Non-Goals:**
- 不做请求级/流中切换（进程启动后不换端点）
- 不做跨角色的全局负载均衡
- 不实现成本计费（仅字节/次数观测，成本视图归独立 SPEC）

## Decisions

- **D1 切换粒度 = attempt 边界。** 失败仅在 attempt 之间推进链指针（cursor 按落 (agent_type) 记忆于 runner 实例生命周期），进行中的进程不迁移。理由：流中切换意味着放弃已产出上下文与工作树状态，风险高于收益；attempt 预算独立计数（与既有模型一致）。
- **D2 错误分类扩展点。** `parse_api_error_status` 增加 `classify_switch_error()`：匹配 `unrecognized_model` 文本、HTTP 5xx、连接异常三类 → 返回 switch 标记；配额/鉴权 4xx 维持原 4xx 熔断路径。今日真实报错字符串入库为 fixture。
- **D3 链级冷却复用熔断表但键隔离。** 复用 provider_circuits 数据结构，新增 `switch_cooldown_until` 字段与独立阈值（默认 300s，可配 `pm.failover.switch_cooldown_seconds`）；避免与既有 4xx 冷却互相污染计数。链选择时跳过 switch-cooldown 未到期者；全链皆冷却 → 按现状失败返回（保持熔断抑制语义，不无限打转）。
- **D4 跨 provider resume 保留。** session_id 提取与 --resume 逻辑不变；切换 provider 时照常携带 resume 参数（CLI 会话历史在本地，消息 API 无状态）。风险：目标模型与原上下文能力差异 → 记录 switch 事件日志供审计，不做能力预检。
- **D5 观测落点。** AgentRunResult 增 `provider_used/model_used`；run jsonl 追加一行 `{"type":"provider_marker",...}`（在 attempt 启动时写入）；日志 INFO 打点 "provider switched a→b for spec"。每 provider 当日 attempt 计数超 `pm.failover.daily_attempts_warn`（默认 50）打 WARNING。

## Risks / Trade-offs

- [备份 provider 更贵] → 每日计数告警兜底；切换仅发生在主链失败时，常态零开销
- [unrecognized_model 误判（记忆：也可能是网关瞬时故障）] → 分类只触发"链前进+短冷却"，不永久拉黑；冷却到期后主链自动复位优先
- [配置错误在启动后才发现] → config loader 启动时校验链名存在性并打 ERROR 清单，但不阻塞启动（沿用热更新哲学）

## Migration Plan

配置向后兼容（str 原样单链）。daemon 重启生效；回滚 revert。无数据迁移。

## Open Questions

- 无
