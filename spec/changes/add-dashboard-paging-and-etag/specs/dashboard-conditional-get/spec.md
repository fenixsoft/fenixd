## ADDED Requirements

### Requirement: 读端点数据源签名

dashboard 为 GET 读端点维护每响应的 ETag，取值为该响应所依赖数据源的签名哈希：签名由数据源文件的 `(mtime_ns, size)` 组合廉价计算（复用 `_RUN_TASK_CACHE`/SummaryIndex 同款失效键模式，不得引入第二套全量扫描）。签名计算成本 MUST 显著低于响应体序列化成本。

覆盖端点及其签名源（下表为基线；实现 MUST 以「响应实际依赖的数据源全集」为准——响应还依赖的其他数据源（如 runs 目录、registry 项目清单）MUST 一并纳入签名，宁多勿漏（与 SummaryIndex 自身签名先例同纪律），禁止不完整签名造成假 304；依赖进程探针的（daemon 健康/托管态），探针的 TTL memo 结果直接参与哈希输入；无法廉价纳入的端点 MUST NOT 挂 ETag，宁缺 304 不假 304）：
- `/api/overview`：全部注册项目的 STATE.md + spec 目录 + runs 目录签名聚合，叠加 registry 项目清单与 daemon/托管态探针 memo 值。
- `/api/specs?project=X`：项目 X 的 STATE.md + spec/changes 目录 + runs 目录签名。
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

### Requirement: 条件请求协商

GET 读端点在请求携带 `If-None-Match` 且其值与当前 ETag 一致时，返回 HTTP 304 空体（附当前 ETag 响应头）；不一致或未携带时返回 200 全量响应体（附当前 ETag 响应头）。协商判断发生在响应体序列化之前——304 路径不得序列化响应体。

#### Scenario: 未变数据命中 304

- **WHEN** 客户端携带 `If-None-Match: "<etag>"` 请求 `/api/admin-activities`，且期间 `admin_alerts.json` 未变化
- **THEN** 返回 304，响应体为空，传输量 ≤1KB

#### Scenario: 数据变化后返回 200 全量

- **WHEN** 客户端携带旧 ETag 请求，但项目数据源已变化
- **THEN** 返回 200 与完整响应体，`ETag` 头为新值

#### Scenario: 无条件请求不受影响

- **WHEN** curl 不带 `If-None-Match` 直接请求任一覆盖端点
- **THEN** 行为与改造前完全一致（200 全量体），仅新增 `ETag` 响应头
