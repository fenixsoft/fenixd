# GET 读端点条件请求（ETag/304）

<!-- knowledge: capability=dashboard-conditional-get rev=3
     sources=spec/archive/2026-10-07-add-dashboard-paging-and-etag,spec/knowledge/_inbox/done/specs-api-read-path-triple-scan.md,spec/changes/fix-specs-api-latency -->

dashboard 传输侧条件请求通道：GET 读端点带数据源签名 ETag，数据未变时以 304 空体应答，传输归零。

## 规则

- ETag 取值为响应所依赖数据源的签名哈希：签名由数据源文件的 `(mtime_ns, size)` 组合廉价计算，只 stat 不读内容，计算成本 MUST 显著低于响应体序列化成本。禁对响应体做哈希——304 省传输不省计算，违背「304 路径不序列化」目标。
- 覆盖端点基线：`/api/overview`、`/api/specs?project=X`、`/api/specs/<spec>` 详情、`/api/admin-activities`（含 `?project=`）、`/api/alerts`、`/api/config`（含 `?project=`）。实现 MUST 以「响应实际依赖的数据源全集」为准：STATE.md、spec 目录、runs 目录、registry 项目清单、admin_alerts.json、config.yaml 等间接依赖一并纳入签名，宁多勿漏，禁止不完整签名造成假 304；依赖进程探针的（daemon 健康/托管态），探针 TTL memo 结果参与哈希输入；无法廉价纳入的端点 MUST NOT 挂 ETag。
- 宁缺 304 不假 304：签名函数缺失、抛错或返回空 → 降级为无条件 200 路径（不协商、不挂 ETag 头，行为与无条件请求一致）。表驱动通道端点的签名计算与 handler 取数是两趟读取，`_json` 发头前按签名上下文复核一次，间隙内数据已变化的丢弃 ETag，防旧签名错标新体后被客户端缓存、数据回摆即复放假 304。
- 协商语义：请求携带 `If-None-Match` 且与当前 ETag 一致 → 304 空体（附当前 ETag 头，`Cache-Control: no-cache`——ETag 协商是唯一复用通道，不引入启发式缓存）；不一致或未携带 → 200 全量响应体（附当前 ETag 头）。协商判断发生在响应体序列化之前。
- 304 短路在表驱动分派层实现、发生在 route handler 调用之前；自含响应 handler（`/api/config` 的 `_api_config_get`、`/api/specs` 的 `_api_specs`）无法被该短路拦截——等返回值再拦截对它们无效，协商改在 handler 内联完成。协商仅对 200 成功路径生效，404/错误响应不挂 ETag。
- `/api/specs` 为取数同趟型协商，不经表驱动 304 通道：失效签名由 `SummaryIndex.get_with_signature` 与取数同趟产出（同趟原子；聚合结构与 `invalidation_signature` 同构同源，一致性守卫测试锚定两者逐字节等值，防两套 combine 结构漂移造成假 304），最终 ETag = 聚合签名与 `page`/`page_size` 原始 query 值稳定串的 combine——分页变体不共享 ETag，宁少 304 不可跨变体假 304，缺省参数请求共享同一 ETag；签名不可得降级为无条件 200；304 命中路径同时完成索引取数（预热缓存，对后续 200 有利）；错误体（未知/不存在项目恒 200 + error 字段空表）不参与协商、不挂 ETag；同趟原子使发头前签名复核对本端点不适用。
- 304 空体与 `_json` 同一写出纪律：不发响应体、不写 `Content-Length`（按 RFC 7230 由头结束分帧，恒写 0 属协议语义偏差），keep-alive 连接不被污染；`_pending_etag` 在 handler finally 中清零，防泄漏到同连接下一请求。
- stat 现算纪律：文件签名每次请求现 stat，MUST NOT 以 path 为键跨请求 memo 化 stat——「写后立刻读」窗口会吐陈旧签名造成假 304。允许的安全 memo 仅两类：单次签名计算内的路径去重（同一轮重复路径只 stat 一次，随本轮即弃）与以完整签名集为键的树哈希 memo（命中校验本身仍需全量 stat，只省重复哈希，有界清空）。
- 与计算侧缓存正交叠加：本通道只治传输，不替代 SummaryIndex 增量缓存与 `/api/overview` 结果缓存；心跳照发、前端照常重拉，未变数据的传输由 304 兜住。
- 前端请求层：`request()` 维护模块级 `Map<url, {etag, data}>` ETag 缓存（有界，超限按最旧键淘汰），仅无副作用的 GET 走缓存通道；发起时带 `If-None-Match`，304 判定先于 `!res.ok`（304 非 ok，落入错误分支会把「数据未变」误报失败）；304 命中返回缓存数据的结构化拷贝（共享缓存条目禁直接交付，防被调用方原地污染）；仅 200 且响应带 ETag 头时写缓存。缓存键为完整请求路径（含 query），同 URL 不同参数的 ETag 互不干扰。对调用方透明、接口不变形。

## 关键行为

- 数据源 `mtime_ns` 变化（如 daemon 写 STATE.md）→ 下一次请求 ETag 翻转，携带旧 ETag 的条件请求返回 200 全量新体。
- 运行态数据源变化（runs 目录新增 run 记录）而 STATE.md 未变 → `/api/overview` ETag 照样翻转，不返回陈旧概览。
- 同一签名窗口内连续多次无条件请求：ETag 互相一致（签名确定性），签名计算复用安全 memo，总耗时与单次同量级。
- 无 `If-None-Match` 的请求行为与基线完全一致（200 全量体），仅新增 `ETag` 响应头；对不感知 ETag 的调用方零影响。

## 代码锚点

- 主实现：`core/dashboard/routes/base.py`（表驱动协商短路、ETag 与 304 写出、发头前复核通道）
- 单源符号：`core/dashboard/routes/base.py:_route_etag`、`core/dashboard/routes/base.py:_if_none_match_hit`
- 消费方：`core/dashboard/routes/spec_routes.py`（specs 自含协商）、`core/dashboard/routes/alert_routes.py`（端点侧签名函数）
- 守卫测试：`tests/test_dashboard_api.py`（If-None-Match 协商）、`tests/test_specs_api_perf_guard.py`（specs 单趟）

## 溯源

- 2026-10-07 add-dashboard-paging-and-etag（spec/archive/2026-10-07-add-dashboard-paging-and-etag） — 新增 GET 读端点 ETag/304 条件请求通道：数据源签名计算、分派层协商短路、「宁缺 304 不假 304」纪律与前端请求层 ETag 缓存
- 2026-11-08 specs-api-read-path-triple-scan（spec/knowledge/_inbox/done/specs-api-read-path-triple-scan.md） — /api/specs 摘出表驱动通道、改取数同趟型自含协商：同趟原子发头前复核不适用、分页变体进 ETag 稳定串、签名不可得降级无条件 200
- 2026-11-08 fix-specs-api-latency（spec/changes/fix-specs-api-latency/） — 协商通道按端点分两型的正式 SPEC 入库（表驱动型默认 / specs 取数同趟型例外）：同趟聚合签名与 invalidation_signature 同构同源守卫、304 命中同时预热索引缓存、表驱动端点复核机制不动
