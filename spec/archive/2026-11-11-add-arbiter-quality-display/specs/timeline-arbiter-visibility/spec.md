# timeline-arbiter-visibility Spec

## ADDED Requirements

### Requirement: 时间轴 arbiter 节点标签

SPEC 运行时间轴（SPEC 详情页运行时间轴）SHALL 将 arbiter run 节点显示为「质量裁决 Agent」：前端 Agent 标签单源 `runVisual.ts` 的 `AGENT_LABEL` SHALL 含 `arbiter: '质量裁决 Agent'` 条目，`RUN_ID_PREFIX_LABEL` SHALL 含 `['arbiter-', '质量裁决 Agent']` 前缀兜底条目。MUST NOT 出现 arbiter 节点显示「未知 Agent」的形态（后端 get_runs 既有 arbiter- 前缀归属保持不变，本能力仅修前端标签面）。

#### Scenario: arbiter 节点正确标注

- **WHEN** SPEC 时间轴含 agent_type=arbiter 的 run 节点（如 arbiter-evo-refine-midflight-outlier-dims-1793464069）
- **THEN** 节点标签渲染「质量裁决 Agent」，不显示「未知 Agent」

#### Scenario: agent_type 缺失时前缀兜底

- **WHEN** run 节点 agent_type 为泛型 'agent' 或缺失且 run_id 以 `arbiter-` 开头
- **THEN** 前缀判别命中，标签仍为「质量裁决 Agent」

### Requirement: 时间轴 arbiter 处理记录富展示

SPEC 运行时间轴 SHALL 富展示 arbiter 的处理记录：后端时间轴派生（`get_spec_timeline`）对 agent_type=arbiter 的 run 节点按 run_id 联查处置台账 `.fenix/arbiter_ledger.jsonl`，命中 `kind ∈ {disposition, escalation}` 的条目时节点 SHALL 附带结构化字段（处置结论 kind、根因 root_cause、处置动作或升级理由 action_or_upgrade、触发信号 signal_type；长文本截断下发）。前端 run 节点卡片 SHALL 渲染该块：处置结论区分「自主处置」（disposition）与「升级人工」（escalation），根因与处置动作以摘要文本随节点可见。联查 MUST fail-open：台账文件缺失、条目损坏、run_id 未命中时静默省略附加字段，时间轴节点（标签/状态/摘要等既有字段）不受影响。spec-proposed 类条目（无 run_id 关联）MUST NOT 挂到 run 节点上。

#### Scenario: 自主处置节点展示处置结论与根因

- **WHEN** 某 arbiter run 对应台账 disposition 条目（含 root_cause 与 action_or_upgrade）
- **THEN** 该 run 节点渲染「自主处置」结论块，根因与处置动作摘要在节点内可见

#### Scenario: 升级节点区分展示

- **WHEN** 某 arbiter run 对应台账 escalation 条目
- **THEN** 该 run 节点渲染「升级人工」结论块（与自主处置视觉可区分），升级理由摘要可见

#### Scenario: 处置失败 run 无台账条目时优雅降级

- **WHEN** 某 arbiter run（如 frozen-terminated 终态）在台账中无 disposition/escalation 条目，或台账文件不存在
- **THEN** 节点正常渲染标签与既有字段，无附加块、无报错（fail-open）

#### Scenario: 立项条目不污染 run 节点

- **WHEN** 台账存在 spec-proposed 条目（run_id 为空）
- **THEN** 该条目不挂载到任何时间轴 run 节点
