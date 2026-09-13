## ADDED Requirements

### Requirement: 删除类交付物的收工校验

守卫 MUST 对 `delete` 条目反判：该路径在实现分支 HEAD 的 blob **不存在**视为达成，**仍存在**判违规 `undeleted`。`delete` 条目 MUST NOT 走软校验，也 MUST NOT 因「不可满足」被降级——其合法性约束由晋升 lint 在前置阶段裁定（见 `declaration-premechanize`）。

#### Scenario: 未删除判违规

- **WHEN** 声明段含 `- path: __init__.py` + `kind: delete`，实现分支 HEAD 中该 blob 仍存在
- **THEN** 守卫返回一条 `{"path": "__init__.py", "kind": "delete", "violation": "undeleted"}`

#### Scenario: 已删除放行

- **WHEN** 声明段含 `- path: __init__.py` + `kind: delete`，实现分支 HEAD 中该 blob 已不存在
- **THEN** 守卫对该条目不产生违规，其余条目照常判定

## MODIFIED Requirements

### Requirement: 交付物路径提取

`tasks.md` 的 `## Deliverables` 声明段 MUST 支持四类 kind：`new`（本仓库新建文件）、`modify`（修改既有文件）、`delete`（本 change 的交付物是让该路径在合并后不存在，仅限入库文件）、`reference`（运行时写入目标/既有引用，非本仓库交付物）。`kind` 取值超出该四值集合的条目 MUST 被忽略（与既有的非法 kind 处理一致）。

提取结果按硬软两组归类：`new` / `modify` / `delete` 归 `deliverables`（硬校验），`reference` 归 `references`（软校验）。同一路径重复声明时保留首见条目（既有行为）。

#### Scenario: delete 条目归入硬校验组

- **WHEN** 声明段含 `- path: __init__.py` + `kind: delete`
- **THEN** `extract_declared` 返回的 `deliverables` 含该路径
- **AND** `references` 不含该路径

#### Scenario: 四类之外的 kind 仍被忽略

- **WHEN** 声明段含 `- path: core/x.py` + `kind: archive`
- **THEN** 该条目不出现在 `deliverables` 与 `references` 任何一组

#### Scenario: 同路径重复声明保留首见

- **WHEN** 声明段先写 `- path: core/x.py` + `kind: delete`、后写同路径 + `kind: new`
- **THEN** 提取结果中该路径的 kind 为 `delete`

### Requirement: 收工时存在性校验

实现 run 声明成功后、merge 之前，系统 MUST 对声明段 `deliverables` 组中每个条目，在**实现分支 HEAD** 上按 kind 校验达成条件：`new`/`modify` 要求该路径 blob 存在，`delete` 要求该路径 blob 不存在。任一未达成 → 本次 run MUST NOT 执行 merge、MUST NOT 推进状态，按既有失败路径处置。

校验结果 MUST 以结构化条目列表返回（每项含 `path` / `kind` / `violation`，`violation ∈ {missing, undeleted}`），而非裸路径列表——下游（dispute 匹配、LLM 终审、重派话术）据此按 kind 分化表述与可用归宿。

#### Scenario: 缺件阻断 merge

- **GIVEN** 声明清单含 `core/x.py`（kind: new）且实现分支 HEAD 中该 blob 不存在
- **WHEN** 实现 agent 报成功
- **THEN** 不执行 merge、不推进状态
- **AND** 守卫返回项含 `{"path": "core/x.py", "kind": "new", "violation": "missing"}`
- **AND** error 记录违规清单（含「交付物守卫」字样），按既有重试路径重派实现

#### Scenario: 全部达成时放行

- **GIVEN** 声明清单全部条目的达成条件在实现分支 HEAD 成立（new/modify 存在、delete 不存在）
- **WHEN** 实现 agent 报成功
- **THEN** 走既有 merge 与推进路径，守卫不产生额外状态变更

#### Scenario: 缺件与未删除混合时逐条返回

- **WHEN** 同一声明段中一条 `new` 缺失、一条 `delete` 未删除
- **THEN** 守卫返回两项，`violation` 分别为 `missing` 与 `undeleted`，路径与 kind 一一对应
