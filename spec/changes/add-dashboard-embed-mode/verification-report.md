# 验证报告：add-dashboard-embed-mode

> ⚠️ 本报告由框架于 2026-10-14T10:47:21Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-10-14T10:44:42.975719+00:00+run-result@mtime1791974825864027607

## 结论：✅ 通过（verified）

**状态：verified — 10/11 场景通过，0 失败，0 错误（全部场景通过）**

11 场景：10 pass，1 flaky warning（embed-sse-stream-alive 仅视觉 SSIM 0.6721<0.95，6 项功能断言全过；根因为 SSE 实时记录流动态内容区，activities/index.tsx:510-517 created 排序 + :436-437 事件驱动重拉，第4层动态内容特判豁免，非产品缺陷，不阻塞）。静态情报 3 处 double_han 断言（监控/设置）经执行证据核实为误报：目标为容器文本 text_contains 而非 antd Button，断言均 pass（checked_elements=1），无需修复场景文件。

| 指标 | 数量 |
| --- | --- |
| 通过 | 10 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 0.59M |
| 本链增量 Token（输出） | 0.13M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| default-unprefixed-byte-identical | 缺省行为逐字节一致（spec: 缺省行为逐字节一致）：不带任何参数直开根路径、hash 路由进概览页。本场景零 mock，页面全部请求打真实同源端点——若实现给缺省 apiBase 误加前缀，全部 /api/* 请求将 404，被 no_network_error 与错误横幅断言捕获；概览数据与告警横幅正常渲染即证明缺省请求路径与改造前一致。出处：core/dashboard/routes/base.py:1027（/ → dist/index.html）、core/dashboard/static/config/routes.ts:11（/overview 路由）、core/dashboard/static/config/config.ts:12,15（publicPath './' + hash 路由）、core/dashboard/static/src/services/dashboard.ts:77,197（STREAM_URL/request() 经 withApiBase 缺省恒等）。 | pass | 0/6 | - |
| non-embed-shell-intact-nav | 非 embed 布局不变（spec: 非 embed 布局不变）：无参数启动下全局侧栏、全局顶栏、面包屑照常渲染，且侧栏菜单导航可用——点击「设置」经 hash 路由进入设置页。出处：core/dashboard/static/src/app.tsx:149（isEmbedMode() 为假时不增 menuRender/headerRender 键，布局配置与现状逐字节一致）、app.tsx:120-121（menuItemRender 以 Link 包裹菜单项）、app.tsx:144（actionsRender 挂 HeaderCrumb）、app.tsx:95（面包屑 .global-header-crumb）、core/dashboard/static/config/routes.ts:31（/settings 路由）；data-testid 出处：@ant-design/pro-components es/layout/components/SiderMenu/SiderMenu.js:277（pro-layout-sider）、GlobalHeader/index.js:79（pro-layout-global-header）。 | pass | 0/7 | - |
| embed-shell-hidden-overview | embed=1 隐藏壳层（spec: embed 隐藏壳层）：以 ?embed=1 启动进概览页，ProLayout 全局侧栏与全局顶栏（含面包屑）不渲染，页面自身内容头（PageContainer 标题「跨项目概览」）保留；apiBase 未设，数据经真实根相对端点正常加载，SSE（EventSource）照常建连。出处：core/dashboard/static/src/app.tsx:145-149（embed 分支 menuRender:false + headerRender:false 经运行时布局配置下发）、@ant-design/pro-components es/layout/ProLayout.js:28-30（headerRender===false 返回 null）、ProLayout.js:59（menuRender===false 返回 null）、core/dashboard/static/src/pages/overview/index.tsx:154-158,116（内容头标题与 STREAM_URL EventSource）。 | pass | 0/9 | - |
| embed-sse-stream-alive | embed=1 下 SSE 自动刷新通道与独立访问等价（spec: 嵌入态自动刷新保留）：打开运维页（同一 services 单源 STREAM_URL 的 EventSource），等待建连窗口后，页内 SSE 健康灯「实时刷新已断开」不出现——该提示条仅在 EventSource 断连（readyState CLOSED 或连续失败）时上屏，不亮即流连接存活、自动刷新通道挂载完成；SSE 端点事件流本身由 api 场景 stream-endpoint-sse-hello 在同一 fresh 实例的 HTTP 层钉住（上游真实事件产生依赖外部活动，场景以「端点活性 + 通道存活」组合钉住等价性，如实分解、不以 mock 掩盖）。出处：core/dashboard/static/src/pages/activities/index.tsx:421（EventSource(STREAM_URL)）、activities/index.tsx:579-586（streamDown 断流提示条）、activities/index.tsx:436-437（alerts/refresh 事件驱动重拉）、core/dashboard/static/src/services/dashboard.ts:77。 | warning | 0/6 | flaky |
| embed-api-prefix-requests | apiBase 前缀化请求 + 两参数独立生效（spec: 前缀化请求）：以 ?apiBase=/fenix-dashboard 启动（无 embed），request() 封装的全部调用（getInitialState 与概览页的 getOverview、AlertBanner 的 getAlerts）打到前缀路径，且壳层照常渲染（apiBase 单独存在不影响布局）。验证实例无反代（/fenix-dashboard/ 前缀反代属 dsh 面板桥另一仓库 SPEC 交付），故以 mock_api 拦截前缀命名空间 URL（**/fenix-dashboard/api/overview、**/fenix-dashboard/api/alerts）作为代理替身回探针数据：探针项目名上屏即证明请求真实走了前缀路径；若前缀化缺失，请求落真实根相对端点、探针数据不出现，断言失败——mock 未覆盖被测交付物（前端 URL 构造）的判定路径，仅顶替本实例不存在的反代半边。首个 mock_api 注册后引擎自动挂起 **/api/stream*（EventSource 停在 CONNECTING，无 404 重连噪声）。出处：core/dashboard/static/src/services/dashboard.ts:197（fetch(withApiBase(path))）、dashboard.ts:77（STREAM_URL）、core/dashboard/static/src/app.tsx:32-35（getInitialState 走 getOverview）、core/dashboard/static/src/utils/embedMount.ts:52-57。 | pass | 0/6 | - |
| embed-api-combined-independent | 参数组合互不干扰（spec: 参数组合）：?embed=1&apiBase=/fenix-dashboard/ 组合启动（apiBase 特意带尾斜杠，顺带钉住 embedMount 的斜杠归一）——壳层隐藏（embed 生效）且请求走前缀（apiBase 生效），两者互不干扰；探针项目名上屏即前缀请求落地。mock 策略同 embed-api-prefix-requests（前缀命名空间代理替身，不 mock 被测对象）。出处：core/dashboard/static/src/utils/embedMount.ts:52-57（base 去尾部斜杠归一）、app.tsx:145-149（embed 壳层隐藏）、services/dashboard.ts:197。 | pass | 0/7 | - |
| embed-arch-iframe-prefixed-src | 服务层构造的下发 URL 同单点（spec: 服务层构造的下发 URL 同单点）：?apiBase=/fenix-dashboard 深链夹具项目 scheduling-showcase 的「架构蓝图」分面（hash 内 ?tab=architecture 直达），ArchitectureTab 渲染的架构图 iframe src 经 architectureDiagramUrl() 前缀化，attribute_match 精确相等断言为 /fenix-dashboard/api/architecture/diagram?project=scheduling-showcase&present=1（architectureDiagramUrl 输出为确定性字符串，逐字节可比）。验证实例无反代，mock_api 拦截前缀 status（回 ready）与 diagram 作代理替身；项目页其余未 mock 的前缀旁路请求（specs 等）在本实例 404 属预期环境形态（反代是 dsh 侧 SPEC 交付物），故本场景不挂 no_console_error/no_network_error，仅断言分面内容与 iframe src——mock 未覆盖被测交付物（iframe src 的 URL 构造），src 属性断言打在前端真实产物上。出处：core/dashboard/static/src/services/dashboard.ts:2535-2537（architectureDiagramUrl 经 withApiBase）、core/dashboard/static/src/pages/projects/components/ArchitectureTab.tsx:331-338（iframe src/title 项目架构图/sandbox allow-scripts）、ArchitectureTab.tsx:309-312（「核心组件：N 个」元信息）、core/dashboard/static/src/pages/projects/list.tsx:1552-1557（架构蓝图分面 active 门控）、listFilters.ts:8-15,51-52（tab=architecture 深链合法值）；夹具出处：bin/fixture_scheduling_showcase.py（verify.yaml prepare 每轮 provision 并登记 scheduling-showcase）。 | pass | 0/4 | - |
| api-dist-relative-assets | 构建产物可前缀挂载（spec: 前缀下资源加载·回归钉）：GET / 返回的 dist/index.html 以相对引用（publicPath './'）引用 bundle（src="./umi.<hash>.js"、href="./umi.<hash>.css"）——hash 路由 + 相对资源形态使整站可在任意路径前缀下由反代挂载（静态资源相对文档 URL 解析）。本 SPEC 不改构建配置，本场景钉产物形态不回归；「资源全部 200 加载、应用正常启动」由零 mock 的 web 场景 default-unprefixed-byte-identical 在同实例上实证。出处：core/dashboard/static/config/config.ts:12（publicPath './'）、config.ts:15（hash 路由）、core/dashboard/routes/base.py:1027-1028（/ → _serve_static("dist/index.html")）、core/dashboard/routes/static_routes.py:58-63（根路径回退映射到 dist/）。 | pass | 0/4 | - |
| api-stream-sse-hello | SSE 流端点（STREAM_URL 单源目标）在 fresh 实例上真实可用（spec: 嵌入态自动刷新保留的 HTTP 层半边）：SSE 连接建立后服务端立即推送 hello（携带 cid）首事件，此后持续广播——embed 与独立访问两形态的页面 EventSource 均连此端点，本场景在 HTTP 层钉住事件流活性。端点为本 SPEC 交付物依赖的真实后端端点（本 SPEC 后端零改动），打真实实例、不 mock。出处：core/dashboard/routes/base.py:972-980（GET /api/stream → _handle_sse）、core/dashboard/routes/sse_routes.py:37-88（首事件 hello 携 cid，sse_send 帧形态 data: {"type": "hello", ...}）。 | pass | 0/2 | - |
| cli-embedmount-unit-tests | embedMount 单测全绿（tasks 3.1-3.3 交付物回归）：core/dashboard/static/tests/embedMount.test.mjs 覆盖参数解析/拼接（缺省恒等、多斜杠归一）、isEmbedMode 判定、两参数组合互不干扰、缺省逐字节回归（getOverview 封装/STREAM_URL/architectureDiagramUrl 缺省产出根相对 URL）、apiBase 前缀化回归，以及「ClaudeOutputPane 引用单源：无硬编码流端点」源码面 grep 断言（spec 场景「组件内自建流连接同单点」的源码钉——该面板需真实 run 产物方可 E2E 打开，源码面断言 + STREAM_URL E2E 场景组合钉住本交付点）。输出断言文案照抄实测 spec reporter 输出（pass 10 / fail 0）。出处：core/dashboard/static/tests/embedMount.test.mjs、spec/changes/add-dashboard-embed-mode/tasks.md 3.1-3.3。 | pass | 0/4 | - |
| cli-frontend-full-regression | 前端全量回归全绿（tasks 4.2）：node --test tests/*.test.mjs 跑全部前端单测（248 用例，含 embedMount/etagCache/sessionEvents 等），钉住「前缀化改造未打断任何既有前端行为」。实测耗时约 1.3s、spec reporter 输出 pass 248 / fail 0；断言用与用例数解耦的稳定片段（fail 0、withApiBase 函数名）防用例增删致伪失败。出处：spec/changes/add-dashboard-embed-mode/tasks.md 4.2、core/dashboard/static/tests/。 | pass | 0/3 | - |


## 断言级豁免清单

以下失败断言被归类为非产品缺陷（不记产品 Bug），逐条列出供人工复核豁免是否掩盖真实缺陷（场景级一句话归因不足以复核）。

| 场景 | 断言 | 归类 | 豁免理由 | 证据 |
| --- | --- | --- | --- | --- |
| embed-sse-stream-alive | visual_diff embed-sse-stream-alive 全页 SSIM 0.6721<0.95（retake_count=2） | flaky | 不稳定复现（非产品缺陷） | 6项功能断言全过（断流提示条未亮/无console与network错误/壳层隐藏）；activities/index.tsx:510-517 记录按 created 时间戳排序，:436-437 SSE alerts/refresh 事件驱动重拉，验证期实例自身持续广播 state 事件（见 api-stream... |

## 本轮场景集变更

当前稳定场景集共 11 个（第 1 轮）。

- 首轮写入 11 个场景

