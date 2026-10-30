## Deliverables

```yaml
- path: core/dashboard/data/command_center.py
  kind: new
- path: core/dashboard/routes/command_center_routes.py
  kind: new
- path: core/dashboard/server.py
  kind: modify
- path: core/dashboard/static/config/routes.ts
  kind: modify
- path: core/dashboard/static/src/app.tsx
  kind: modify
- path: core/dashboard/static/src/services/dashboard.ts
  kind: modify
- path: core/dashboard/static/src/pages/command-center/index.tsx
  kind: new
- path: core/dashboard/static/src/pages/command-center/OrgGrid.tsx
  kind: new
- path: core/dashboard/static/src/pages/command-center/PipelineBoard.tsx
  kind: new
- path: core/dashboard/static/src/pages/command-center/AdjudicationInbox.tsx
  kind: new
- path: core/dashboard/static/src/pages/command-center/ExecutionLedger.tsx
  kind: new
- path: core/dashboard/static/tests/commandCenter.test.mjs
  kind: new
- path: tests/test_command_center_aggregation.py
  kind: new
- path: core/dashboard/static/dist/index.html
  kind: reference
```

## 1. 后端聚合：KPI 与组织网格

- [x] 1.1 新建 `core/dashboard/data/command_center.py`：模块级静态常量 `ROSTER`（花名册 lane→zone：需求线 planner/spec-review、交付线 implementer/code-fix、质量线 code-review/judge/testing、运营线 administrator/self-review/scan/ocr，未登记 lane 归「其他」）与 `EDGES`（planner→implementer、implementer→code-review、code-review→judge、code-fix→code-review，冻结结构）；实现 7×24h UTC 滚动窗工具与 `aggregate_kpi(registry_projects, project=None)`：四指标按 spec 口径派生（delivered_specs_7d=窗内归档目录名日期前缀 SPEC 数+活跃 pushed 数跨源去重、human_intervention_rate_7d、run_success_rate_7d 复用 classify_run、cost_per_spec_7d 复用既有成本口径；分母 0 → null），`gateway_health` 为网关配置态只读派生（复用既有配置读取路径，输出 configured 与 provider 数；`llm_health` 为按需主动探测工具 MUST NOT 调用）、不发探测请求
- [x] 1.2 同模块实现 `aggregate_org(registry_projects, project=None)`：车道卡=花名册全量（零 run 也出卡）∪ 观测 lane（落「其他」），字段 lane/zone/status（复用 runs.py 在飞判定口径，working/idle）/runs_today（UTC 日界）/success_rate_7d/cost_7d/activity_14d（长度 14 按日计数，mtime 粗筛入窗文件）/last_activity_ts/attributable（最近在飞 run 归属 {project, spec} 或 null，供钻取），响应携带 `edges` 常量与 projects 回显（与 collab-graph 同一注入与筛选模式）
- [x] 1.3 新建 `tests/test_command_center_aggregation.py`：fixture 覆盖 specs 全部 Scenario——四指标混合派生（含出窗归档不计、跨源去重）、分母零 null、花名册卡+未登记 lane「其他」分区、working/idle 状态、edges 两次请求恒等

## 2. 后端聚合：流水线、台账、收件箱与路由

- [x] 2.1 同模块实现 `aggregate_pipeline(registry_projects, project=None)`：跨项目活跃 SPEC 按 STATE.md 原生状态桶映射归五列（drafted←drafted/reviewing；ready←ready；implementing←implementing/bug-found/blocked；verifying←implemented/testing/verified；pushed←done/pushed，覆盖 SpecStatus 全量），卡片携带原生 status，implementing 列卡存在在飞 run 时附 `running`（lane+开始时间），project 筛选与回显同 D1 注入模式
- [x] 2.2 同模块实现 `aggregate_ledger(registry_projects, project=None)`：跨项目最近 50 条 run 按开始时间倒序，字段 project/spec/lane/outcome(classify_run)/duration/tokens/cost/started_at/trigger（调度记录可得则带，不可得置 null 不硬造）
- [x] 2.3 同模块实现 `aggregate_inbox(registry_projects, project=None)`：未终态且带 choices 快照的 admin_alerts 条目，choices 只读告警记录内快照（MUST NOT 回读注册表演进态），narrative 可得则带，严重度降序+created_at 降序，携带 spec/run 溯源字段；纯装配、不新增执行端点
- [x] 2.4 新建 `core/dashboard/routes/command_center_routes.py` 只读 mixin：`GET /api/command-center/{kpi,org,pipeline,ledger,inbox}` 五端点接对应 aggregate 函数（可选 `project` 查询参数），按 base.py H1 表驱动分派链既有模式注册，并在 `core/dashboard/server.py` 导入挂载 mixin
- [x] 2.5 `tests/test_command_center_aggregation.py` 补齐：五列归组+running 附加+项目筛选回显、台账 50 行倒序+trigger=null、收件箱只含未决带快照条目且 choices 与快照逐字段一致+排序

## 3. 前端接入与页面骨架

- [x] 3.1 `core/dashboard/static/src/services/dashboard.ts` 新增五个 API client 函数（commandCenterKpi/Org/Pipeline/Ledger/Inbox，project 可选参数），沿用既有请求封装与类型声明风格
- [x] 3.2 `core/dashboard/static/config/routes.ts` 注册 `/command-center` 路由指向新页面；`core/dashboard/static/src/app.tsx` menuDataRender 增「指挥中心」菜单项（复用既有 antd 图标）
- [x] 3.3 新建 `core/dashboard/static/src/pages/command-center/index.tsx`：四 Tab 骨架（组织总览默认）、各屏数据独立加载与独立错误降级（错误占位+重试按钮，互不拖垮）、60s 常量静默轮询、暗色 antd token 与既有 tailwind 配置复用

## 4. 四屏组件

- [x] 4.1 新建 `OrgGrid.tsx`：部门分区标题+车道卡（状态徽标/今日 run/7 日成功率/14 日静态柱点 sparkline/成本/最近活动时间），汇报线以静态 SVG 细线一次性渲染（禁动画），working 且可归属 SPEC 的卡点击跳 `/projects/:name/:spec`（不可得禁用点击）
- [x] 4.2 新建 `PipelineBoard.tsx`：五列泳道+项目筛选下拉（数据源响应 projects 全集+「全部项目」）、implementing 卡渲染 running lane 与开始时间、卡片点击跳既有详情页
- [x] 4.3 新建 `AdjudicationInbox.tsx`：决策卡（严重度徽标/项目/SPEC/signal_type/narrative 全文/溯源链接/choices 选项组 label+desc），执行调既有 `POST /api/alert-resolve`；destructive 选项执行前二次确认（由选项数据驱动，对齐既有前端回退清单语义）；成功后卡片移出并触发 KPI 刷新；失败保留卡片展示错误可重试；空态「无待人工裁决事项」
- [x] 4.4 新建 `ExecutionLedger.tsx`：KPI 条（四指标+网关状态徽标，null 显示「—」非 0）+台账表格（项目/SPEC/车道/结果/耗时/tokens/成本/开始时间/trigger，null 显示「—」）+项目筛选（与流水线屏同数据源模式）
- [x] 4.5 新建 `core/dashboard/static/tests/commandCenter.test.mjs`（node:test）：纯函数覆盖——sparkline 14 日分桶、null 指标格式化（null→「—」、0 保留）、车道状态→徽标映射、choices 选项 destructive 判定

## 5. 构建与验收

- [x] 5.1 前端构建更新产物（`max build` 成功，新增 command-center 页面 chunk；dist/ 为 gitignore 不入库——锚点即本地构建产物）；python `py_compile` 全过、`tests/test_command_center_aggregation.py` 全绿、前端 node:test 全绿（含既有套件不回归）
- [x] 5.2 以 fixture 项目端到端自验并记录（`.history/` 下冒烟脚本，生产同款 DashboardHTTPServer + dist 静态透传）：五端点对 fixture 返回与 specs Scenario 一致；四屏渲染走查+端点 e2e 代偿（无浏览器环境）：Tab 切换/独立降级/收件箱执行链路以 mock alert-resolve 断言请求体与刷新行为；风格红线核对：汇报线静态 SVG 无动画属性、页面无插画/动画角色元素（组件代码审查记录）；零改动红线：git diff 确认既有 data/routes 模块仅 server.py 注册行新增

## 验证修复（原地打回第 1 轮）

- [x] 先复核失败有效性：逐条核对 `spec/changes/add-command-center/verification-report.md` 中失败场景的期望断言（状态字面量/选择器/前置数据）与产品实际行为是否相符——断言与产品不符属场景缺陷，修场景文件；确属产品行为不符才修产品代码（结论：cc-web-pipeline-filter 断言有效——spec 字面「筛选切换项目后仅剩该项目卡片」，选择器期望 7 与前置种子一致；产品筛选切换不重拉属实 → 真实产品缺陷，与验证链 product-bug 裁决一致）
- [x] 按复核结论修复：场景缺陷改场景文件，真实产品 Bug 改产品代码（commit a69373557：PipelineBoard/ExecutionLedger 把 project 经 refreshKey 传入 useScreenResource 触发筛选切换即时重拉——台账屏为 BUG-1 同源一并修复；useScreen 注释正名）
- [x] 修复后重跑验证确认通过（run 内可跑面全绿：全量 node:test 280/280、pytest 聚合 15/15、npm run build 产出 command-center 页面 chunk、tsc 裸扫 57 处均存量类别；浏览器场景 cc-web-pipeline-filter 由框架验证链复跑终验，证据 .fenix/verify-evidence/add-command-center/impl-repair-round1.json）
