## ADDED Requirements

### Requirement: 拓扑只读端点

后端 MUST 提供只读端点 `GET /api/specs/<spec>/topology`（与 `/api/specs/<spec>` detail 同族单键寻址），返回派生图数据：`spec`、`status`、`kpis`、`nodes`、`edges`。节点 `kind` 枚举 `run|verify|user|pm|approve|delivery`（`delivery`=交付终点，`approve` 为其人工批准变体）；边 `type` 枚举 `handoff|dispatch|retry|approve`。派生逻辑 MUST 位于 `core/dashboard/data/topology.py`，以既有 timeline/runs 数据源为唯一输入，前端零拓扑推导。端点对活跃与归档 SPEC 均可调用，读侧 MUST NOT 区分数据获取路径。

#### Scenario: 正常 SPEC 派生完整图

- **WHEN** 对一个经历「创建→评审→规划→开发→审查→验证→pushed」的活跃 SPEC 调用端点
- **THEN** 返回的 nodes 含用户入口节点、PMEngine 节点、各 agent run 节点与交付终点节点，edges 表达派发与交接关系，kpis 含五项指标

### Requirement: 角色归列映射以后端前缀为权威

run 节点的 `stage`/`lane` 归属 MUST 由后端按 `run_id` 前缀派生（以 `core/agent_runner/run_files.py` 的 `RUN_ID_AGENT_PREFIXES` 为权威源），七阶段列映射固定为：需求（用户/fenix-new、`spec-review-`、`dispute-judge-`）、规划（`planner-`、`planner-plan-`、`planner-judge-`）、开发（`impl-`）、审查/修复（`impl-ocr-`、`repair-`、`code-review-`、`code-fix-`）、测试/验证（`test-`、`verify-`、验证执行节点）、运维（`admin-`）、交付（终点）。未识别前缀（含不带 spec 段的 `evo-`/`maintenance-`/`review-` 等）MUST 落入开发列并保留 `role: unknown`，MUST NOT 丢弃节点。

#### Scenario: impl-ocr 归审查列

- **WHEN** 存在 run_id 前缀为 `impl-ocr-` 的 run 节点
- **THEN** 该节点 stage 为审查/修复列，role 为代码审查

#### Scenario: 未知前缀不丢节点

- **WHEN** 存在无法识别前缀的 run 节点
- **THEN** 节点保留并归入开发列，role 为 unknown

### Requirement: KPI 口径

`kpis` MUST 含 `total_duration`、`total_cost_usd`、`dispatched`、`completed`、`retried` 五项。口径：`dispatched` = 逻辑 run 数（同一次派发的多个 attempt 文件归并为 1）；`retried` = attempt 数 >1 或被弃置（superseded/stale）的 run 数；`completed` = 具备成功终态的 run 数；`total_cost_usd` = 全部 run 不可计价时 MUST 为 `null`（与 `cost_summary_from_timeline` 同语义）。

#### Scenario: 同一派发多 attempt 归并计数

- **WHEN** 某次派发的 run 产物含 base run_id 相同的 3 个 attempt 文件
- **THEN** `dispatched` 对该派发计 1，`retried` 对该 run 计 1

#### Scenario: 全不可计价时成本为 null

- **WHEN** SPEC 全部 run 均无 cost 数据
- **THEN** `total_cost_usd` 为 `null` 而非 `0`

### Requirement: 重试边仅连 attempt 链

`type: retry` 边 MUST 仅连接同一 base run_id 的 attempt 链节点（前缀后缀归并语义与 `strip_run_id_suffixes` 一致）；不同 base run_id 的两次独立重派 MUST 为 `handoff` 边，MUST NOT 判定为重试。

#### Scenario: attempt 链连重试边

- **WHEN** base run_id 相同的两个 attempt 节点先后出现
- **THEN** 两节点间为 retry 边

#### Scenario: 独立重派不连重试边

- **WHEN** 同角色两个 base run_id 不同的 run 先后出现（后次为人工/自动重派）
- **THEN** 两节点间为 handoff 边，非 retry

### Requirement: 多轮验证逐轮呈现

验证执行节点 MUST 按运行日志中的「开始验证」行逐轮派生（每轮一个节点）；历史轮节点仅含时长，MUST NOT 伪造统计；仅与现存 report.json 配对的末轮节点携带场景通过/失败统计。MUST NOT 因 timeline 数据源仅保留末轮而把多轮验证呈现为单次。

#### Scenario: 两轮验证出两个节点

- **WHEN** 运行日志含两行「开始验证」且 report.json 为末轮产物
- **THEN** 返回两个验证执行节点，仅末轮含统计字段

### Requirement: 交付终点自适应

交付终点节点（`kind: delivery`）MUST 按**持久可确证**的人工批准记录自适应：存在持久批准留痕时渲染 `kind: approve` 节点并携带批准时间；无确证记录时（含 fast-track 连跳、自动链推送）MUST 渲染普通交付终点（`自动推送` 语义）。注意实测：pushed 转移 context 恒 `channel="auto"`（`core/pm_engine/engine.py` transition 调用）、人工批准 `approve_push_request.json` 为消费即清的瞬态文件信号、PROJECT_LOG 推送文案无来源区分——当前系统不产生持久批准记录，故 approve 节点仅在出现持久化批准留痕时才可达。MUST NOT 在无持久确证记录时输出「人工批准」节点。

#### Scenario: 人工批准出 approve 节点

- **WHEN** 存在持久可确证的人工批准留痕（如批准信号的持久化记录）
- **THEN** 交付节点 kind 为 approve 且含批准时间

#### Scenario: fast-track 不虚构人工批准

- **WHEN** SPEC 经 fast-track 连跳 done→pushed、无任何人工批准动作
- **THEN** 交付节点为自动推送终点，无 approve 节点

### Requirement: 归档 SPEC 降级骨架

对 run 产物已被归档清理（`archive_spec_runs`）的 SPEC，端点 MUST 正常返回状态骨架数据（PMEngine 状态转移、验证/运维事件、终点）并携带 `archived: true` 标记与空 run 节点集；MUST NOT 报错。归档链路行为 MUST 保持零改动（不新增归档写路径）。

#### Scenario: 归档 SPEC 返回骨架

- **WHEN** 对已归档 SPEC 调用端点
- **THEN** 返回 `archived: true`、run 节点为空、状态转移与运维事件保留
