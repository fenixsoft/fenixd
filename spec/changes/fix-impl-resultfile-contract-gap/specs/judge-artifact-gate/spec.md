## MODIFIED Requirements

### Requirement: 裁决重试预算语义不变

产物缺失引起的重试 MUST NOT 消耗 `_verify_verdict_evidence` 的「裁决重试一次」预算；该预算专用于
「产物存在但不合规」（validate_report 违规）路径。

产物硬门契约段的提示词可见性 MUST 覆盖全部受硬门约束的 agent 车道：`planner-plan`、
`planner-judge`、`spec-review`、`implementer`、`fast-track`。契约段内容 MUST 声明「收工前未写 /
文件为空 / 非法 JSON → 判失败并原地重试（fail-closed）」与「先落盘再深入」，且结果文件路径
MUST 按 agent_type 分派计算（各车道与其 runner 侧硬门校验路径同源，避免双实现漂移）。

#### Scenario: 硬门重试与裁决重试互不侵占

- **WHEN** judge 第一次 run 产物缺失（硬门瞬态重试成功）后，第二次 run 产物合规但 validate_report 仍报违规
- **THEN** 走既有「裁决重试一次」；两次重试计数独立

#### Scenario: 五条车道契约段全覆盖

- **WHEN** 分别以 `planner-plan` / `planner-judge` / `spec-review` / `implementer` / `fast-track`
  构建提示词
- **THEN** 五个提示词均包含结果文件硬门契约段，且各自给出的结果文件路径与其 runner 侧硬门
  实际校验路径一致

#### Scenario: 实现者车道不再缺段

- **WHEN** 构建 `implementer` 或 `fast-track` 提示词
- **THEN** 契约段在位（本变更前该两车道契约段缺失，是 2026-09-17 取证的 $97.86 事故根因）
