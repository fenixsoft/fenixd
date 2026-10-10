# phantom-running-guard 规格

## ADDED Requirements

### Requirement: 弃置终态不计为在跑

日报 runs 统计（collect_runs_stats）MUST 将产物末行为 superseded 终态的 run 计入独立桶位 superseded（弃置/重试件），MUST NOT 计入 running，MUST NOT 计入 succeeded。

#### Scenario: 原地重试弃置件不被计为在跑

- **WHEN** 某 run 产物末两行为 transient_retry + superseded（原地重试弃置旧产物，2026-10-09T19:01Z 实拍形态）
- **THEN** _classify_run 返回 category=superseded
- **AND** 日报第 2 节「在跑/无终态」计数不含该 run，「弃置/重试件」计数含该 run

### Requirement: 其他终结终态不计为在跑

产物末行为 interrupted、cancelled、frozen-terminated 或 gate-blocked 的 run MUST 计入独立桶位 ended，MUST NOT 计入 running 或失败样本。

#### Scenario: 被取消的 run 不被计为在跑

- **WHEN** 某 run 产物末行为 type: cancelled（取消路径最后落盘，runner.py:6557）
- **THEN** _classify_run 返回 category=ended，detail 含原 type 词
- **AND** 该 run 不进入 collect_failed_run_samples 失败样本

### Requirement: 终态词表单源

_classify_run 的终态识别集合 MUST 引用 core.dashboard.data.runs.RUN_TERMINAL_STATUS_MAP（或其键集），MUST NOT 复制定义新词表；MUST NOT 消费 core.agent_runner.liveness.RUN_TERMINAL_EVENT_TYPES（该集合故意排除 superseded，防退避窗口双派发，语义为存活判定而非事后统计）。

#### Scenario: 词表演进单点生效

- **WHEN** 框架未来在 RUN_TERMINAL_STATUS_MAP 新增终态 type
- **THEN** self_review 侧分类无需改动即不将其误计为 running

### Requirement: 残余无终态的 stale 对账

对末行非任何已知终态（running 判定）的 run，统计侧 MUST 按双源对账细分：产物 mtime 距统计时刻超过 RUN_STALE_SECONDS 且 _run_terminal_success 未返回 True → 计 stale（无终态残留）；查得 terminal=success → 计 succeeded；mtime 新鲜 → 维持 running 不改判。「未返回 True」= None（指标索引查无）或 False（查得非 success 终态——run_metrics 的 terminal 值域为 success/failure/frozen/cancelled/circuit，runner.py:8226 写入，:3660/:4649/:4691/:5096 为各非 success 值写入点）；非 success 终态 MUST NOT 按成功提升，MUST NOT 改计 failed（失败样本口径以产物 marker/信号为归因源，指标侧无归因 detail，改计将造成计数与失败样本分叉），同走 stale 通道。对账遵循「宁可不拦不可误伤」：数据缺失不改判。

#### Scenario: 陈旧断尾产物单列为 stale

- **WHEN** 某 run 产物末行非终态、mtime 停更超 1800s、fenixd.log run_metrics 无该 run 终态
- **THEN** 该 run 计入 stale 桶，日报渲染为「无终态残留」

#### Scenario: 指标记非 success 终态而产物断尾按 stale 通道处理

- **WHEN** 某 run 产物末行非终态、mtime 停更超 RUN_STALE_SECONDS、run_metrics 记 terminal="failure"（或 cancelled/frozen/circuit）
- **THEN** 该 run 计入 stale 桶，MUST NOT 改计 failed，MUST NOT 按成功提升计 succeeded

#### Scenario: 指标有终态而产物断尾按终态计

- **WHEN** 某 run 产物末行非终态（如 daemon 崩溃截断）但 run_metrics 记录 terminal=success
- **THEN** 该 run 计入 succeeded，不混入在跑

#### Scenario: 新鲜无终态维持在跑判定

- **WHEN** 某 run 产物末行非终态且 mtime 停更不足 RUN_STALE_SECONDS
- **THEN** 该 run 维持计 running（真实在跑或近瞬状态，不做对账改判）

### Requirement: 日报第 2 节口径透明

collect_daily_summary 第 2 节 MUST 渲染新增桶位行（弃置/重试件、其他终态、无终态残留），「在跑/无终态」行保留且语义收窄为「末行非任何已知终态且未触发 stale 对账改判」。计数桶 key 与渲染 MUST 同步扩展，新 category 落 counts 时 MUST NOT 因缺键抛 KeyError。

#### Scenario: 报告形态增量演进

- **WHEN** 窗口内同时存在 result/superseded/ended/running/stale 五类产物
- **THEN** 第 2 节各行计数之和等于总 run 数，且聚合过程无异常