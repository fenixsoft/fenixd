# judge-artifact-gate — planner 裁决产物存在性硬门

## ADDED Requirements

### Requirement: planner-judge 产物硬门
`agent_runner` 对 `planner-judge` run 的成功判定 SHALL 为「进程 exit 0 **且**结果文件（`.fenix/verify-progress/<spec>/.fenix-run-result.json`）存在且可解析为非空 JSON」。任一条件不满足 MUST 判 `success=False` 并附产物缺失归因 error，走既有瞬态原地退避重试通道。

#### Scenario: exit 0 无产物判瞬态失败
- **WHEN** planner-judge 进程 exit 0 但结果文件不存在（模拟网关流截断后零产物）
- **THEN** run 判 `success=False`，error 含「结果文件缺失」归因；进入瞬态退避重试（attempt 1/3），**不**触发 `_verify_verdict_evidence` 的「裁决重试一次」路径

#### Scenario: 结果文件残缺视为缺失
- **WHEN** 结果文件存在但内容为空或非法 JSON
- **THEN** 与缺失同判：`success=False` + 瞬态重试

#### Scenario: 正常产物放行
- **WHEN** planner-judge exit 0 且结果文件为合法 JSON（status ∈ verified/bug-found/scenario-repaired）
- **THEN** run 判成功，后续 validate_report 流程与现状一致

### Requirement: planner-plan 产物硬门
`planner-plan` run 的成功判定 SHALL 同样要求 `test_scenarios.json` 存在且可解析；场景冻结复用轮不派发 planner-plan（既有行为），硬门对其无影响。

#### Scenario: plan 无产物判瞬态失败
- **WHEN** planner-plan exit 0 但 test_scenarios.json 未生成
- **THEN** run 判 `success=False` + 瞬态退避重试

### Requirement: 裁决重试预算语义不变
产物缺失引起的重试 MUST NOT 消耗 `_verify_verdict_evidence` 的「裁决重试一次」预算；该预算专用于「产物存在但不合规」（validate_report 违规）路径。

#### Scenario: 硬门重试与裁决重试互不侵占
- **WHEN** judge 第一次 run 产物缺失（硬门瞬态重试成功）后，第二次 run 产物合规但 validate_report 仍报违规
- **THEN** 走既有「裁决重试一次」；两次重试计数独立
