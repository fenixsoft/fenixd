# SPEC 协作拓扑派生端点

<!-- knowledge: capability=topology-derivation rev=1
     sources=spec/archive/2026-10-30-add-spec-topology-bigscreen,spec/archive/2026-10-30-improve-spec-topology-pipeline-view -->

单 SPEC 协作图数据的唯一派生引擎：以既有 timeline/runs 数据源派生 nodes/edges/kpis 下发，前端零拓扑推导；单 SPEC 大屏与跨项目协作图谱共用同一派生结果（ADR-303）。

## 规则

- **只读端点**：`GET /api/specs/<spec>/topology`（与 `/api/specs/<spec>` detail 同族单键寻址）返回 `spec`、`status`、`kpis`、`nodes`、`edges`；节点 `kind` 枚举 `run|verify|user|pm|approve|delivery`（`delivery`=交付终点，`approve` 为其人工批准变体）；边 `type` 枚举 `handoff|dispatch|retry|approve`；活跃与归档 SPEC 均可调用，读侧不区分数据获取路径。派生引擎唯一落点 `core/dashboard/data/topology.py`，以既有 timeline/runs 数据源为唯一输入。
- **角色归列以后端前缀为权威**：run 节点的 `stage`/`lane` 归属由后端按 `run_id` 前缀派生（以 `core/agent_runner/run_files.py` 的 `RUN_ID_AGENT_PREFIXES` 为权威源），七阶段列映射固定——需求（用户/fenix-new、`spec-review-`、`dispute-judge-`）、规划（`planner-`、`planner-plan-`、`planner-judge-`）、开发（`impl-`）、审查/修复（`impl-ocr-`、`repair-`、`code-review-`、`code-fix-`）、测试/验证（`test-`、`verify-`、验证执行节点）、运维（`admin-`）、交付（终点）。spec-review run_id 形态 `spec-review-<spec>-<6hex>-<unix秒>` 的 6 位 uuid 段在 `run_spec_part`（全仓归属单源）剥除，使推断 spec 名与真实 spec 名全等；剥除严格限定该前缀形态，其余前缀（impl-/planner-/code-review- 等，含 spec 名以 9-10 位数字结尾的既有保护样本）推断行为不变。未识别前缀（含不带 spec 段的 `evo-`/`maintenance-`/`review-` 等）落开发列并保留 `role: unknown`，MUST NOT 丢弃节点。
- **KPI 口径**：`kpis` 含 `total_duration`、`total_cost_usd`、`dispatched`、`completed`、`retried` 五项——`dispatched` = 逻辑 run 数（同一次派发的多个 attempt 文件归并为 1）；`retried` = attempt 数 >1 或被弃置（superseded/stale）的 run 数；`completed` = 具备成功终态的 run 数；`total_cost_usd` = 全部 run 不可计价时为 `null`（与 `cost_summary_from_timeline` 同语义，禁输出 0）。
- **重试边仅连 attempt 链**：`type: retry` 边仅连接同一 base run_id 的 attempt 链节点（前缀后缀归并语义与 `strip_run_id_suffixes` 一致）；不同 base run_id 的两次独立重派为 `handoff` 边，MUST NOT 判定为重试。
- **多轮验证逐轮呈现**：验证执行节点按运行日志「开始验证」行逐轮派生（每轮一个节点）；历史轮节点仅含时长、MUST NOT 伪造统计；仅与现存 report.json 配对的末轮节点携带场景通过/失败统计——禁因 timeline 数据源仅保留末轮而把多轮验证呈现为单次。
- **交付终点自适应（不虚构人工动作）**：交付终点按**持久可确证**的人工批准记录自适应——存在持久批准留痕时渲染 `kind: approve` 节点并携带批准时间；无确证记录时（含 fast-track 连跳、自动链推送）渲染普通自动推送终点。pushed 转移 context 恒 `channel="auto"`、人工批准 `approve_push_request.json` 为消费即清的瞬态文件信号、PROJECT_LOG 推送文案无来源区分——存量系统不产生持久批准记录，approve 节点仅在出现持久化批准留痕时才可达，MUST NOT 在无持久确证记录时输出「人工批准」节点。
- **状态转移派生完整性**：PMEngine 状态转移（`transitions`）不得因日志中存在单个超长行而整体为空——锚定窗口（按 created 锚定）必须保证覆盖锚点时刻之后的可解析事件（超长行处置由 [daemon-log-event-governance](../daemon-runtime/daemon-log-event-governance.md) 承载，本能力只约束派生结果完整性）。
- **派发锚点字段**：派生层为 run 首节点附加可选 `dispatch_anchor`（值为归位转移节点 id `tr:<n>`，按 run started 落在转移区间 `[t_i, t_{i+1})` 归位；无法定位时回退 pm 主节点）——供管线视图派发边视觉归位，泳道视图不消费该字段、行为零变化。
- **归档降级骨架**：run 产物已被归档清理的 SPEC 正常返回状态骨架数据（PMEngine 状态转移、验证/运维事件、终点）并携带 `archived: true` 标记与空 run 节点集，MUST NOT 报错；归档链路零改动（不新增归档写路径）。

## 关键行为

消费面：单 SPEC 协作拓扑大屏（管线/泳道双视图，见 [topology-bigscreen-ui](../dashboard-frontend/topology-bigscreen-ui.md)）与跨项目协作图谱聚合（[collab-graph-aggregation](collab-graph-aggregation.md) 逐 SPEC 调用 `derive_topology` 在其结果上聚合）。边语义修正（如并行无伪串行边）在派生层做——前端过滤会造成视图间边集分裂。

## 溯源

- 2026-10-30 add-spec-topology-bigscreen（spec/archive/2026-10-30-add-spec-topology-bigscreen） — 新增本能力：只读派生端点与七阶段角色归列（RUN_ID_AGENT_PREFIXES 权威）、KPI 五项口径、重试边仅连 attempt 链、多轮验证逐轮、交付终点按持久确证自适应、归档降级骨架
- 2026-10-30 improve-spec-topology-pipeline-view（spec/archive/2026-10-30-improve-spec-topology-pipeline-view） — 修订：run_spec_part 单源剥除 spec-review uuid 段（恢复全部 SPEC 的需求评审节点与归属）、状态转移派生完整性约束（锚定窗口不因超长行丢锚点后事件）、新增 dispatch_anchor 派发锚点字段
