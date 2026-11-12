# 指挥中心后端聚合

<!-- knowledge: capability=command-center-aggregation rev=6
     sources=spec/archive/2026-10-31-add-command-center,spec/knowledge/_inbox/done/memory-distill-unspec-landed-rules.md,spec/knowledge/_inbox/done/alert-narrative-generation-chain-retired.md,spec/changes/add-command-center-verify-stats,spec/changes/consolidate-alerts-to-ops-page -->

面向管理层演示叙事（组织、交付、裁决、执行四个切面）的第三块大屏数据面：对 dashboard 托管项目跨项目聚合出 KPI 四指标、组织网格、交付流水线、执行台账与裁决收件箱，全部只读。

## 规则

- **五个只读端点**：`GET /api/command-center/{kpi,org,pipeline,ledger,inbox}`，由 `core/dashboard/routes/command_center_routes.py` mixin 注册；聚合实现单文件 `core/dashboard/data/command_center.py`，跨项目聚合入口沿用 `aggregate_*(registry_projects, project=None)` 注入模式（同构形态沿袭自 topology/collab-graph 先例，两者已分别随 v2 退役与本退役批删除）。端点只读无副作用，本能力 MUST NOT 新增任何裁决执行端点。
- **可选项目筛选**：全部端点支持可选 `project` 参数收窄到单项目；响应回显 `project` 与 `projects` 全集。未知项目返回 200 + `{error: 'project not found'}` 错误字典（大屏按 200 消费的有意契约，非 404）。
- **夹具与失效项目剔除**：缺省跨项目聚合剔除 `fixture=True` 登记项目与路径已不存在（exists=False）的 Registry 条目；夹具项目仅可显式 `project` 寻址。
- **KPI 七日滚动窗口径**：`/kpi` 全部指标基于 7×24 小时滚动窗（UTC，锚定当前时刻），MUST NOT 引入其他口径：
  - `delivered_specs_7d`（7 日交付 SPEC 数）：归档目录名日期前缀（`YYYY-MM-DD-<name>`）落窗的归档 SPEC 数 + 活跃 STATE.md 中 `status=pushed` 条目数，按 SPEC 名跨两源去重；pushed 条目无终态时间戳，不做时间戳猜测，「窗内归档 + 当前 pushed」即口径。
  - `human_intervention_rate_7d`（人工介入率）：窗内 `handled_at` 落窗的人工处置 escalation 告警数 ÷ 窗内终态 run 数；人工路径含 alert-resolve 与「标记已处理」两条，auto-self-heal 收口不计（复用 `get_resolved_alerts` 既有读取口径剔除其自愈部分）。
  - `run_success_rate_7d`（7 日 run 成功率）：窗内 success 终态 run 数 ÷ 窗内（success + failed）终态 run 数，终态判定复用 `classify_run` 既有口径。
  - `cost_per_spec_7d`（单 SPEC 成本）：窗内 run 成本合计（复用 run metric 既有成本口径）÷ `delivered_specs_7d`。
  - 三个比率/均值指标分母为 0 时返回 `null`（0 冒充被禁止），`delivered_specs_7d` 空窗为 0。
- **网关健康为配置态派生**：`/kpi` 响应携带 `gateway_health`（`configured` 布尔 + 已配置 provider 数），复用项目配置只读读取路径；`core.dashboard.llm_health` 是按需主动探测工具、无缓存结果，MUST NOT 调用，KPI 链路 MUST NOT 发起任何网络探测。
- **窗口聚合即时计算**：窗口指标从既有 run 文件与目录名即时聚合，不建预聚合缓存表或定时任务；复用 run metric index 既有 memo 缓存，并按 run 文件 mtime 粗筛入窗文件，窗外文件不读内容。
- **组织网格静态花名册**：`/org` 车道卡按分区（zone）归组，分区与车道花名册为模块级静态常量 ROSTER，MUST NOT 做成用户配置项。预置五线分区：需求线（planner、spec-review）、设计线（planner-plan、planner-judge）、交付线（implementer、code-fix、verifier）、质量线（judge、code-review、self-review）、运营线（administrator、evolution、knowledge-distiller）；testing 与 scan 不出卡（测试在实现/修复 run 内部执行、扫描由代码评审承担，两车道从未派发），ocr 未划线（观测到才落「其他」）。观测到花名册外 lane 归入「其他」分区，编制内外车道都不丢。
- **车道卡字段**：`lane`、`zone`、`status`（`working`=该 lane 存在在飞 run 或在飞验证，复用 runs.py 既有在飞判定；否则 `idle`）、`runs_today`（UTC 日界）、`success_rate_7d`、`cost_7d`、`activity_14d`（长度 14 的按日计数数组，旧→新，run 按开始时间落桶、验证按报告时间戳落桶）、`last_activity_ts`、`attributable`/`attributables`（`{project, spec, run_id}` 归属条目，run_id 可空；不可得 MUST 为 `null`/空，供前端钻取）。花名册内车道即使窗内零活动也出卡。
- **verifier 车道卡双统计源**：org 车道卡统计以 run 文件为基，verifier 卡另折入每项目 `.fenix/verify-progress/` 读侧聚合——新版三段验证流水线（VerifyEngine 进程内执行，无 LLM、无 run 产物）不产 `verify-` 前缀 run 文件，验证活动可见性由该聚合承担。折入只写既有车道卡字段，MUST NOT 新增 org 响应键、MUST NOT 改变既有键语义；MUST NOT 触碰 `verify-` 前缀 run 的任何写路径与消费方（`_cancel_lane_runs`/verify 单飞/admin_monitor 失败计数），也不归并 planner-plan/planner-judge run（其同时服务规划与判定，归并口径失真）。
- **verify-progress 产物两形态**：只认 `<spec>/report.json`（终态验证轮：`{spec, timestamp, summary:{total,passed,warnings,failed,errors}, scenarios}`，每轮原子覆盖、无轮次历史）与 `<spec>.json`（进度摘要：`{total, done, current}`）两类形态；目录内其余文件（顶层杂项与 spec 目录旁产物）MUST 忽略；脏 JSON 或缺 timestamp/summary 关键字段的 SPEC 防御性跳过，不冒异常、不中断聚合。
- **终态轮折入口径**：`runs` 计「窗内有终态验证产物的 SPEC 数」（timestamp 落窗的每个 SPEC 计 1，与 run 计数相加；同 SPEC 多轮仅代表最新轮，MUST NOT 造历史轮次）。`success_rate` 用轮级执行口径：`summary.errors == 0` 记 done、`errors > 0` 记 error，进既有 done/(done+error) 分母；场景级 `failed` 是验证发现的产品缺陷，MUST NOT 计入执行成功率分母。`activity_14d`/`last_activity_ts` 按 report.json `timestamp` 落桶取 max（进度摘要仅作在飞信号、不作活动源），时间戳缺失/脏值跳过该轮活动贡献。
- **在飞验证状态**：进度摘要存在且 `done < total` 且文件 mtime 落 15 分钟新鲜窗（模块常量，对齐 admin_monitor 孤儿判定阈值）→ verifier 卡 `status=working`，`attributables` 含 `{project, spec, run_id: ""}` 条目（started 排序值取进度文件 mtime）；新鲜窗外或 `done == total` 一律不判在飞，与窗口参数无关（同 run 在飞口径的「当下」状态）。在飞条目不计入 runs/success_rate/活动桶（终态产物才计）。
- **verify-progress 归档剔除与读取粗筛**：已归档 SPEC（STATE.archive.md 清单）名下产物在全量窗（`window=all`）同样剔除，与既有 run 剔除口径一致；report.json 正文读取前按 mtime 粗筛（today/7d 窗 mtime 早于 14 日界不读正文，window=all 不限；org 路由无缓存逐请求直调），进度摘要单行小文件恒读。
- **空 run_id 归属容错**：在飞验证归属无 run 文件——`AttributableRun.run_id` 可空，org 卡装配与 `activityLineState` 主路径过滤器均保留空 run_id 条目（spec 空仍剔除）；渲染端将空 run_id 渲染为显名不可点（不开运行记录弹窗、不报错），渲染层零分支。
- **汇报线为静态常量**：`/org` 响应 `edges` 恒为模块常量 4 条：planner→implementer、implementer→code-review、code-review→judge、code-fix→code-review。
- **交付流水线五列桶映射**：`/pipeline` 跨项目收集活跃 SPEC 按五列归组，桶映射 MUST 覆盖 `SpecStatus` 全量（含侧挂 blocked）：`drafted`←{drafted, reviewing}（单证评审属需求阶段）；`ready`←{ready}；`implementing`←{implementing, bug-found, blocked}（侧挂暂停归在制列）；`verifying`←{implemented, testing, verified}；`pushed`←{done, pushed}（终态未归档仍为活跃 SPEC）。每卡携带原生 `status`；implementing 列卡存在在飞 run 时附 `running`（含 lane 与开始时间）。
- **执行台账**：`/ledger` 跨项目最近 50 条 run（LEDGER_CAP=50）按开始时间倒序，每行含 `project`、`spec`、`lane`、`outcome`（classify_run 口径）、`duration`、`tokens`、`cost`、`started_at`、`trigger`；trigger 调度/派发记录不可得时 MUST 为 `null`，MUST NOT 硬造默认值。
- **裁决收件箱只装配**：`/inbox` 收集未终态且告警记录携带 choices 快照的 admin_alerts 条目，按严重度降序、created_at 降序排列；每卡含告警 id、project、spec、run/kind 溯源、signal_type、severity、`narrative`（调查报告槽位内容，仅历史侧车/arbiter 报告已合并时携带，缺失不带该字段、无生成中语义）、`choices`、`created_at`。响应 MUST NOT 携带 `narrative_pending` 字段（告警不存在生成中态）。`choices` MUST 读告警记录内快照，MUST NOT 回读裁决注册表演进态（历史告警不回写语义）；卡片响应定形（additionalProperties false），不携带任何执行动作端点引用，裁决执行唯一通道复用既有 `POST /api/alert-resolve`。

## 代码锚点

- 主实现：`core/dashboard/data/command_center.py`（`aggregate_org` 项目循环折入 + `_verify_progress_stats` 纯函数助读 + `VERIFY_INFLIGHT_FRESHNESS` 常量）
- 前端共享契约：`core/dashboard/static/src/pages/command-center/shared.ts`（`AttributableRun` 类型、`activityLineState` 过滤器）
- 守卫测试：`tests/test_command_center_aggregation.py`（终态折入/在飞/归档防御用例）

## 溯源

- 2026-10-31 add-command-center（spec/archive/2026-10-31-add-command-center） — 新增本能力：五个只读聚合端点（KPI 四指标 7 日窗精确口径、组织网格静态花名册与汇报线常量、流水线五列桶映射覆盖全量 SpecStatus、台账 50 条倒序 trigger 允许 null、收件箱只读装配复用 alert-resolve）
- 2026-11-04 memory-distill-unspec-landed-rules（spec/knowledge/_inbox/done/memory-distill-unspec-landed-rules.md） — 组织网格花名册刷新为现行五线划分（设计线 planner-plan/planner-judge、verifier 入交付线、self-review 归质量线、knowledge-distiller 收编运营线），testing/scan 不出卡、ocr 未划线。
- 2026-11-08 协作拓扑与会话接入退役批（用户指令，无归档 SPEC，登记见 log.md） — 镜像条款收口：聚合入口条款出处口径改历史出处（topology/collab-graph 已删除）
- 2026-11-12 alert-narrative-generation-chain-retired（spec/knowledge/_inbox/done/alert-narrative-generation-chain-retired.md） — 折叠收件箱响应定形收缩（consolidate-alerts-to-ops-page）：`narrative` 仅历史侧车/arbiter 报告已合并时携带，`narrative_pending` 字段退役（无槽位内容的卡不带该字段、无生成中语义）
- 2026-11-12 add-command-center-verify-stats（spec/changes/add-command-center-verify-stats/） — verifier 车道卡折入 verify-progress 读侧聚合：runs 计 SPEC 数、success_rate 轮级执行口径（场景 failed 不进分母）、15 分钟在飞新鲜窗 + 空 run_id 归属条目、归档剔除与脏产物防御；org 响应契约零新增键
- 2026-11-12 consolidate-alerts-to-ops-page（spec/changes/consolidate-alerts-to-ops-page/） — 收件箱响应定形收缩以 SPEC 定案入库：`narrative_pending` 字段退役升格为响应 MUST NOT 携带条款，narrative 仅侧车/arbiter 报告已合并时携带（同时裁定活跃变更 redesign-command-center-ledger 与本能力的 scope 重叠以本定形为准）
