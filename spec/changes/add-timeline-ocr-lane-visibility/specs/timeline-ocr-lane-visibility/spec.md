## ADDED Requirements

### Requirement: ocr 车道 run 节点身份标签
项目时间轴上 `impl-ocr` 车道的 run 节点 SHALL 显示「代码审查 Agent」：agent_type 识别（`impl-ocr`）与 run_id 前缀兜底（`impl-ocr-`，MUST 排在 `impl-` 兜底之前，长前缀优先）双路命中。既有 `impl-` 前缀（implementer/fast-track）run 节点的「开发 Agent」标签 MUST 保持不变。

#### Scenario: 车道运行节点显示代码审查 Agent
- **WHEN** 时间轴渲染 run_id 为 `impl-ocr-<spec>-<ts>` 的 run 节点（无论运行中或已终态）
- **THEN** 节点 agent 标签为「代码审查 Agent」，不显示「开发 Agent」

#### Scenario: 既有实现者节点标签不回归
- **WHEN** 时间轴渲染 run_id 为 `impl-<spec>-<ts>`（非 `impl-ocr-`）的实现者 run 节点
- **THEN** 节点 agent 标签仍为「开发 Agent」

### Requirement: 车道 run 节点审查对象摘要
时间轴后端 SHALL 为 ocr 车道 run 节点透出其转录 start 事件的既有 message（分支名与 `from..to` 审查区间），前端在节点内容行展示——用户可从时间轴直接看出车道在审哪个分支哪段区间；message 缺失/为空时内容行不渲染（容错降级，不报错）。

#### Scenario: 运行中车道节点可见审查区间
- **WHEN** ocr 车道正在运行，时间轴渲染该 run 节点
- **THEN** 节点内容行显示 start 事件 message（含分支名与 `8f17..a917` 形态的审查区间），圆点/状态 Tag 仍为运行中语义

#### Scenario: 无 message 时不渲染内容行
- **WHEN** 车道 run 转录缺 start 事件或 message 为空
- **THEN** 节点仅显示标签与状态，无内容行，渲染不报错

### Requirement: testing 停等的 ocr 门注记
时间轴 SHALL 在「最新的状态转移节点 to 为 testing」时，按质量门禁 ocr 门（gate id `code-review`）的**当前**状态决定是否附注记：状态为 `running` 时附「ocr 审查车道进行中，完成自动推进」语义注记；其余状态（pending/skipped/completed/unknown/无记录）或该节点非最新状态节点时 MUST NOT 附注记。注记数据 MUST 与质量门禁 Card 同一合成源（quality_gates.py 的 ocr 门三态合成），不得另起第二套判定；注记表达的是当前时刻状态，非历史转移时刻状态（节点不声称历史时刻的门禁状态）。

#### Scenario: 车道审查中显示停等注记
- **WHEN** spec 处于 testing、ocr 车道在跑（ocr 门合成状态 running），时间轴最新的状态转移节点为「implementing → testing」
- **THEN** 该节点附「ocr 审查车道进行中，完成自动推进」注记，与质量门禁 Card 中 ocr 门的「进行中」标识一致

#### Scenario: 门禁非 running 不显示注记
- **WHEN** 时间轴存在「→ testing」状态节点，但 ocr 门当前状态为 completed（或 pending/skipped/unknown）
- **THEN** 该节点无注记——历史状态节点不携带与当前无关的进行时语义，避免噪音

#### Scenario: 最新状态节点非 testing 不显示注记
- **WHEN** 时间轴最新的状态转移节点 to 不是 testing（如已 verified/done）
- **THEN** 任何节点都不显示停等注记
