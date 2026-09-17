# 验证报告：refactor-giant-classes

> ⚠️ 本报告由框架于 2026-09-17T19:13:12Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-09-17T18:56:33.075321+00:00

## 结论：❌ 未通过（Bug Found）

**状态：bug-found — 16/19 场景通过，3 失败，0 错误（1 个真实产品 Bug）**

19 场景 16 过 3 败。web-settings-tab-interaction=test-defect（跨轮已裁决写回：settings 用 antd Menu 非 Tabs，选择器组件类型错误）。api-post-chain-spec-evolution 与 api-spec-detail-doc-error-paths=product-bug：表驱动适配层对 handler 错误路径响应写序未隔离，keep-alive 连接复用下错误路径响应异常（501/200+null），新连接实测 404/400 均与断言语义一致，场景断言目标值正确非场景缺陷。静态情报 web-projects-shell-and-hash-sublist 核实为非缺陷：text_contains 目标 PagePlaceholder title（PageContainer header 非 antd Menu/Button，autoInsertSpace 不作用），且该场景本轮 pass。

| 指标 | 数量 |
| --- | --- |
| 通过 | 16 |
| 失败 | 3 |
| 错误 | 0 |
| 产品 Bug | 1 |
| 本链增量 Token（输入） | 11.58M |
| 本链增量 Token（输出） | 0.17M |


## 真实产品 Bug

### BUG-01（severity=major）· status_code

- 关联场景：api-post-chain-spec-evolution、api-spec-detail-doc-error-paths
- 描述：dashboard HTTP 适配层 keep-alive 连接缺陷：POST /api/spec-error-clear 对不存在项目在 httpx 连接复用会话内返回 501（新连接实测 404 正确）；GET /api/spec-doc 对不存在项目返回 200+body null（新连接实测 400 正确）。两处均只在 keep-alive 会话内复现，新连接行为与源码断言语义一致。
- 根因：core/dashboard/routes/base.py 表驱动适配层：_get_spec_doc（base.py:98-99）用 s._json(s._api_spec_doc(q)) 包装，但 _api_spec_doc 错误分支已自写 _error 响应并 return None，适配器再执行 _json(None) 双重写响应，keep-alive 连接残留第二个响应（200+null）被后续请求读到；POST 链（_post_spec_error_clear 等）错误路径响应写序/连接生命周期处理缺陷致复用连接后续请求 501。两机制同源：适配层对 handler 错误路径响应写序未隔离，重构搬移引入。
- 证据（场景 api-post-chain-spec-evolution 结构化证据，引用）：
  - failed_assertions: [{"type": "status_code", "expected": 404, "actual": 501, "label": "spec-error-clear 不存在项目 → 404"}]
  - screenshots: []
  - first_failed_step: 步骤2: POST /api/spec-error-clear?project=no-such-project-xyz&spec=x 期望 404 实际 501——httpx keep-alive 会话内前一请求响应后连接生命周期处理缺陷（新连接实测 404 正确）


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| web-overview-page-renders | 概览页 /overview 在重构后的 server/routes 子包路由分派下正常加载渲染：侧边菜单「概览」「项目」可见、页面 header「跨项目概览」渲染、无 console/网络错误。出处：core/dashboard/static/config/routes.ts:11（/overview 路由）、core/dashboard/static/src/pages/overview/index.tsx:65（title 跨项目概览）、core/dashboard/static/src/app.tsx:101（菜单项） ｜web 场景 | pass | 0/5 | - |
| web-settings-tab-interaction | 设置页 /settings 在重构后正常加载：左侧 tab 菜单渲染（含「系统」），点击「系统」tab 后 SystemPanel 面板渲染（data-testid=system-panel），验证 server 静态服务与 SPA 路由分派正常、交互可用。出处：core/dashboard/static/config/routes.ts:31（/settings 路由）、core/dashboard/static/src/pages/settings/index.tsx:34（system tab）、core/dashboard/static/src/pages/settings/components/SystemPanel.tsx:245（data-testid=system-panel） ｜web 场景 | failed（已修正） | - | test-defect |
| web-projects-shell-and-hash-sublist | 项目页 /projects 与多级 hash 路由 /projects/showcase（spec 树列表）在重构后正常加载：菜单「项目」可见、面包屑显示目标项目名、页面内容区渲染、无 console/网络错误——验证 H2/H3 数据经重构后的 server 路由表驱动分派被前端消费。出处：core/dashboard/static/config/routes.ts:17（/projects）、core/dashboard/static/config/routes.ts:27（/projects/:name）、core/dashboard/static/src/app.tsx:53-61（面包屑 crumbItems） ｜web 场景 | pass | 0/5 | - |
| api-overview-projects-read | H2 project_routes 读侧端点集合语义保持：GET /api/overview、GET /api/projects 均 200 且返回 JSON 结构（projects 数组），响应语义与重构前一致（design D1 表 C H2；task 4.8 端点集合零变化）。出处：core/dashboard/routes/project_routes.py:22（_api_projects）、:48（_api_overview）；路由表 core/dashboard/routes/base.py:236 | pass | 0/6 | - |
| api-specs-parameterized-routes | H3 spec_routes 精确+regex 参数化路由（表驱动）语义保持：GET /api/specs 无 project 参数→200 {error:unknown project,specs:[]}；GET /api/specs?project=<不存在>→200 {error:project not found,specs:[]}——确定性语义验证 regex matcher 参数化分派（GET 20 = 18精确+2 regex，design D1）。出处：core/dashboard/routes/spec_routes.py:21（_api_specs）；core/dashboard/routes/base.py:239(regex /api/specs/([^/]+)$) | pass | 0/6 | - |
| api-config-evolution-alerts-read | H5 settings_routes/H6 alert_routes/H7 evolution_routes 读侧端点语义保持：GET /api/config（无 project）→200 用户级配置结构；GET /api/evolution/items（无参）→200 {items:[]}；GET /api/alerts（无参）→200 跨项目聚合结构——验证三资源组 handler 在表驱动分派下响应与重构前一致。出处：core/dashboard/routes/settings_routes.py:29、core/dashboard/routes/evolution_routes.py:33、core/dashboard/routes/alert_routes.py:22 | pass | 0/7 | - |
| api-events-evolution-analysis-error | H4 run_routes/H7 evolution_routes 端点语义保持：GET /api/events（无 project）→200 {events:[]}；GET /api/hooks/audit（无参）→200 {audit:[]}；GET /api/evolution/analysis（缺 item_id）→400——确定性验证 GET 链表驱动分派各 handler。出处：core/dashboard/routes/run_routes.py:103（_api_events）、core/dashboard/routes/run_routes.py:127（_api_hooks_audit）、core/dashboard/routes/evolution_routes.py:46（_api_evolution_analysis） | pass | 0/6 | - |
| api-post-chain-spec-evolution | POST 表驱动分派（_API_POST_ROUTES 33 条，design D1 保留 endswith 顺序陷阱）语义保持：POST /api/spec-error-clear 无 project→400/404 unknown project；POST /api/evolution/reject 缺 item_id→400 缺少 item_id 参数——确定性异常路径验证 POST 链分派到正确 handler 而非 405。出处：core/dashboard/routes/base.py:260（_API_POST_ROUTES）、core/dashboard/routes/spec_routes.py:58（_api_spec_error_clear）、core/dashboard/routes/evolution_routes.py:83（_api_evolution_reject） | failed | 1/4 | product-bug |
| cli-facade-reexport-integrity | 门面 re-export 完整性（design D3/5.2 patch 缝隙）：三个子包门面全部公开名 import 可用——WorktreeManager/MergeConflictInfo/8 常量/_is_claude_process/_is_build_artifact_path；Dispatcher/DEFAULT_DISPATCH_BACKOFF_SCHEDULE/MAX_REPAIR_ROUNDS_PER_FAILURE；serve/STATIC_DIR/DashboardHTTPServer/find_free_port/SSEHub/HELP_DOC_NAME_RE/_bind_parent_lifecycle/_claude_watchdog_loop/_proc_starttime/_start_claude_watchdog；类直调 _impl_branch_owned_by_spec/_dispatch_backoffed staticmethod 与类级属性 _rehearsal_probe_done 保持。出处：core/worktree_manager/__init__.py、core/pm_engine/dispatch/__init__.py、core/dashboard/server.py | pass | 0/2 | - |
| web-activities-page | 运维页 /activities 在重构后正常加载：header「运维记录」渲染、视图模式切换控件渲染（data-testid=view-mode-switch）、无 console/网络错误——覆盖 H4/H6 数据被前端消费。出处：core/dashboard/static/config/routes.ts:37（/activities）、core/dashboard/static/src/pages/activities/index.tsx:503（title 运维记录）、:517（view-mode-switch） ｜web 场景 | pass | 0/4 | - |
| web-help-page | 帮助页 /help 在重构后正常加载：「文档目录」卡片区渲染、无 console/网络错误——覆盖 H8 帮助文档数据被前端消费。出处：core/dashboard/static/config/routes.ts:43（/help）、core/dashboard/static/src/pages/help/index.tsx:332（文档目录） ｜web 场景 | pass | 0/3 | - |
| web-spec-detail-hash-route | spec 详情多级 hash 路由 /projects/:name/:spec 在重构后正常加载：进入 /projects/showcase/refactor-giant-classes（或空态 fallback 场景）面包屑三级渲染、页面脚本无 console 错误——验证参数化前端路由与后端 /api/specs/<spec> regex 分派路径。出处：core/dashboard/static/config/routes.ts:23（/projects/:name/:spec）、core/dashboard/static/src/pages/projects/detail.tsx（详情页） ｜web 场景 | pass | 0/5 | - |
| api-spec-detail-doc-error-paths | H3 spec 详情与 spec-doc 端点异常路径语义保持：GET /api/specs/<spec>?project=<不存在>→200 {error:project not found}；GET /api/spec-doc 无 project 参数→400 unknown project；GET /api/spec-doc?project=<不存在>&spec=x&doc=proposal→404——确定性语义验证参数化 regex 路由与 _error 分派。出处：core/dashboard/routes/spec_routes.py:33（_api_spec_detail）、:88（_api_spec_doc） | failed | 2/5 | product-bug |
| api-delete-projects-unknown | DELETE 表驱动分派（_API_DELETE_ROUTES 2 条，独立方法 _handle_api_delete）语义保持：DELETE /api/projects/<不存在> → 404 project not found——确定性验证 DELETE regex 参数化 matcher。出处：core/dashboard/routes/base.py:300（_API_DELETE_ROUTES）、core/dashboard/routes/project_routes.py:_del_project | pass | 0/2 | - |
| cli-module-namespace-patch-guard | 模块命名空间 patch 语义保持（design D3 缝隙清单）：core.worktree_manager 模块属性 subprocess/time 存在（patch('core.worktree_manager.subprocess.run')/patch('core.worktree_manager.time.time') 语义保持）；core.pm_engine.dispatch 模块 time 可重绑；core.dashboard.server 的 HELP_DOCS_DIR/FRAMEWORK_ROOT/MAX_SSE_CONNECTIONS/start_daemon/stop_daemon 命名空间存在（字符串路径 patch 语义保持） | pass | 0/2 | - |
| cli-route-map-entry-count-regression | route-map 生成条目数不减少（design D4/4.6 核心回归断言）：python3 bin/gen-route-map.py 输出条目数 111（重构前后 (path,method) 集合不减少，实测当前条目数 111）。出处：bin/gen-route-map.py:30（scan_server_routes 表驱动+文本 fallback 双级扫描） | pass | 0/3 | - |
| api-help-docs-and-static-root | H8 help_routes 与 H10 静态服务端点语义保持：GET /api/help/docs → 200 {docs:数组}（help_routes.py:33）；GET /（根路径）→ 200 text/html SPA 入口（_serve_static，static_routes.py）——验证伴生类摘出与静态服务通路。出处：core/dashboard/routes/help_routes.py:33、core/dashboard/routes/static_routes.py、core/dashboard/server.py:399（根路径注册） | pass | 0/4 | - |
| api-sse-stream-hello | H9 SSE 通道伴生类摘出后仍工作：SSEConnection/SSEHub 移入 core/dashboard/sse.py（task 4.1 交付物）、_handle_sse 在 sse_routes.py——连接 /api/stream 收集事件，首事件必须为 hello（sse_routes.py:45）。出处：core/dashboard/routes/sse_routes.py:22（_handle_sse）、core/dashboard/sse.py（SSEConnection/SSEHub 伴生类） | pass | 0/2 | - |
| cli-regression-characterization-route-map | 阶段 0 characterization tests（33 用例）+ route-map 专项测试（含 D4 本仓覆盖回归断言 test_repo_api_entries_not_reduced）全部通过（实测 50 passed）——重构后行为锁定与 route-map 扫描源同步验收。出处：tests/test_characterization_giant_classes.py、tests/test_planner_route_map.py | pass | 0/3 | - |


## 断言级豁免清单

以下失败断言被归类为非产品缺陷（不记产品 Bug），逐条列出供人工复核豁免是否掩盖真实缺陷（场景级一句话归因不足以复核）。

| 场景 | 断言 | 归类 | 豁免理由 | 证据 |
| --- | --- | --- | --- | --- |
| web-settings-tab-interaction | no_click_interception [.ant-menu-item:has-text("系 统")] 系统 tab 点击前不被遮挡 | test-defect | 测试用例自身缺陷（非产品缺陷） | 场景缺陷（含 click 步骤同因）：settings 页用 antd Menu（.ant-menu）非 Tabs（.ant-tabs-tab 不存在）；label「系统」二汉字经 autoInsertSpace 渲染为「系 统」亦失配。根因在场景文件选择器，非产品缺陷 |

## 本轮场景集变更

当前稳定场景集共 19 个（第 1 轮）。

- 移除场景 web-activities-help-pages（理由：跨页面断言绑定最终 DOM：activities 断言（运维记录/view-mode-switch）在导航 /help 后被覆盖失效；拆分 web-activities-page + web-help-page 两单页独立场景，覆盖面不变）
- 新增场景 web-help-page（重新规划，第 1 轮）
- 新增场景 web-activities-page（重新规划，第 1 轮）

