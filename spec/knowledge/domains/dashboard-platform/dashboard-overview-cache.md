# /api/overview 结果缓存

<!-- knowledge: capability=dashboard-overview-cache rev=1
     sources=spec/archive/2026-10-07-add-alerts-archive-and-overview-cache -->

overview 读端点的结果级缓存：TTL 与数据源签名双键取或，签名未变的重复请求（2s SSE 心跳驱动的概览页重拉）不再重复执行跨项目聚合。

## 规则

- 单槽结果缓存：`/api/overview` handler 维护全局单槽缓存 `{签名, 项目集合键, 计算时刻, 响应载荷}`——响应无 project 参数维度，单槽足够，不用多槽/LRU。
- 命中条件取或：缓存未过 TTL（≥2s，与 `REFRESH_HEARTBEAT` 对齐）**或**全部注册项目数据源签名未变，任一满足即直接返回缓存结果、不执行 `project_summary` 聚合；两条件皆不满足才重算并更新缓存（含计算时刻的项目集合与各项目签名）。
- 签名键复用既有 `(path, mtime_ns, size)` 失效键模式（单文件签名单点 + runs 按 spec 分组签名），不引入第二套扫描；`hosting_state` 等动态源不入签名，由 TTL 窗口兜底。
- 项目集合变化（新项目注册/项目移除）按集合变化失效缓存，响应包含/不含对应项目。
- 数据变化生效时机：TTL 窗口内的陈旧与 `REFRESH_HEARTBEAT` 心跳节奏同量级；缓存已过 TTL 后的首个请求即反映新状态。
- 响应结构不变，纯缓存加速，调用方零感知。
- 线程安全：缓存读写用简单锁防写撕裂；读竞态最坏多算一次聚合，无正确性风险。
- 范围边界：结果缓存只挂 `/api/overview`；其它读端点不加结果缓存（`/api/specs` 等已有 SummaryIndex 增量缓存）。

## 关键行为

- 2s 内连续多次请求（无数据变化）：仅首次执行聚合，各次响应内容一致。
- 缓存已过 TTL 但全部项目数据源签名未变：直接复用缓存结果，不重算聚合。
- 任一项目数据源签名变化且缓存已过 TTL：重新执行聚合，响应反映新状态。

## 溯源

- 2026-10-07 add-alerts-archive-and-overview-cache（spec/archive/2026-10-07-add-alerts-archive-and-overview-cache） — 新增 `/api/overview` 结果级「TTL 或签名」双键单槽缓存
