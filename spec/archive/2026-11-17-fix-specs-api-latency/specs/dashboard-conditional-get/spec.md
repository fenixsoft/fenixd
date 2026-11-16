## MODIFIED Requirements

### Requirement: 读端点数据源签名

dashboard 为 GET 读端点维护每响应的 ETag，取值为该响应所依赖数据源的签名哈希：签名由数据源文件的 `(mtime_ns, size)` 组合廉价计算（复用 `_RUN_TASK_CACHE`/SummaryIndex 同款失效键模式，不得引入第二套全量扫描）。签名计算成本 MUST 显著低于响应体序列化成本。

覆盖端点及其签名源（下表为基线；实现 MUST 以「响应实际依赖的数据源全集」为准——响应还依赖的其他数据源（如 runs 目录、registry 项目清单）MUST 一并纳入签名，宁多勿漏（与 SummaryIndex 自身签名先例同纪律），禁止不完整签名造成假 304；依赖进程探针的（daemon 健康/托管态），探针的 TTL memo 结果直接参与哈希输入；无法廉价纳入的端点 MUST NOT 挂 ETag，宁缺 304 不假 304）：
- `/api/overview`：全部注册项目的 STATE.md + spec 目录 + runs 目录签名聚合，叠加 registry 项目清单与 daemon/托管态探针 memo 值。
- `/api/specs?project=X`：签名由 `SummaryIndex.get_with_signature()` 在取数同趟产出（STATE.md + 归档清单 + runs 目录 + 全 spec 依赖签名的聚合哈希，结构与 `invalidation_signature` 同构同源），并与 page/page_size 原始 query 值拼装的稳定串组合为最终 ETag——翻页变体不得共享同一 ETag；签名与响应体出自同一次扫描（同趟原子），签名计算零额外 stat（复用取数轮已驻留内存的 per-spec 签名）。
- `/api/specs/<spec>`（详情，regex 路由）：项目 X 的 STATE.md 条目 + spec 目录（docs/report/verdict/run-result）+ runs（含归档）+ 时间轴日志源签名。
- `/api/admin-activities`（含 `?project=`）：各项目 `admin_alerts.json` 签名聚合。
- `/api/alerts`（含 `?project=`）：同上。
- `/api/config`（含 `?project=`）：对应 config.yaml（用户与项目配置源）签名。

#### Scenario: 签名随数据源变化

- **WHEN** 项目 X 的 STATE.md 被 daemon 写入（mtime_ns 变化）
- **THEN** 下一次 `/api/specs?project=X` 计算出的 ETag 与写入前不同

#### Scenario: 运行态数据源变化不假 304

- **WHEN** 项目 X 的 runs 目录新增 run 记录（如新派发一次实现 run），STATE.md 未变
- **THEN** 下一次 `/api/overview` 计算出的 ETag 与写入前不同（active_runs 等 runs 依赖纳入签名，不返回陈旧概览）

#### Scenario: 签名计算不触发全量扫描

- **WHEN** 同一秒内对 `/api/overview` 连续发起 10 次无条件请求
- **THEN** 服务端签名计算复用缓存（失效键未变时不重扫 spec 目录），总耗时与单次同量级

#### Scenario: 同趟聚合与独立签名同构一致

- **WHEN** 同一磁盘状态下分别计算 `get_with_signature()` 的聚合签名与 `invalidation_signature()` 的独立签名
- **THEN** 两者逐字节等值（一致性守卫测试锚定，防两套 combine 结构漂移造成假 304）

### Requirement: 条件请求协商

GET 读端点在请求携带 `If-None-Match` 且其值与当前 ETag 一致时，返回 HTTP 304 空体（附当前 ETag 响应头）；不一致或未携带时返回 200 全量响应体（附当前 ETag 响应头）。协商判断发生在响应体序列化之前——304 路径不得序列化响应体。

协商实现通道按端点分两型：
- **表驱动型**（默认）：304 短路在 `_dispatch_table` 实现、发生在 route handler 调用之前（兼容 `_api_config_get` 等自写响应的自含 handler——等返回值再拦截对它们无效）；200 路径 `_json` 发头前按签名上下文复核一次，两趟读取间隙内数据已变化的丢弃 ETag（宁缺 304 不假 304）。适用：`/api/overview`、`/api/specs/<spec>`、`/api/admin-activities`、`/api/alerts`、`/api/config`。
- **取数同趟型**（`/api/specs` 例外）：协商内联在 handler 内完成——handler 先 `get_with_signature()` 取数并得同趟签名，再以 `_if_none_match_hit` 内联判定：命中 → `_write_304` 空体（不序列化响应体）；未命中 → `_json` 200 全量体附 ETag。因签名与体出自同一次扫描（同趟原子），该端点无「两趟间隙」缺陷面，表驱动通道的发头前复核对其不适用；304 命中路径同时完成索引取数（预热缓存）。签名不可得（`get_with_signature` 返回 None）时降级为无条件 200 路径（不协商、不挂 ETag 头），与 `_route_etag` 降级纪律同构。

#### Scenario: 未变数据命中 304

- **WHEN** 客户端携带 `If-None-Match: "<etag>"` 请求 `/api/admin-activities`，且期间 `admin_alerts.json` 未变化
- **THEN** 返回 304，响应体为空，传输量 ≤1KB

#### Scenario: 数据变化后返回 200 全量

- **WHEN** 客户端携带旧 ETag 请求，但项目数据源已变化
- **THEN** 返回 200 与完整响应体，`ETag` 头为新值

#### Scenario: 无条件请求不受影响

- **WHEN** curl 不带 `If-None-Match` 直接请求任一覆盖端点
- **THEN** 行为与改造前完全一致（200 全量体），仅新增 `ETag` 响应头

#### Scenario: specs 端点同趟协商命中 304

- **WHEN** 客户端携带上一响应的 ETag 请求 `/api/specs?project=X` 且数据未变
- **THEN** handler 内联协商命中，返回 304 空体（附当前 ETag），单趟完成（无独立预扫描）

#### Scenario: specs 端点翻页变体不共享 ETag

- **WHEN** 同一数据状态下分别请求 `/api/specs?project=X` 与 `/api/specs?project=X&page=1&page_size=200`
- **THEN** 两者 ETag 不同（page/page_size 原始值参与最终 ETag 组合）

#### Scenario: specs 端点签名不可得降级

- **WHEN** 项目 X 的 STATE.md 在请求期间不可读（签名组件缺失，`get_with_signature` 返回 None 签名）
- **THEN** 响应降级为无条件 200 全量体（不挂 ETag 头、不协商），列表数据仍正常返回
