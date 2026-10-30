## Deliverables

```yaml
- path: core/dashboard/data/topology.py
  kind: new
- path: core/dashboard/routes/topology_routes.py
  kind: new
- path: core/dashboard/server.py
  kind: modify
- path: core/dashboard/static/config/routes.ts
  kind: modify
- path: core/dashboard/static/src/services/dashboard.ts
  kind: modify
- path: core/dashboard/static/src/pages/projects/list.tsx
  kind: modify
- path: core/dashboard/static/src/pages/projects/topology/index.tsx
  kind: new
- path: core/dashboard/static/src/pages/projects/topology/PipelineView.tsx
  kind: new
- path: core/dashboard/static/src/pages/projects/topology/SwimlaneView.tsx
  kind: new
- path: core/dashboard/static/src/utils/runVisual.ts
  kind: new
- path: core/dashboard/static/src/pages/projects/components/SpecTimeline.tsx
  kind: modify
- path: core/dashboard/static/tests/runVisual.test.mjs
  kind: new
- path: tests/test_topology_derivation.py
  kind: new
- path: core/dashboard/static/dist/index.html
  kind: reference
```

## 1. 后端拓扑派生引擎

- [x] 1.1 新建 `core/dashboard/data/topology.py`：`derive_topology` 以既有 timeline/runs 数据源为唯一输入产出 `nodes/edges/kpis/archived`；角色归列按 `core/agent_runner/run_files.py` 的 `RUN_ID_AGENT_PREFIXES` 权威源执行七阶段列映射（需求=用户+spec-review+dispute-judge / 规划=planner 族 / 开发=impl / 审查修复=impl-ocr+repair+code-review+code-fix / 测试验证=test+verify+验证执行 / 运维=admin / 交付=终点）；未知前缀落开发列 `role: unknown` 不丢节点
- [x] 1.2 attempt 链归并与 KPI 口径：按 `strip_run_id_suffixes` 语义归并同 base run_id；`dispatched`=逻辑 run 数、`retried`=attempt>1 或 superseded/stale 数、`completed`=成功终态数、全不可计价时 `total_cost_usd=null`
- [x] 1.3 重试边判定：仅同 base run_id 的 attempt 链节点间连 `retry` 边；不同 base run_id 的独立重派一律 `handoff` 边
- [x] 1.4 多轮验证派生：扫运行日志「开始验证」行逐轮产出验证执行节点，历史轮仅含时长，末轮（与现存 report.json 配对）携带场景通过/失败统计
- [x] 1.5 交付终点自适应：以**持久可确证**的人工批准记录判定——无确证记录（fast-track 连跳/自动链推送，实测 pushed 转移 context 恒 `channel="auto"`、`approve_push_request.json` 信号消费即清、PROJECT_LOG 文案无来源区分）时产出 `kind: delivery`「自动推送」普通终点；仅在存在持久批准留痕时产出 `kind: approve` 节点（含批准时间），无持久确证记录 MUST NOT 产出 approve 节点
- [x] 1.6 归档降级：run 产物已被 `archive_spec_runs` 清理时正常返回状态骨架（PMEngine 状态转移/验证/运维事件）+ `archived: true` + 空 run 节点集，不报错；归档链路自身零改动

## 2. 后端端点与单测

- [x] 2.1 新建 `core/dashboard/routes/topology_routes.py`：只读端点 `GET /api/specs/<spec>/topology`（与 `/api/specs/<spec>` detail 同族单键寻址，在 `base.py` `_API_GET_ROUTES` regex 表新增条目，复用现有鉴权/sig 与宿主约定），`core/dashboard/server.py` 以 Mixin 方式接入
- [x] 2.2 新建 `tests/test_topology_derivation.py`：表驱动覆盖任务 1.1–1.6 对应全部 Scenario（含归档 fixture、多轮验证 fixture、attempt 链与独立重派 fixture、未知前缀兜底、全不可计价 null）

## 3. 前端共享常量等价迁移

- [x] 3.1 新建 `core/dashboard/static/src/utils/runVisual.ts`：将 `SpecTimeline.tsx` 的状态语义色五分支与角色中文名/`run_id` 前缀映射抽为纯函数与常量；`SpecTimeline.tsx` 改为导入消费，渲染输出严格等价（禁止嵌套三元等 lint 规则照守）
- [x] 3.2 新建 `core/dashboard/static/tests/runVisual.test.mjs`：node:test 纯函数用例钉住等价性（状态→色全分支、前缀→角色标签全表、agent_type 优先级）

## 4. 大屏页面与双视图

- [x] 4.1 `core/dashboard/static/config/routes.ts` 新增 `/projects/:name/:spec/topology` 路由；新建 `core/dashboard/static/src/pages/projects/topology/index.tsx`：脱壳全屏深色壳（无 dashboard 框架侧边栏）、顶部 SPEC 名 + KPI 条 + 退出按钮（返回来源页）
- [x] 4.2 `core/dashboard/static/src/services/dashboard.ts` 新增 `getSpecTopology` 与拓扑数据类型定义
- [x] 4.3 新建 `core/dashboard/static/src/pages/projects/topology/PipelineView.tsx`：手写 SVG 七阶段列布局、handoff/retry/approve 三类边着色、在飞节点发光脉冲、失败/中止/弃置状态着色（消费 runVisual 常量）、`fix-*` 🔧 角标、验证执行节点、节点悬浮详情卡（角色/run_id/状态/LLM/耗时/成本/重试）
- [x] 4.4 新建 `core/dashboard/static/src/pages/projects/topology/SwimlaneView.tsx`：手写 SVG 八泳道时序（用户/PMEngine/需求评审/规划/开发/审查修复/测试验证/运维）、时间刻度自适应、run 色块宽度=耗时且并行错行、PMEngine 派发标记与状态转移刻度、跨泳道交接箭头、长跨度横向滚动或缩放
- [x] 4.5 `index.tsx` 编排：胶囊切换器（一屏独占单视图）、跨视图联动高亮、SSE 失效全量重拉（不可用时 30s 轮询兜底）、归档 SPEC「run 明细已随归档清理」横幅、run 节点点击下钻复用 `RunRecordModal`/`HarnessBrandProvider`、PMEngine/用户节点点击展示状态转移与人工动作记录
- [x] 4.6 `core/dashboard/static/src/pages/projects/list.tsx`：`specMenuItems` 新增「协作拓扑」导航项（桌面表格与移动卡片两处同源生效），仅导航不弹窗

## 5. 构建与验收

- [x] 5.1 前端构建更新产物（`max build` 成功，新增 `p__projects__topology__index` chunk，dist/ 为 gitignore 不入库——锚点即本地构建产物；python `py_compile` 全过、pytest 相关套件 180+28 全绿、前端 node:test 261 全绿；仓库无 eslint/ruff 配置，lint 以编译检查代偿）
- [x] 5.2 以 fixture 项目端到端自验并记录（`.history/e2e_topology_smoke.py`，生产同款 DashboardHTTPServer + dist 静态透传，25 项检查全绿）：活跃 SPEC 端点 KPI（dispatched=3 attempt 链归并 / retried=1 / completed=2 / cost=null / total_duration=1380 同 `_spec_total_duration` 口径）、attempt 链 retry 边、在飞 a2、fix 🔧、双验证节点末轮统计；归档 archived=true 骨架+转移保留；未知 spec 200+error。UI 交互（视图切换/联动/下钻）以代码走查+端点 e2e 代偿（无浏览器环境）：selectedId 单源共享双视图、RunRecordModal 复用、退出返回列表路由、归档横幅条件渲染。零改动红线：git diff 确认 detail.tsx/spec_routes.py/spec_archive.py 零改动，SpecTimeline.tsx 仅常量/纯函数等价迁移（+20/−83，渲染 JSX 语义零变化）
