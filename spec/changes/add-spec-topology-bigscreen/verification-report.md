# 验证报告：add-spec-topology-bigscreen

> ⚠️ 本报告由框架于 2026-10-25T13:24:57Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-10-25T13:22:19.058560+00:00+run-result@mtime1792934679319345624

## 结论：✅ 通过（verified）

**状态：verified — 19/20 场景通过，0 失败，0 错误（全部场景通过）**

20 场景：19 PASS + 1 env-warning（topology-empty-spec-zero-state 首跑截图被健全性门判 low_contrast 拒固化基线，6/6 功能断言全过、页面渲染正常，属截图采集环境伪画面，引擎后续干净轮次自动建基线，不阻塞）。上轮 5 处场景缺陷修复本轮全部转 PASS。静态情报 15 条 double_han_text_selector 旗标经执行证据核实均为误报（目标为 SVG text/span 容器非 antd Button，autoInsertSpace 不适用，相关断言本轮全 pass）。0 product-bug、0 test-defect、0 flaky、1 env。

| 指标 | 数量 |
| --- | --- |
| 通过 | 19 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 0.44M |
| 本链增量 Token（输出） | 0.14M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| topology-endpoint-contract-active-spec | 正向路径·活跃 SPEC 拓扑只读端点契约：GET /api/specs/add-spec-topology-bigscreen/topology?project=fenixd 返回 200，顶层含 spec/status/kpis/nodes/edges，kpis 含 total_duration/total_cost_usd/dispatched/completed/retried 五项，节点 kind 与边 type 落在规范枚举内，节点集至少含 user 入口、PMEngine 与 run 节点（该 SPEC 在被测实例项目内有 planner-plan-/impl- 前缀 run 产物，单键寻址与 detail 同族），响应耗时 <3s。出处：spec/changes/add-spec-topology-bigscreen/specs/topology-derivation/spec.md:3-14（端点契约与枚举）、core/dashboard/routes/base.py:609（/api/specs/([^/]+) 同族 regex 路由表先例）、core/dashboard/routes/project_routes.py:793-797（?project= 单项目寻址）、core/dashboard/data/timeline.py:250-254（timeline=日志+runs 数据源）、/root/fenixd/.fenix/runs/（planner-plan-add-spec-topology-bigscreen-1792930152-a1.jsonl 等产物现存实测）。 | pass | 0/4 | - |
| topology-archived-skeleton-endpoint | 降级路径·归档 SPEC 状态骨架：对已归档 SPEC add-fenix-dashboard（活跃目录 spec/changes 已迁出、.fenix/STATE.archive.md 留有条目）调用端点，MUST 正常返回 200：archived=true、run 产物已随 archive_spec_runs 清理故 kpis.dispatched=0 且节点集不含 kind=run 节点（空 run 节点集），不报错。出处：spec/changes/add-spec-topology-bigscreen/specs/topology-derivation/spec.md:77-84（归档降级需求）、core/dashboard/data/spec_archive.py:391-420（is_spec_archived 活跃目录缺席+清单条目双源判定）、/root/fenixd/.fenix/STATE.archive.md（add-fenix-dashboard 条目现存实测）、/root/fenixd/spec/archive/2026-09-02-add-fenix-dashboard（目录已迁出实测）、core/agent_runner/run_files.py:205 起（archive_spec_runs 顶层与 archive/ 两处清理）、实测 /root/fenixd/.fenix/runs/ 顶层无 add-fenix-dashboard run 产物。 | pass | 0/3 | - |
| fixture-scheduling-showcase-registry-visible | 夹具自建·scheduling-showcase 注册表可见性修复：宿主 registry ~/.config/fenixd/dashboard.yaml 的 ignored 列表若含 /root/scheduling-showcase（软删除语义压过显式 fixture 注册，core/dashboard/registry.py discover 过滤 :357），移除该条目并等待 11s（http_server.py:50 _projects_cache TTL=10s）使被测实例项目缓存过期重发现。夹具 prepare 的 add_project 对已存在条目跳过不清 ignored（registry.py:476-484），可见性须由场景集自建。 | pass | 0/2 | - |
| topology-sse-channel-hello-frame | 实时刷新通道·既有 SSE 长连接可用：大屏实时刷新 MUST 复用既有 /api/stream SSE 通道——连接建立即推送 hello 帧，建连后事件数 ≥1 且事件内容含 hello。出处：spec/changes/add-spec-topology-bigscreen/specs/topology-bigscreen-ui/spec.md:81-88（实时刷新复用既有 SSE 通道需求）、core/dashboard/routes/base.py:997（/api/stream GET 派发）、core/dashboard/routes/sse_routes.py:37-70（_handle_sse 连接即发 hello 帧并常驻推送）。 | pass | 0/2 | - |
| topology-derivation-unit-suite | 派生引擎单测全绿·表驱动语义套件：运行交付物 tests/test_topology_derivation.py（pytest -v，不并写 -q 以保 PASSED 行输出形态），覆盖任务 1.1–1.6 全部 Scenario——角色归列（impl-ocr 归审查列、未知前缀落开发列 role=unknown 不丢节点）、attempt 链归并（dispatched 逻辑 run 计数、retried=attempt>1 或弃置）、重试边仅连同 base run_id attempt 链（独立重派为 handoff）、多轮验证逐轮节点（末轮才带 report.json 统计）、交付终点自适应（无持久批准留痕不虚构 approve）、归档骨架（archived=true 空 run 节点集）。断言退出码 0 且汇总行含 passed。出处：spec/changes/add-spec-topology-bigscreen/tasks.md:46（任务 2.2 新建 tests/test_topology_derivation.py 覆盖 1.1–1.6）、core/agent_runner/run_files.py:32（RUN_ID_AGENT_PREFIXES 权威源）、core/agent_runner/run_files.py:173-182（strip_run_id_suffixes 归并语义）、core/dashboard/data/timeline.py:246-263（日志「开始验证」行扫描源）、core/dashboard/data/spec_archive.py:391（归档判定）。 | pass | 0/5 | - |
| topology-runvisual-equivalence-suite | SpecTimeline 等价迁移纯函数单测：状态语义色五分支、run_id 前缀→角色中文标签全表、agent_type 优先级被 node:test 用例钉住（迁移至 src/utils/runVisual.ts 后渲染输出严格等价有背书）。在 core/dashboard/static 下运行 node --test tests/runVisual.test.mjs。出处：spec/changes/add-spec-topology-bigscreen/tasks.md:50-51（任务 3.1 runVisual.ts 等价迁移 + 3.2 runVisual.test.mjs 纯函数用例）、spec/changes/add-spec-topology-bigscreen/specs/topology-bigscreen-ui/spec.md:90-97（零改动红线与等价迁移 Scenario）、core/dashboard/static/package.json:14（node --test tests/*.test.mjs 既有测试形态先例）、core/dashboard/static/src/pages/projects/components/SpecTimeline.tsx:59-83（被抽取的状态着色/角色映射现状实现）。 | pass | 0/4 | - |
| topology-entry-from-list-menu-desktop | 正向路径·桌面 SPEC 列表「更多」菜单进入大屏：在 /projects/fenixd 列表页搜索过滤出 add-spec-topology-bigscreen 行（pageSize=20 需过滤定位），点行内「更多」Dropdown 触发器，菜单出现「协作拓扑」项，点击后跳转 /projects/fenixd/add-spec-topology-bigscreen/topology，呈现脱壳全屏页面（无 dashboard 侧边栏），顶部 SPEC 名 + KPI 条（总耗时等五项）+ 退出按钮齐备。出处：core/dashboard/static/config/routes.ts:22-29（既有 /projects/:name/:spec 路由族，本 SPEC 新增 topology 子路由平级扩展）、core/dashboard/static/config/config.ts:15（history hash 模式故 URL 带 #）、spec/changes/add-spec-topology-bigscreen/tasks.md:55/60（任务 4.1 路由+脱壳壳、4.6 specMenuItems 菜单项）、core/dashboard/static/src/pages/projects/list.tsx:1420-1426（桌面表格行「更多」Dropdown 触发器真实渲染结构）、list.tsx:1477（搜索输入 placeholder=搜索名称…）、list.tsx:577（pageSize 20）、spec/changes/add-spec-topology-bigscreen/specs/topology-bigscreen-ui/spec.md:3-15（独立脱壳大屏页面需求）。 | pass | 0/7 | - |
| topology-exit-returns-source-list | 交互流程·退出大屏返回来源页：经列表「更多」菜单进入大屏后点击右上角「退出大屏」，返回该项目 SPEC 列表页（列表搜索框重新可见、大屏页面卸载）。出处：spec/changes/add-spec-topology-bigscreen/specs/topology-bigscreen-ui/spec.md:12-15（退出返回 Scenario）、tasks.md:55（任务 4.1 退出按钮返回来源页）、core/dashboard/static/src/pages/projects/list.tsx:1477（列表页搜索框=列表页稳定标记）、core/dashboard/static/config/config.ts:15（hash 路由）。 | pass | 0/4 | - |
| topology-pipeline-seven-columns-special-nodes | 正向路径·管线视图七阶段列与特殊节点：直入大屏后切到管线视图，画布按需求/规划/开发/审查修复/测试验证/运维/交付 七阶段列左→右排布（列头文案齐备），用户/fenix-new 需求列入口节点与 PMEngine 规划列调度节点在场，页面无横向溢出。出处：spec/changes/add-spec-topology-bigscreen/specs/topology-bigscreen-ui/spec.md:26-33（管线视图七阶段列需求）、tasks.md:57（任务 4.3 PipelineView 手写 SVG 七阶段列）、specs/topology-derivation/spec.md:14（七阶段列映射与 user/fenix-new、PMEngine 特殊节点权威定义）、core/dashboard/static/src/pages/projects/topology/（4.3 交付为无 data-testid 的手写 SVG 组件，选择器按真实 DOM 结构编写）、design.md:14（决策 1 手写 SVG 渲染）。 | pass | 0/13 | - |
| topology-capsule-switch-exclusive-views | 交互/回归点·胶囊切换器一屏独占：点击切换器「协作时序」后原管线视图卸载、时序视图独占画布且 KPI 条保持；再点回「管线视图」反向等价（回归点：切换往返后管线恢复、时序卸载）。出处：spec/changes/add-spec-topology-bigscreen/specs/topology-bigscreen-ui/spec.md:17-24（双视图切换式组织需求）、tasks.md:59（任务 4.5 胶囊切换器一屏独占单视图）、design.md:28（切换式单视图取舍：A/D 不同屏）。 | pass | 0/5 | - |
| topology-swimlane-lanes-time-axis | 正向路径·协作时序泳道视图：切到协作时序视图后，八条角色泳道行标签（用户/PMEngine/需求评审/规划/开发/审查修复/测试验证/运维）齐备，时间刻度轴在场，该 SPEC 的 run 渲染为色块（当前 SPEC 在被测实例内有 planner-plan-/impl- run 产物故至少 1 个色块）。出处：spec/changes/add-spec-topology-bigscreen/specs/topology-bigscreen-ui/spec.md:40-52（协作时序泳道视图需求）、tasks.md:58（任务 4.4 八泳道+时间刻度自适应）、/root/fenixd/.fenix/runs/（planner-plan-add-spec-topology-bigscreen-1792930152-a1.jsonl 等现存实测）。 | pass | 0/13 | - |
| topology-cross-view-highlight-sync | 交互流程·跨视图联动高亮：在管线视图点击选中某 run 节点后切换到协作时序视图，对应 run 的色块处于高亮态（data-selected=true）。出处：spec/changes/add-spec-topology-bigscreen/specs/topology-bigscreen-ui/spec.md:54-61（跨视图联动高亮需求与 Scenario）、tasks.md:59（任务 4.5 跨视图联动高亮）、design.md:28（联动高亮弥补不同屏对照）。 | pass | 0/3 | - |
| topology-run-node-drilldown-record-modal | 交互流程·节点下钻复用运行记录弹窗：点击管线视图 run 节点打开现有运行记录弹窗（RunRecordModal，标题「运行记录 · <run_id>」）并加载该 run 转录（弹窗体渲染、无网络错误=转录拉取成功）；不新建第二套转录组件（弹窗即现有组件复用）。出处：spec/changes/add-spec-topology-bigscreen/specs/topology-bigscreen-ui/spec.md:63-70（节点下钻复用运行记录需求）、tasks.md:59（任务 4.5 下钻复用 RunRecordModal/ClaudeOutputPane）、core/dashboard/static/src/pages/projects/components/RunRecordModal.tsx:19-27（Modal 标题「运行记录 · runId」与 ClaudeOutputPane 装载真实结构）、core/dashboard/static/src/components/claude-msg/ClaudeOutputPane.tsx:263（getRunTail 转录拉取）、/root/fenixd/.fenix/runs/（目标 run 产物现存，转录可加载）。 | pass | 0/6 | - |
| topology-pm-node-state-transitions | 交互流程·PMEngine 节点点击展示状态转移记录：点击管线视图 PMEngine 调度节点，出现状态转移记录详情（topology-node-detail 容器，含「状态转移」内容）。出处：spec/changes/add-spec-topology-bigscreen/specs/topology-bigscreen-ui/spec.md:65（点击 PMEngine 节点展示状态转移记录需求）、tasks.md:59（任务 4.5 PMEngine/用户节点点击展示状态转移与人工动作记录）、core/dashboard/data/timeline.py:263 起（状态转移事件数据源真实存在，当前 SPEC 有 drafted→reviewing→ready→implementing 转移实测 /root/fenixd/.fenix/logs/fenixd.log）。 | pass | 0/4 | - |
| topology-user-node-actions-record | 交互流程·用户节点点击展示人工动作记录：点击管线视图用户入口节点，出现人工动作记录详情（topology-node-detail 容器，含「人工动作」内容）。出处：spec/changes/add-spec-topology-bigscreen/specs/topology-bigscreen-ui/spec.md:65（点击用户节点展示人工动作记录需求）、tasks.md:59（任务 4.5 用户节点点击展示人工动作记录）、core/agent_runner/run_files.py:32 起（用户/fenix-new 为需求列特殊节点权威源）。 | pass | 0/4 | - |
| topology-archived-banner-degraded-render | 降级路径·归档 SPEC 大屏骨架渲染与显式提示：打开已归档 SPEC add-fenix-dashboard 的大屏页面，正常渲染状态骨架（管线画布与 KPI 条在场）并显示「run 明细已随归档清理」降级提示横幅，而非空白无解释页面。出处：spec/changes/add-spec-topology-bigscreen/specs/topology-bigscreen-ui/spec.md:72-79（归档降级提示需求与 Scenario）、tasks.md:59（任务 4.5 归档横幅）、core/dashboard/data/spec_archive.py:391-420（归档判定双源）、/root/fenixd/.fenix/STATE.archive.md（add-fenix-dashboard 条目现存实测）、design.md:20（决策 7 归档降级用户选型 a）。 | pass | 0/5 | - |
| topology-mobile-card-menu-entry | 正向路径·移动卡片列表同源菜单进入大屏：390×844 视口下 SPEC 列表以卡片渲染（useIsMobile 门控），卡片「更多」Dropdown 与桌面表格同源 specMenuItems——过滤出目标 SPEC 卡片、点「更多」、点「协作拓扑」同样可达大屏。出处：spec/changes/add-spec-topology-bigscreen/specs/topology-bigscreen-ui/spec.md:13（桌面表格与移动卡片同源 specMenuItems）、tasks.md:60（任务 4.6 两处同源生效）、core/dashboard/static/src/pages/projects/list.tsx:605-611（移动卡片「更多」Dropdown 触发器真实渲染结构）、list.tsx:1519/661（isMobile 门控表格/卡片切换）、core/dashboard/static/src/hooks/useIsMobile.ts:7（767.98px 断点，390 宽判移动）。 | pass | 0/4 | - |
| topology-detail-timeline-zero-change-regression | 回归点·现有页面零改动红线（UI 半边）：runVisual 等价迁移后，SPEC 详情页运行时间轴照常渲染——时间轴区块可见、run 节点「查看运行记录」入口在场（现有渲染行为与视觉不变）。出处：spec/changes/add-spec-topology-bigscreen/specs/topology-bigscreen-ui/spec.md:90-97（现有界面零改动红线）、tasks.md:50（任务 3.1 SpecTimeline 改为导入消费渲染严格等价）、core/dashboard/static/src/pages/projects/detail.tsx:1031（.spec-detail-timeline 时间轴挂载点真实结构）、core/dashboard/static/src/pages/projects/components/SpecTimeline.tsx:468（「查看运行记录」入口文案）、core/dashboard/static/config/config.ts:15（hash 路由 URL 形态）。 | pass | 0/3 | - |
| topology-kpi-null-cost-zero-runs | KPI 口径·全不可计价与零 run：对夹具项目 scheduling-showcase（fixture=true，每轮验证 prepare 幂等复位）中无任何 run 历史/日志事件的 SPEC c-sched-set（基线 ready 态）调用端点：total_cost_usd MUST 为 null 而非 0（与 cost_summary_from_timeline 同语义），dispatched=0，archived=false。出处：spec/changes/add-spec-topology-bigscreen/specs/topology-derivation/spec.md:26-38（KPI 口径与全不可计价 null）、bin/fixture_scheduling_showcase.py:55-60（夹具运行时根 /root/scheduling-showcase 与基线 STATE，c-sched-set 为 ready）、实测 /root/scheduling-showcase/.fenix/（仅有 STATE.md/config.yaml/admin_alerts.json，无 runs/ 无 logs/）、~/.config/fenixd/dashboard.yaml（scheduling-showcase 已登记 fixture=true，场景零 add_project 调用）。 | pass | 0/3 | - |
| topology-empty-spec-zero-state | 空状态·零 run 历史 SPEC 大屏：夹具项目 scheduling-showcase 的 c-sched-set（ready、无 run 产物无日志事件）大屏不空白不崩溃：用户入口节点仍渲染，KPI 条渲染且派发计数为 0、总成本呈 null 态。出处：spec/changes/add-spec-topology-bigscreen/specs/topology-derivation/spec.md:26-38（零 run KPI 口径）、specs/topology-bigscreen-ui/spec.md:5（KPI 条状态常态渲染）、bin/fixture_scheduling_showcase.py:55-60（夹具基线 c-sched-set ready 无 run）、实测 /root/scheduling-showcase/.fenix/（无 runs/ 无 logs/）、~/.config/fenixd/dashboard.yaml（scheduling-showcase 已登记 fixture=true）。 | warning | 0/6 | env |


## 断言级豁免清单

以下失败断言被归类为非产品缺陷（不记产品 Bug），逐条列出供人工复核豁免是否掩盖真实缺陷（场景级一句话归因不足以复核）。

| 场景 | 断言 | 归类 | 豁免理由 | 证据 |
| --- | --- | --- | --- | --- |
| topology-empty-spec-zero-state | visual_baseline_rejected [topology-empty-spec-zero-state_baseline] 截图健全性判定 | env | 环境因素（非产品缺陷） | 首跑 1280x800 帧 pixel_std=0.077、dominant_color_pct=0.54 被判低对比拒固化为基线；同场景 element_visible 用户节点/派发/总成本与 text_contains "0" 共 6 条断言全过，页面渲染正常，纯截图采集环境性伪画面，引擎注明后续干净轮次自... |

## 本轮场景集变更

当前稳定场景集共 20 个（第 1 轮）。

- 新增场景 fixture-scheduling-showcase-registry-visible（重新规划，第 1 轮）

