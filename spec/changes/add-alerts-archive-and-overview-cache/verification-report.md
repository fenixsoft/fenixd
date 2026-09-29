# 验证报告：add-alerts-archive-and-overview-cache

> ⚠️ 本报告由框架于 2026-09-29T13:32:15Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-09-29T13:32:15.304776+00:00+run-result@mtime1790688735334426576

## 结论：✅ 通过（verified）

**状态：verified — 18/18 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 18/18 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 18 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 10.65M |
| 本链增量 Token（输出） | 0.21M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| arch-store-trim-appends-archive | 超限裁剪触发归档：夹具项目活跃文件播种 150 条（arch-a-000..149，created 递增），经 AdminStore.append 追加 2 条触发裁剪——最旧 2 条（arch-a-000/001）被移出活跃文件并按裁剪顺序逐字段一致地追加进归档 JSONL 末行，活跃文件保持 150 条且新记录在末尾。出处 spec/changes/add-alerts-archive-and-overview-cache/specs/admin-alerts-archive/spec.md「超限裁剪触发归档」；裁剪与同锁归档 core/admin_store.py:244-249，_archive_unlocked JSONL 追加 core/admin_store.py:257-283 | pass | 0/6 | - |
| arch-store-rollover-2000-cap | 归档自身滚动淘汰：归档文件预置 MAX_ARCHIVE_RECORDS=2000 条（arch-r-000..1999），活跃文件播种 150 条后再 append 1 条触发裁剪归档——归档追加 1 条后被裁回 2000 条：新条目（arch-b-000）在末行、最旧一条（arch-r-000）被淘汰，活跃文件保持 150 条。出处 spec.md「归档自身滚动淘汰」；_trim_archive_unlocked 保留末尾 N 行（临时文件+rename 原子替换）core/admin_store.py:285-312，MAX_ARCHIVE_RECORDS=2000 core/admin_store.py:54 | pass | 0/6 | - |
| arch-store-archive-failure-soft-fail | 归档失败不阻塞主写回（D2 软失败）：归档路径占位为同名目录使归档追加抛 IsADirectoryError（OSError 子类；root 下 chmod 不设防，目录占位必然触发软失败分支），注入 spy logger 后触发裁剪写回——无异常抛出、活跃文件写回成功（150 条、新记录在末尾）、归档路径保持目录、logger 收到「归档写入失败」warning，收尾清理占位目录。出处 spec.md「归档失败不阻塞主写回」；except OSError 仅记日志不抛出 core/admin_store.py:274-282 | pass | 0/6 | - |
| arch-seed-endpoint-fixtures | 为归档端点契约场景供数（自复位幂等）：夹具项目归档文件重置为 120 条分页夹具（arch-pg-000..119，created 逐分钟递增，spec 按 i%4 轮转 c-sched-set/c-sched-clear/c-sched-pg，其中 c-sched-set 恰 30 条、c-sched-clear 恰 30 条），活跃文件重置为 2 条已知 disposition（arch-active-000/001，001 最新）。后续 api 契约场景经 depends_on 消费此确定性状态。出处 admin-alerts-archive spec.md「归档只读出口」；归档 JSONL 布局 core/admin_store.py:53,95 | pass | 0/6 | - |
| arch-scratch-project-register-seed | 注册非 fixture 探针项目并供数：创建 /tmp/fenix-verify-arch-scratch（.fenix/STATE.md 两 spec + config.yaml），经 Registry().add_project（fixture=False，与 bin/fixture_scheduling_showcase.py:99-116 同通道）登记进 dashboard.yaml 注册表，播种活跃 1 条（arch-scratch-active-marker，created 2026-12-05，summary 含 arch-scratch-timeline-probe）与归档 3 条（arch-scratch-arch-00/01/02，created 2026-12-01..03，summary 含 arch-scratch-archived-probe-0N），轮询等待验证实例发现该项目（≤25s，容忍 projects 10s TTL 缓存）。出处 core/dashboard/registry.py:388（add_project）、core/dashboard/http_server.py:76-103（projects TTL 缓存决定轮询） | pass | 0/5 | - |
| ovr-api-response-shape-unchanged | overview 响应结构不变（纯缓存加速、调用方零感知）：GET /api/overview 返回 200 且载荷保持既有形态——projects 为数组、totals 为对象且含整数型 spec_count/task_total/active_runs。出处 core/dashboard/routes/project_routes.py:143（payload=dashboard_data.overview 原样返回）、core/dashboard/data/summary.py:1024（overview 聚合）、dashboard-overview-cache spec.md「overview 结果缓存：响应结构不变」 | pass | 0/2 | - |
| ovr-cache-ttl-window-hit-latency | TTL 窗口内命中：2s 内对 /api/overview 连续 3 次请求——3 次均 200；第 2/3 次走免聚合快路径（命中为 deepcopy+序列化，服务端 ≤5ms 级；冷算聚合实测 ~200ms）。latency_under 属第 4 层启发式断言（失败=warning 需上下文判定，不单凭它判产品缺陷）。出处 core/dashboard/routes/project_routes.py:126-133（TTL 快路径直接返回缓存 deepcopy）、_OVERVIEW_CACHE_TTL=2.0 project_routes.py:34、dashboard-overview-cache spec.md「TTL 窗口内命中」 | pass | 0/5 | - |
| ovr-cache-signature-reuse-past-ttl | TTL 过期但签名未变仍复用（原地修复第 2 次后复测）：每轮先对夹具 STATE.md 追加注释行并过 TTL 强制一次重算——缓存槽 sig 同步为当前文件系，同时取得同负载态重算基线 d1；随后静默 2.6s 并在「签名自重算起全程未变」的夹逼窗（睡后、GET 前、GET 后三次核对）内净测第 2 次请求 d2——应走免聚合复用快路径：scheduling-showcase 的 spec_count 前后一致（content_stable）、d2<120ms（reuse_fast）且不高于 d1 的 60%（reuse_faster_than_compute）；窗内任一时点被共享注册表第三方写入（fenixd 自身 runs 记账）击穿则换轮重试（≤6 轮）。STATE.md 用毕恢复原文。上一版缺陷：静默窗轮询只保证窗内文件未变，不保证缓存槽 sig 与文件系一致（基线后任意写入使 sig 永久滞后，静默窗 GET 按 D3 正确重算被误判复用失败）。出处 core/dashboard/routes/project_routes.py:135-146（签名未变直接复用并刷新 computed_at）、_overview_project_sig (path,mtime_ns,size) project_routes.py:40-66、dashboard-overview-cache spec.md「TTL 过期但签名未变」 | pass | 0/5 | - |
| ovr-cache-data-change-invalidates | 数据变化后过期失效：请求基线（记录 scheduling-showcase spec_count=n0）→ 向夹具 STATE.md 追加新 spec 段 c-arch-ovr-probe（签名变化）→ TTL 窗口内立即请求：命中缓存返回陈旧结果（spec_count 仍 n0，陈旧窗口与 2s 心跳节奏同量级）；静默 2.6s 过 TTL 后请求：重算生效，spec_count=n0+1。全程只观测 scheduling-showcase 自身子树（per-project spec_count），对其他项目的并发数据变化免疫；STATE.md 用毕恢复原文。出处 core/dashboard/routes/project_routes.py:126-155、core/dashboard/data/summary.py（project_summary spec_count）、dashboard-overview-cache spec.md「数据变化后过期失效」 | pass | 0/4 | - |
| web-overview-page-renders-cached-payload | 概览页消费缓存端点端到端：导航 #/overview（概览页，HashRouter）——页面拉取 /api/overview（结果缓存生效中）渲染项目卡片栅格：scheduling-showcase 卡片可见、antd Card 栅格渲染、控制台无错误（缓存命中路径返回的 deepcopy 载荷与直连聚合形态一致，前端零感知）。出处 core/dashboard/static/src/app.tsx:123（/overview 路由）、overview/index.tsx:114（监控 N 个项目副标题）、overview/components/ProjectCards.tsx（antd Card 项目栅格） | pass | 0/3 | - |
| arch-api-archived-pagination-page2 | 归档分页读取（spec 场景原样）：archived=1&project=scheduling-showcase&page=2&page_size=50 返回时间正序第 51–100 条倒序排列——total=120、page=2、page_size=50、has_more=true，activities[0].id=arch-pg-069、activities[49].id=arch-pg-020，响应含 archived/total/page/page_size/has_more/activities 六字段且 activities 不超过 50 条。出处 admin-alerts-archive spec.md「归档分页读取」；分页切片与 has_more=total>page*page_size core/dashboard/routes/alert_routes.py:163-201 | pass | 0/9 | - |
| arch-api-archived-spec-filter-combo | 归档与 spec 过滤组合：archived=1&project=scheduling-showcase&spec=c-sched-set 先过滤后分页——total=30（夹具中 spec=c-sched-set 恰 30 条）、activities[0].id=arch-pg-116（该 spec 最新）、activities[29].id=arch-pg-000、has_more=false，且每条记录 spec 恒为 c-sched-set。出处 admin-alerts-archive spec.md「归档与 spec 过滤组合」；spec 过滤 core/dashboard/data/admin_alerts.py:151-169，先过滤后分页 core/dashboard/routes/alert_routes.py:164 | pass | 0/7 | - |
| arch-api-default-timeline-ignores-archive | 读侧时间线语义不变（缺省响应与归档无关）：归档已含 120 条时请求 /api/admin-activities?project=scheduling-showcase（不带 archived）——响应仍只读活跃 admin_alerts.json：activities 恰 2 条且按 created 倒序为 arch-active-001/000，归档的 120 条不混入，响应保持 {project, spec, activities} 缺省形态。出处 admin-alerts-archive spec.md「缺省响应与归档无关」；archived 分派仅认 archived 参数 core/dashboard/routes/alert_routes.py:138-139，缺省路径不读归档 alert_routes.py:141-161 | pass | 0/5 | - |
| arch-api-archived-empty-and-param-variants | 归档空态与 archived 参数变体：(a) 无归档项目 activation-showcase 请求 archived=1 → total=0、activities=[]、has_more=false、archived=true（缺失归档文件容错返回空）；(b) archived=0 走缺省活跃路径（响应含 project 字段且 activities[0]=arch-active-001——若误路由进归档响应则无 project 顶层键，路径缺失断言必失败）；(c) archived=TRUE 大写命中归档（total=120，参数白名单大小写不敏感）。出处 core/dashboard/routes/alert_routes.py:138-139（('1','true') lower 白名单）、admin_alerts.py:166-168（缺失归档返回 []） | pass | 0/11 | - |
| arch-api-archived-pagination-default-and-beyond | 归档分页缺省值与越界：(a) archived=1 不带分页参数 → 缺省 page=1、page_size=50、activities[0].id=arch-pg-119（最新在前）、has_more=true；(b) page=4&page_size=50 越界（page=3 实为末页含 20 条，原写法算术错误已修） → activities=[]、has_more=false、total 仍 120；(c) page_size=500 被钳制到上限 200（has_more=120>200=false）。出处 core/dashboard/routes/alert_routes.py:29-31（缺省 50/上限 200 常量）、:167-169（max(1,page) 与 min(max(1,ps),200) 钳制） | pass | 0/13 | - |
| arch-api-default-aggregation-injects-project | 归档缺省聚合（无 ?project=）：跨全部非 fixture 项目聚合归档并逐条注入 project 字段、按 created 跨项目统一倒序——期望值由脚本按注册表+归档文件实时计算（并发环境下自洽）：夹具项目 120 条归档必须被跳过（scheduling-showcase 不出现在结果内，而 arch-scratch-verify 的 3 条在），total 与非 fixture 归档行数之和要求一致，activities[0]=arch-scratch-arch-02 置顶（created 2026-12-03 最晚）。cli 承载因期望值依赖实时注册表计算；端点核心契约由 5 个 api 场景钉住。出处 core/dashboard/routes/alert_routes.py:185-196（跳过 fixture、注入 project、合并倒序） | pass | 0/7 | - |
| web-activities-timeline-excludes-archive | 运维时间线页面端到端：导航 #/activities（运维页，HashRouter）——页面经 getAdminActivities() 缺省聚合渲染时间线卡片：探针项目活跃锚点卡（summary 含 arch-scratch-timeline-probe）可见，归档独有锚点（arch-scratch-archived-probe-02）不出现在时间线内（归档数据不进缺省读路径的 UI 半边），时间线卡片容器渲染，控制台无错误。出处 core/dashboard/static/src/app.tsx:134（/activities 路由）、activities/index.tsx:121-125（activity-card）、:137（project Tag）、:317（getAdminActivities 调用） | pass | 0/4 | - |
| ovr-cache-project-set-change-invalidates | overview 缓存按项目集合变化失效：移除前 /api/overview 载荷包含 arch-scratch-verify（轮询等待 ≤30s，容忍 projects 10s TTL 与 overview 缓存 TTL）；经 Registry().remove_project 移除后轮询至载荷不再包含该项目（≤35s）——项目集合（projects_key）变化使缓存失效并反映新集合。收尾兜底再移除一次保证注册表干净。出处 core/dashboard/routes/project_routes.py:121-123,135-138（projects_key 参与命中判定）、core/dashboard/registry.py:493（remove_project）、dashboard-overview-cache spec.md「项目集合变化」 | pass | 0/4 | - |
