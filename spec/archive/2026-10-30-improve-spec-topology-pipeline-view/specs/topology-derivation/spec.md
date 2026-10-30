## ADDED Requirements

### Requirement: spec-review run 归属（uuid 段剥除）

需求评审 run_id 形态为 `spec-review-<spec>-<6hex>-<unix秒>`（`core/pm_engine/spec_review.py:392`
恒插入 6 位 uuid 段）。`run_spec_part`（`core/agent_runner/run_files.py`，全仓归属单源）
必须对该形态剥除 uuid 段，使推断 spec 名与真实 spec 名全等；剥除严格限定
`spec-review-` 前缀形态，其余前缀（impl-/planner-/code-review- 等）的推断行为不变。
修复后拓扑派生（`_family_run_paths` family 全等预过滤）与 `get_runs` 的 spec 字段
同步恢复正确。

#### Scenario: spec-review run_id 推断 spec 名全等

- **WHEN** 对 `spec-review-add-collab-graph-bigscreen-8e869d-1792938331` 调用 `run_spec_part`
- **THEN** 返回 `add-collab-graph-bigscreen`（无 uuid 尾巴），family 正则全等匹配成功

#### Scenario: 拓扑含需求评审节点

- **WHEN** 对存在 spec-review run 产物的 SPEC 派生拓扑（实测样本
  `add-collab-graph-bigscreen`，产物 `.fenix/runs/archive/spec-review-…-8e869d-….jsonl`）
- **THEN** nodes 含 `kind=run`、`agent_type=spec-review`、`stage=demand` 的需求评审节点，
  该 run 的 attempt/成本/harness 等字段与其他 run 节点同构

#### Scenario: 非 spec-review 形态推断行为不变

- **WHEN** 对 `impl-<spec>-<ts>-a2`、`planner-plan-<spec>-<ts>`、`fix-fix-<spec>-<ts>`
  及 spec 名以 9-10 位数字结尾的既有保护样本（code-review item 6c089e65a080）调用 `run_spec_part`
- **THEN** 返回值与修复前完全一致（快照对账）

### Requirement: 状态转移派生完整性

拓扑派生的 PMEngine 状态转移（`transitions`）不得因日志中存在单个超长行而整体为空：
锚定窗口（按 created 锚定）必须保证覆盖锚点时刻之后的可解析事件，超长行的处置机制
由 specs/daemon-log-event-governance 承载，本能力只约束派生结果完整性。

#### Scenario: 巨型行占满默认窗口仍派生锚点后转移

- **WHEN** daemon 日志首行为 6.6MB 巨型行（实测样本：fenixd.log 首行 admin_monitor
  信号嵌入 51054 个 entry）、SPEC created 晚于巨型行时刻
- **THEN** `derive_topology` 返回的 transitions 含该 SPEC 的全部状态转移
  （实测样本 `add-collab-graph-bigscreen` 为 9 条：drafted→reviewing→ready→
  implementing→implemented→testing→testing→verified→done→pushed 语义链），
  不再为 0 条

#### Scenario: 归档 SPEC 转移骨架不受影响

- **WHEN** 归档 SPEC（日志窗口退化/产物已清理）派生拓扑
- **THEN** 行为与既有「归档降级骨架」Requirement 一致，不因超长行防御引入新异常
