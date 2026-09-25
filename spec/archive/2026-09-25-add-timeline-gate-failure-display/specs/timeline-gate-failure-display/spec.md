## ADDED Requirements

### Requirement: 门禁失败在 run 产物中带错误归因

产物硬门（`AgentArtifactGateError`）失败时的原地退避重试路径 MUST 把门禁归因文案写入 run jsonl，
而非仅写 daemon log。

- `transient_retry` 事件（门禁路径）MUST 含 `error` 字段（门禁归因，截断至 ≤1024 **字符**；UTF-8
  编码后 ≤4096 字节）。
- `superseded` 事件（门禁路径）MUST 含 `error` 字段（同上）。
- 归因文案 MUST 保留门禁名称与目标路径（截断不得使其不可判）。

#### Scenario: 原地重试事件带门禁文案

- **WHEN** 产物硬门失败且原地退避预算未耗尽，写 `transient_retry`
- **THEN** 该事件 MUST 含非空 `error` 字段，且其内容 MUST 含门禁归因（如
  `impl-code-review-gate`）与目标路径片段

#### Scenario: 弃置事件带门禁文案

- **WHEN** 产物硬门失败、本 attempt 文件被弃置，写 `superseded`
- **THEN** 该事件 MUST 含非空 `error` 字段

### Requirement: 门禁拒绝产生独立终态事件

门禁失败导致本次 attempt 终止时，系统 MUST 向该 attempt 的 run jsonl 追加一个终态事件
`{"type": "gate-blocked", "spec", "provider", "reason", "error", "timestamp"}`，且该事件 MUST 为
文件**末行**（维持终态后置不变量）。`reason` MUST 按终止分支取对应值，MUST NOT 一律填同一个值：

- 结构类（产物硬门）原地退避预算耗尽 → `reason == "artifact_gate"`；
- 任务完成度类（`[task-gate]`）终止本 attempt → `reason == "task_gate"`；
- 退避后**让位**（spec 已被接管，非门禁判定）MUST NOT 追加该事件——该文件终态为已写入的
  `superseded`（含 `error`），把「被接管」标成「门禁拒绝」属误标。

#### Scenario: 门禁预算耗尽写终态

- **WHEN** 结构类门禁失败且原地退避预算耗尽，本次 attempt 终止
- **THEN** 该 attempt 的 run jsonl 末行 MUST 为 `type == "gate-blocked"`，且 MUST 含非空
  `error` 与 `reason == "artifact_gate"`

#### Scenario: 任务完成度门终止写终态

- **WHEN** `[task-gate]` 类门禁失败终止本 attempt
- **THEN** 该 attempt 文件末行 MUST 为 `type == "gate-blocked"` 且 `reason == "task_gate"`
  （MUST NOT 写成 `artifact_gate`）

#### Scenario: 让位分支不写门禁终态

- **WHEN** 门禁失败后进入原地退避，退避期间 spec 被接管（让位）
- **THEN** 该 attempt 文件 MUST NOT 出现 `gate-blocked` 事件（其末行终态为 `superseded`）

#### Scenario: 不再以 CLI result 冒充收工

- **WHEN** 上述（除让位外的）场景发生
- **THEN** 该 attempt 文件 MUST NOT 以 `type == "result"` 收尾（否则读侧会将其判为成功）

## MODIFIED Requirements

### Requirement: 运行终态映射

`_RUN_TERMINAL_STATUS_MAP` MUST 登记 `gate-blocked` 终态。

#### Scenario: 门禁终态被读取为终态

- **WHEN** run jsonl 末行为 `gate-blocked`
- **THEN** `classify_run` MUST 返回 `"gate-blocked"`（而非 `running`），且该状态 MUST 属于可归档
  状态集合

#### Scenario: 门禁终态不被判为死亡 run

- **WHEN** 实现预算对账统计 `_run_file_died`
- **THEN** 末行为 `gate-blocked` 的 run MUST NOT 被计作死亡（仍计入已耗预算）

### Requirement: 时间轴节点携带门禁失败原因

时间轴 run 节点 MUST 在门禁失败时下发非空 `reason`（取自终态事件的 `error`/`reason` 字段），供前端
直接展示，不依赖展开运行记录。

#### Scenario: 门禁拒绝节点带原因

- **WHEN** 某次 attempt 以 `gate-blocked` 收尾
- **THEN** 该 run 节点的 `status` MUST 为 `gate-blocked`，`reason` MUST 非空且含门禁归因

#### Scenario: 弃置重试节点带原因

- **WHEN** 某次 attempt 以 `superseded` 收尾且该事件带 `error`
- **THEN** 该 run 节点 `reason` MUST 非空

### Requirement: 门禁终态类型两侧同步登记

新增的写侧终态事件类型 `gate-blocked` MUST 同时登记进两处终态真源，缺一即产生半接入事故：

- 读侧映射 `core/dashboard/data/runs.py::_RUN_TERMINAL_STATUS_MAP`（缺它时间轴永远把该 run 判
  `running`）；
- 写侧终态集合 `core/agent_runner/liveness.py::RUN_TERMINAL_EVENT_TYPES`（缺它末行 `gate-blocked`
  的运行在「在跑判定」里被永远判为在跑）。

#### Scenario: 门禁终态不被判为在跑

- **WHEN** 某 SPEC 名下只剩末行为 `gate-blocked` 的 run 产物，对其执行删除/归档
- **THEN** 该 run MUST NOT 被计入在跑（`running_run_ids_for_spec` 不返回它），软删除 MUST NOT 因
  「有进行中的运行」被拒

### Requirement: 前端在 Agent 节点展示门禁拒绝

`detail.tsx` 的时间轴 run 节点 MUST 对 `gate-blocked` 状态给出可辨识的失败渲染，MUST NOT 落入
成功（绿色）兜底。

#### Scenario: 门禁拒绝节点红色可辨

- **WHEN** run 节点 `status == "gate-blocked"`
- **THEN** 圆点与状态 Tag MUST 为失败色（红），Tag 文案 MUST 表达「门禁拒绝」，且 `reason` 非空时
  MUST 渲染「门禁拒绝：<原因>」行

#### Scenario: 带原因的弃置节点不落无原因绿点

- **WHEN** run 节点 `status == "superseded"` 且 `reason` 非空
- **THEN** MUST 渲染「原地重试：<原因>」行，MUST NOT 呈现为无原因节点
