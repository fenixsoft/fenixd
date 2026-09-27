# ADR-050：dashboard 数据面增量化——服务端摘要索引 + 增量广播 + 前端本地归并

date: 2026-09-09
status: accepted

## Context

150 spec 实测下，`/api/specs` 每请求对全部 spec 重算摘要（每 spec 多次独立磁盘 IO），watcher 每秒全量枚举文件并在任一日志变化时全量重组广播（payload ~100KB/次），前端 2s 轮询三端点与 SSE 叠加。规模化（万级 spec）路径全为 O(N) 每请求重算。

## Decision

- 热路径从「每请求全量重算」改为「启动惰性构建一次摘要索引 + O(变更) 增量」：索引挂在 HTTP server 实例上，watcher 与 API 共享同一实例（锁保护，单一写者）；每 spec 记录依赖文件签名集合，签名不变直接复用，变化只重算该 spec；仅 STATE.md 自身签名变化触发该项目全量重建（只有全量解析能发现 spec 增删）。
- 广播改增量语义：`state` 事件只携带变更 spec 的 `{spec, summary}`，字段可 null 表示无变化不推送；watcher 不再下发 overview。直接统一增量、不留全量兜底——前端 SPA 是唯一消费方且 dist 随仓同发布，无旧客户端存活。
- 前端本地归并：本地维护 spec 摘要表，首屏全量拉取建立，增量事件进 patch 队列（同 spec 短窗口去重只应用最新）；统计由本地表推导，30s 心跳以 `/api/overview` 校准一次，`visibilitychange` 立即校准；轮询降为 30s 心跳，SSE 增量为准。
- 资源上限内置：SSE 活跃连接与 HTTP 线程数设硬上限，超限 503，客户端退化为轮询。

## Consequences

- 广播 payload 从 ~100KB/次降至 ~1KB/次，轮询路径 CPU 降一个量级；代价是丢帧窗口由心跳校准兜底（最终一致而非实时一致）。
- 索引与真实文件的漂移风险集中在「签名集合 vs 摘要实际读路径」的对齐上，失效策略向保守倾斜（整目录纳入签名）。
- 前端成为统计口径的持有者，后端 overview 从每事件变为低频校准源；与 ADR-038 的事件架构（SSE 通道 + onEvent 增量）同族。
