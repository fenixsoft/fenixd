## ADDED Requirements

### Requirement: overview 结果缓存

`/api/overview` handler 维护单槽结果缓存：命中条件为「缓存未过期（TTL ≥2s，与 `REFRESH_HEARTBEAT` 对齐）**或**全部注册项目数据源签名未变」。命中时直接返回缓存结果，不执行 `project_summary` 聚合；未命中时重算并更新缓存（含计算时刻的项目集合与各项目签名）。签名键复用既有 `(path, mtime_ns, size)` 失效键模式，不引入第二套扫描。响应结构不变（纯缓存加速，调用方零感知）。

#### Scenario: TTL 窗口内命中

- **WHEN** 2s 内对 `/api/overview` 连续发起 3 次请求（无任何数据变化）
- **THEN** 仅第 1 次执行聚合计算，3 次响应内容一致，第 2/3 次服务端耗时 ≤5ms

#### Scenario: TTL 过期但签名未变

- **WHEN** 缓存已过 TTL（>2s）但全部项目数据源签名未变，请求到达
- **THEN** 直接复用缓存结果（不重算聚合），响应与上次一致

#### Scenario: 数据变化后过期失效

- **WHEN** 任一项目 STATE.md 变化（签名改变）且缓存已过 TTL，请求到达
- **THEN** 重新执行聚合，响应反映新状态（TTL 窗口内的陈旧与 `REFRESH_HEARTBEAT` 心跳节奏同量级，超 TTL 后首个请求即反映新状态）

#### Scenario: 项目集合变化

- **WHEN** 新项目注册或项目被移除后请求到达
- **THEN** 缓存按项目集合变化失效，响应包含/不含对应项目
