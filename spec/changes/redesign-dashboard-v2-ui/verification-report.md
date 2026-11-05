# 验证报告：redesign-dashboard-v2-ui

> ⚠️ 本报告由框架于 2026-11-05T10:14:18Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-11-05T10:14:17.052095+00:00+run-result@mtime1793873657099443305

## 结论：✅ 通过（verified）

**状态：verified — 27/27 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 27/27 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 27 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 22.27M |
| 本链增量 Token（输出） | 0.26M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| v2-overview-reachable | /v2/overview 经 v2 路由前缀可达并按 Bento 原型渲染：.v2-page 壳 + 四 KPI 磁贴标签（SPEC 总数/任务进度/Token 消耗/活跃 Agent）+ 项目清单磁贴，消费真实 /api/overview 数据（出处 core/dashboard/static/config/routes.ts:80、core/dashboard/static/src/pages/v2/overview.tsx:238,279,300,318,643,668） | pass | 0/11 | - |
| v2-overview-search-empty-state | 概览项目清单搜索无命中时表格落 antd 空状态占位行、项目行消失，输入框值回读正确（出处 core/dashboard/static/src/pages/v2/overview.tsx:649,676） | pass | 0/4 | - |
| v2-overview-search-hit-and-run-filter | 搜索 fenixd 命中真实项目行，切换「运行中」分段过滤后项目行仍可见（真实 /api/overview 数据驱动；出处 core/dashboard/static/src/pages/v2/overview.tsx:649,663,676） | pass | 0/4 | - |
| v2-overview-row-nav | 点击项目行进入 /v2/projects/<name> 项目详情（pd-panel 磁贴落地），点击窗口内触发 /api/specs 列表拉取（出处 core/dashboard/static/src/pages/v2/overview.tsx:677-679、core/dashboard/static/src/services/dashboard.ts:711）；前置直达导航预暖 p__v2__projectDetail 懒加载 chunk，消除行点击窗口静默收窗（300ms）与异步 chunk 挂载取数的竞态（出处 core/verify_engine/browser.py:66，修复式同 v2-project-detail-row-to-spec） | pass | 0/5 | - |
| v2-overview-dropdown-menu-contents | 项目行三点下拉菜单仅含 停止/安装托管/删除 三项且删除为 danger 项（菜单保持展开态收尾计数；出处 core/dashboard/static/src/pages/v2/overview.tsx:606-612,624） | pass | 0/6 | - |
| v2-overview-delete-abort | 三点下拉点「删除」弹 antd 确认框（danger 确认钮），点取消后不执行删除、项目行仍在、无网络错误（回归点闭环；出处 core/dashboard/static/src/pages/v2/overview.tsx:521-529,612） | pass | 0/6 | - |
| legacy-overview-unchanged | 既有 #/overview 路由零改动回归：统一标题栏原版页头（标题「跨项目概览」）渲染、v2 壳不出现（出处 core/dashboard/static/config/routes.ts:11、core/dashboard/static/src/pages/overview/index.tsx:214） | pass | 0/4 | - |
| v2-unmatched-path-fallback | 未实现的 #/v2/* 路径落既有 '*' 兜底重定向到概览页，不产生空白页、v2 壳不出现（出处 core/dashboard/static/config/routes.ts:106-108） | pass | 0/4 | - |
| prod-menu-zero-pollution | v2 页面下现产侧栏菜单逐字不变：白名单六项（概览/项目/配置/运维/指挥中心/帮助）可见、顶级菜单项计数不增（无 v2 条目混入）（出处 core/dashboard/static/src/app.tsx:103、core/dashboard/static/config/routes.ts:76-78） | pass | 0/7 | - |
| v2-project-detail-table-filter | /v2/projects/fenixd 直达：SPEC 表真实列集（优先级/创建时间/耗时等）渲染，名称搜索 redesign-dashboard 命中真实 SPEC 行（出处 core/dashboard/static/config/routes.ts:90、core/dashboard/static/src/pages/v2/projectDetail.tsx:277,315） | pass | 0/7 | - |
| v2-project-detail-tabs-placeholder | 项目详情四页签：功能开发实体渲染，代码审查/测试回归/会话接入占位说明如实声明（原型示意页签），页签切换不被拦截（出处 core/dashboard/static/src/pages/v2/projectDetail.tsx:387-406） | pass | 0/5 | - |
| v2-project-detail-row-to-spec | 点击 SPEC 行进入 v2 SPEC 详情（sd-panel 落地 + 状态转移按钮 + 返回箭头），点击窗口内触发 /api/specs/<spec> 详情拉取，返回箭头回到项目详情（出处 core/dashboard/static/src/pages/v2/projectDetail.tsx:315、core/dashboard/static/src/pages/v2/specDetail.tsx:709,723、core/dashboard/static/src/services/dashboard.ts:1253）；前置直达导航预暖 specDetail 懒加载 chunk，消除行点击窗口静默收窗（300ms）与异步 chunk 挂载取数的竞态（出处 core/verify_engine/browser.py:66） | pass | 0/4 | - |
| v2-spec-detail-info-tasks-timeline | 直达 /v2/projects/fenixd/redesign-dashboard-v2-ui：项目信息 8 项（优先级/创建时间/更新时间/依赖/输入 Token/输出 Token/耗时/成本）、任务清单大百分比卡（已完成 N/M）、运行时间轴（立项原话 + run 元数据）、完整模式徽标与状态转移入口（出处 core/dashboard/static/config/routes.ts:86、core/dashboard/static/src/pages/v2/specDetail.tsx:114-121,179,268,702,723） | pass | 0/16 | - |
| v2-spec-detail-tabs-hook | SPEC 详情页签巡游：场景结果/Bug 列表/测试截图/Hook 页签实体渲染，Hook 页签激活窗口内触发 /api/hooks/audit 拉取（出处 core/dashboard/static/src/pages/v2/specDetail.tsx:767-770、core/dashboard/static/src/services/dashboard.ts:2714）；当前环境 hook 审计为空（端点实况 audit=[]），磁贴断言按空态契约修复（原数据态断言依赖带外数据无夹具） | pass | 0/5 | - |
| v2-settings-llm-panel | /v2/settings：左侧 11 分面菜单 + 模型与网关实体面板（Provider 表：网关地址/默认模型/健康列 + 健康检测/编辑按钮）+ 真实 config 开关行（aria 作用域标注、可操作），零写操作（出处 core/dashboard/static/config/routes.ts:94、core/dashboard/static/src/pages/v2/settings.tsx:25,74-87,104-108,224） | pass | 0/13 | - |
| v2-settings-scope-switch-menu | 作用域切到项目级 fenixd 触发 /api/config?project= 重拉、开关行 aria 标注切「项目级」；左侧菜单切「角色模型」分面显示占位说明（该分面在 v2 域尚未展开）（出处 core/dashboard/static/src/pages/v2/settings.tsx:236,280-281,311）；aria 项目级断言拆分至 v2-settings-scope-aria-label（断言在步骤后统一执行，本场景收尾停留占位分面时 LLM 面板已卸载，两断言所需 DOM 态互斥） | pass | 0/5 | - |
| v2-help-toc-doc | /v2/help 双栏：分组目录（README→总览、NN- 编号→使用手册）+ 正文磁贴渲染；点击手册目录项后 on 选中态与 aria-current 同步切换（出处 core/dashboard/static/config/routes.ts:98、core/dashboard/static/src/pages/v2/help.tsx:34-36,64-65） | pass | 0/9 | - |
| v2-ops-stats-alerts | /v2/activities 运维页：头部统计条四项真实口径（待处理告警/在飞链/升级中/配额耗尽）+ 默认人工告警页签磁贴渲染（出处 core/dashboard/static/config/routes.ts:102、core/dashboard/static/src/pages/v2/ops.tsx:32-35,263,273） | pass | 0/9 | - |
| v2-ops-chain-observations | 处置链观测页签：在飞链/升级件/签名配额三段计数小节渲染（真实 getChainOverview 数据；出处 core/dashboard/static/src/pages/v2/ops.tsx:209-226,309） | pass | 0/6 | - |
| v2-ops-auto-placeholder | 自愈记录页签：占位说明如实声明（自愈记录分面暂无数据端点）（出处 core/dashboard/static/src/pages/v2/ops.tsx:312-314） | pass | 0/4 | - |
| v2-routes-guard-node-test | routes 快照守卫测试通过：既有条目逐字钉死、v2 六条齐备且不写 name/icon、menuDataRender 白名单零 v2 条目（node --test 四用例全过零败；出处 core/dashboard/static/tests/v2RoutesGuard.test.mjs:1） | pass | 0/3 | - |
| v2-theme-single-source-audit | v2 主题单源审计：theme.tsx Bento token 常量齐备（V2_BG/V2_PRIMARY/V2_LINK/ramp/胶囊圆角）、v2 域内零 import 现产 theme、v2 域外零文件引用 v2 主题（例外域隔离；出处 core/dashboard/static/src/pages/v2/theme.tsx:16-54、core/dashboard/static/src/pages/v2/v2.less:3） | pass | 0/4 | - |
| v2-build-and-dist-chunk | npm run build 构建成功且 dist 产物含 v2 域标记（页面 data-proto-id 与 Bento 表格 fixed 布局 CSS 落产物）（出处 core/dashboard/static/src/pages/v2/v2.less:63-64、spec/changes/redesign-dashboard-v2-ui/tasks.md 4.1） | pass | 0/4 | - |
| v2-design-md-amendment | DESIGN.md 同步增补审计：含「例外域：v2 商业化界面域」小节与 Bento token 值登记，既有章节（红线/通用条款/一般域/待裁决段）未删（出处 DESIGN.md:120、spec/changes/redesign-dashboard-v2-ui/tasks.md 3.1） | pass | 0/3 | - |
| v2-deliverables-ledger | 交付物对账：tasks.md Deliverables 声明的 v2 六页面族/theme/routes 修改/DESIGN.md/dist 入口全部落地存在（出处 spec/changes/redesign-dashboard-v2-ui/tasks.md Deliverables 段） | pass | 0/12 | - |
| v2-consumed-endpoints-health | v2 页面族消费的既有端点健康：/api/overview、/api/specs?project=、/api/config、/api/chain、/api/help/docs 均 200 且返回 JSON 对象（出处 core/dashboard/static/src/services/dashboard.ts:321,627,711,2235,2737） | pass | 0/10 | - |
| v2-settings-scope-aria-label | /v2/settings 作用域切到项目级 fenixd 后开关行 aria 作用域标注同步为「项目级」（/api/config?project= 重拉断言；拆分自 v2-settings-scope-switch-menu——原场景断言排在切走分面之后，LLM 面板已卸载致断言时序错置） | pass | 0/3 | - |

## 本轮场景集变更

场景集与持久化集一致，无变更。

