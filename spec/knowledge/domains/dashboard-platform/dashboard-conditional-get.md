# GET 读端点条件请求（ETag/304）

<!-- knowledge: capability=dashboard-conditional-get rev=1
     sources=spec/archive/2026-10-07-add-dashboard-paging-and-etag -->

dashboard 传输侧条件请求通道：GET 读端点带数据源签名 ETag，数据未变时以 304 空体应答，传输归零。

## 规则

- ETag 取值为响应所依赖数据源的签名哈希：签名由数据源文件的 `(mtime_ns, size)` 组合廉价计算，只 stat 不读内容，计算成本 MUST 显著低于响应体序列化成本。禁对响应体做哈希——304 省传输不省计算，违背「304 路径不序列化」目标。
- 覆盖端点基线：`/api/overview`、`/api/specs?project=X`、`/api/specs/<spec>` 详情、`/api/admin-activities`（含 `?project=`）、`/api/alerts`、`/api/config`（含 `?project=`）。实现 MUST 以「响应实际依赖的数据源全集」为准：STATE.md、spec 目录、runs 目录、registry 项目清单、admin_alerts.json、config.yaml 等间接依赖一并纳入签名，宁多勿漏，禁止不完整签名造成假 304；依赖进程探针的（daemon 健康/托管态），探针 TTL memo 结果参与哈希输入；无法廉价纳入的端点 MUST NOT 挂 ETag。
- 宁缺 304 不假 304：签名函数缺失、抛错或返回空 → 降级为无条件 200 路径（不协商、不挂 ETag 头，行为与无条件请求一致）；`_json` 发头前按签名上下文复核一次，签名计算与 handler 取数是两趟读取，间隙内数据已变化的丢弃 ETag，防旧签名错标新体后被客户端缓存、数据回摆即复放假 304。
- 协商语义：请求携带 `If-None-Match` 且与当前 ETag 一致 → 304 空体（附当前 ETag 头，`Cache-Control: no-cache`——ETag 协商是唯一复用通道，不引入启发式缓存）；不一致或未携带 → 200 全量响应体（附当前 ETag 头）。协商判断发生在响应体序列化之前。
- 304 短路在表驱动分派层实现、发生在 route handler 调用之前（兼容 `_api_config_get` 等自写响应的自含 handler——等返回值再拦截对它们无效）；协商仅对 200 成功路径生效，404/错误响应不挂 ETag。
- 304 空体与 `_json` 同一写出纪律：不发响应体、不写 `Content-Length`（按 RFC 7230 由头结束分帧，恒写 0 属协议语义偏差），keep-alive 连接不被污染；`_pending_etag` 在 handler finally 中清零，防泄漏到同连接下一请求。
- stat 现算纪律：文件签名每次请求现 stat，MUST NOT 以 path 为键跨请求 memo 化 stat——「写后立刻读」窗口会吐陈旧签名造成假 304。允许的安全 memo 仅两类：单次签名计算内的路径去重（同一轮重复路径只 stat 一次，随本轮即弃）与以完整签名集为键的树哈希 memo（命中校验本身仍需全量 stat，只省重复哈希，有界清空）。
- 与计算侧缓存正交叠加：本通道只治传输，不替代 SummaryIndex 增量缓存与 `/api/overview` 结果缓存；心跳照发、前端照常重拉，未变数据的传输由 304 兜住。
- 前端请求层：`request()` 维护模块级 `Map<url, {etag, data}>` ETag 缓存（有界，超限按最旧键淘汰），仅无副作用的 GET 走缓存通道；发起时带 `If-None-Match`，304 判定先于 `!res.ok`（304 非 ok，落入错误分支会把「数据未变」误报失败）；304 命中返回缓存数据的结构化拷贝（共享缓存条目禁直接交付，防被调用方原地污染）；仅 200 且响应带 ETag 头时写缓存。缓存键为完整请求路径（含 query），同 URL 不同参数的 ETag 互不干扰。对调用方透明、接口不变形。

## 关键行为

- 数据源 `mtime_ns` 变化（如 daemon 写 STATE.md）→ 下一次请求 ETag 翻转，携带旧 ETag 的条件请求返回 200 全量新体。
- 运行态数据源变化（runs 目录新增 run 记录）而 STATE.md 未变 → `/api/overview` ETag 照样翻转，不返回陈旧概览。
- 同一签名窗口内连续多次无条件请求：ETag 互相一致（签名确定性），签名计算复用安全 memo，总耗时与单次同量级。
- 无 `If-None-Match` 的请求行为与基线完全一致（200 全量体），仅新增 `ETag` 响应头；对不感知 ETag 的调用方零影响。

## 溯源

- 2026-10-07 add-dashboard-paging-and-etag（spec/archive/2026-10-07-add-dashboard-paging-and-etag） — 新增 GET 读端点 ETag/304 条件请求通道：数据源签名计算、分派层协商短路、「宁缺 304 不假 304」纪律与前端请求层 ETag 缓存
