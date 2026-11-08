# 验证报告：fix-specs-api-latency

> ⚠️ 本报告由框架于 2026-11-08T13:10:24Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-11-08T13:10:23.936878+00:00+run-result@mtime1794143423984254290

## 结论：✅ 通过（verified）

**状态：verified — 15/15 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 15/15 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 15 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 13.20M |
| 本链增量 Token（输出） | 0.14M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| api-specs-unknown-project-compat | 「未知项目兼容契约（api 静态形态）」：GET /api/specs?project=__no_such_project__ 维持 200 + {"error": "unknown project", "specs": []} 的 v1 兼容契约（不走 404 家族）；缺 project 参数时同款 unknown project 文案与空表形状。出处：core/dashboard/routes/spec_routes.py:105-111 + http_server.py:121-125（未注册名经 project_by_name 未命中返回 None 走 unknown project 分支；project not found 仅 registered-but-missing 的 exists=False 分支可达；改造前代码 d77c4d3e5^ 分支结构逐字一致） | pass | 0/6 | - |
| cli-specs-error-contracts | 「未知项目与缺参错误体不挂 ETag（live 探针）」：api 形态只能断静态形状，本场景用探针补「错误响应恒无条件 200 且不带 ETag 头」的动态断言（协商仅对 200 成功路径生效的纪律回归）。未注册名与缺参同走 unknown project 分支（project_by_name 未命中返回 None）。探针经 FENIX_VERIFY_BASE_URL 打真实实例，输出 JSON 由 json_output 仲裁。出处：core/dashboard/routes/spec_routes.py:104-111（错误体不参与协商、不挂 ETag；两输入同文案） | pass | 0/6 | - |
| cli-index-slot-lock-tests | 「SummaryIndex 分槽锁并发语义（tasks 1.3 单测层）」：运行交付物测试 tests/test_dashboard_index.py 的三个并发用例——跨项目槽不互斥（test_cross_project_slots_do_not_block）、同项目并发 get 仍互斥（test_same_project_concurrent_gets_serialize）、invalidation_signature 内调 state_snapshot 同槽重入不死锁（test_invalidation_signature_reentrant_no_deadlock）。-v 单档输出（禁 -v -q 并列），断言逐用例 PASSED 行 | pass | 0/4 | - |
| cli-signature-aggregation-tests | 「get_with_signature 同趟聚合契约（tasks 2.2/2.3 单测层）」：运行 tests/test_dashboard_index.py 三用例——聚合签名与 invalidation_signature 逐字节等值（test_aggregate_signature_matches_invalidation_signature，防两套 combine 结构漂移假 304）、签名组件不可得返回 None 且列表仍产出（test_signature_none_when_component_unavailable）、聚合零额外扫描（test_aggregation_adds_zero_extra_scans）。出处：spec dashboard-read-path-performance「get 取数同趟产出失效签名聚合」Requirement | pass | 0/4 | - |
| cli-api-etag-regression-tests | 「/api/specs ETag/304 回归套件（tasks 3.3 单测层）」：运行 tests/test_dashboard_api.py 的 specs 协商回归子集——304 命中空体、无条件 200 体附 ETag、翻页变体 ETag 不同、签名不可得降级无 ETag、304 后 keep-alive 连接复用、STATE.md mtime 变化翻转 ETag、重复调用 ETag 稳定、错误响应裸响应无 ETag。in-process 夹具实例，不依赖 live 实例 | pass | 0/9 | - |
| cli-perf-guard-tests | 「性能守卫（tasks 4.1/4.2，新文件 tests/test_specs_api_perf_guard.py）」：规模夹具（活跃+归档各 ≥300 spec 目录）上断言 /api/specs 单次 200 全链 _stat_sig 调用计数 ≤ 三趟形态的 1/2（三趟并一趟的结构性证明，不依赖绝对时间）；跨项目互斥 handler 层断言（项目 A 冷重建在飞时项目 B 端到端响应不被阻塞）。重型夹具构建标记 resource_group 互斥 | pass | 0/3 | - |
| cli-watcher-regression-tests | 「watcher SSE 广播路径回归（tasks 5.1）」：get() 改薄包装后 watcher 消费形态零变化——运行 tests/test_dashboard_watcher_incremental.py 全文件（增量推送/不变不重推/单 spec 变更单条推送/删除 null 标记/千级规模 50ms 内）。出处：core/dashboard/data/summary.py:901-908（get() = get_with_signature(...)[0] 薄包装） | pass | 0/3 | - |
| web-projects-page-smoke | 「前端零改动回归 smoke」：服务端 /api/specs 改造后，项目 SPEC 列表页照常渲染——打开 scheduling-showcase 列表页，桌面 Table 渲染 9 个夹具 spec（行内进度格与 spec 名可见），控制台无错误、网络无错误。出处：core/dashboard/static/config/routes.ts:44-47（/projects/:name → ./projects/list）、core/dashboard/static/config/config.ts:15（history: hash——URL 带 #/ 前缀）、core/dashboard/static/src/app.tsx:148（/projects 菜单注册） | pass | 0/4 | - |
| api-specs-response-shape | 「/api/specs 200 响应形状与 ETag 头（api 静态形态）」：无条件 GET 夹具项目 scheduling-showcase——200 全量体、Content-Type JSON、project 名回显、specs 非空数组、ETag 头在场且双引号包裹（_route_etag 同款）、首请求延迟软上限（启发式层 warning，不作硬门）。出处：core/dashboard/routes/spec_routes.py:79-140（自含响应 handler） | pass | 0/6 | - |
| api-specs-inline-negotiation-304 | 「handler 内联协商在位（api 形态结构性证明）」：路由表 /api/specs 条目已摘掉第 4 位 sig_fn（4 元组→3 元组，表驱动 304 通道摘除）——If-None-Match: * 得到 304 只能来自 _api_specs handler 内部的 _if_none_match_hit 内联协商；随后无条件请求照常 200 附 ETag。出处：core/dashboard/routes/base.py:236（* 通配命中）、spec_routes.py:134（内联协商） | pass | 0/3 | - |
| cli-specs-etag-negotiation-lifecycle | 「/api/specs 同趟协商 304 全生命周期（live 探针，单 keep-alive 连接）」：①无条件 200 全量体附双引号 ETag；②同签名窗口重复请求 ETag 一致（确定性）；③携当前 ETag → 304 空体、无 Content-Length（RFC 7230 头结束分帧纪律）、附当前 ETag；④304 后同连接继续请求得合法 200（keep-alive 未失步，自含 handler 未双写污染）；⑤携不存在 ETag → 200 全量体。304 空体/无 Content-Length/ETag 头为动态断言，api 形态无法承载，故用探针。出处：core/dashboard/routes/base.py:883-897（_write_304 空体写出纪律） | pass | 0/9 | - |
| cli-specs-paging-variants | 「翻页切片不变量与翻页 ETag 变体（live 探针）」：①无参响应不带 total（缺省 page 响应零变化）；②page=1&page_size=2 的 specs 切片 ≡ 无分页全量列表前 2 条（created 倒序同名对齐）、total==全量条数、page/page_size/has_more 字段正确；③page=2&page_size=2 切片 ≡ 第 3-4 条；④翻页变体 ETag 互不相同且与无参 ETag 不同（page/page_size 原始值入签）；⑤page_size=99999 截到 500、has_more=false；⑥同变体重复请求 ETag 一致（确定性）。出处：core/dashboard/routes/spec_routes.py:130-133（原始 query 值拼稳定串）、base.py:763-781（_parse_page_params max_size=500） | pass | 0/6 | - |
| cli-conditional-get-regression-others | 「表驱动 304 通道不受 /api/specs 改造牵累（live 探针）」：其余表驱动端点（/api/alerts?project=、/api/config、/api/admin-activities?project=）各自的「无条件 GET 得双引号 ETag → 携 ETag 条件请求得 304 空体」通道照常工作——守护 base.py 路由表手术后既有协商语义零回归。出处：core/dashboard/routes/base.py:632/637/640（4 元组表驱动条目） | pass | 0/5 | - |
| cli-specs-etag-flip-on-change | 「签名随数据源变化（live 探针，一次性变更夹具）」：os.utime 仅改夹具项目 scheduling-showcase 的 STATE.md mtime（内容不变）→ 下一次 /api/specs 的 ETag 与改前不同；携旧 ETag 的条件请求返回 200 全量新体且 ETag 为新值。夹具每轮由 prepare --reset 复位、fixture=true 已过 ADR-163 降噪，一次性 mtime 变更属场景内合法操作。出处：spec delta dashboard-conditional-get「签名随数据源变化」Scenario；core/dashboard/data/summary.py:940（get_with_signature 槽锁内现算签名） | pass | 0/5 | - |
| cli-specs-signature-degrade | 「签名不可得降级与恢复回归（live 探针，临时改名夹具 STATE.md 并 finally 复位）」：STATE.md 不可读（state 签名组件缺失，get_with_signature 返回 None 签名）→ 响应降级无条件 200 全量体：不挂 ETag 头、不协商，列表字段照常返回（列表源=活跃∪归档 spec_routes.py:113-116：STATE.md 移走后活跃侧清空、夹具归档清单条目 f-arch-title 照常产出——in-repo 契约 test_specs_signature_unavailable_degrades_no_etag 的空表形状仅因其空清单夹具，降级契约不承诺清空列表）；复位后 ETag 恢复、活跃列表恢复非空（回归点）。出处：spec_routes.py:117-121（agg_sig None 降级分支） | pass | 0/5 | - |

## 本轮场景集变更

场景集与持久化集一致，无变更。

