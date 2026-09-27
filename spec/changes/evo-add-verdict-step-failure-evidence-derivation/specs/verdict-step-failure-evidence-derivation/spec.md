# verdict-step-failure-evidence-derivation

## ADDED Requirements

### Requirement: 步骤失败形态的失败清单派生
judge 证据的 assertion_results 为空且场景存在失败信号时，校验器 SHALL 在判 triage 违规前，由失败信号（step_results success=false 条目、visual_results diff_detected/warning 条目）派生缺省 failed_assertions 清单，并以派生清单为基准执行 triage 覆盖校验；派生 SHALL NOT 弱化 fail-closed 语义——triage 归因未逐条覆盖派生清单的仍判违规。

#### Acceptance Scenario 1: 空表不再空转驳回
- WHEN judge 证据 assertion_results 为空、场景存在失败步骤、且 failed_assertions 未自申报
- THEN 校验器以派生清单为基准给出违规与应申报条目清单，驱动一次有内容的重试而非同形态空转

#### Acceptance Scenario 2: fail-closed 不弱化
- WHEN 派生清单存在且 judge 的 triage 归因未逐条覆盖派生清单
- THEN 仍判 triage 违规并按既有链路阻断推进

### Requirement: 重试轮注入派生清单
首轮因该形态判违规进入重试时，重试提示 SHALL 携带派生清单，使重试轮 judge 直接拿到应申报条目。

#### Acceptance Scenario 3: 重试轮拿到应申报条目
- WHEN 首轮违规触发重试且场景为步骤失败形态
- THEN 重试提示包含派生的 failed_assertions 条目清单

### Requirement: 提示词处方防漂移守卫
agents/planner-judge.md SHALL 保留「步骤失败型场景必填清单」自申报处方小节，且测试断言其存在，防止后续改写静默丢失（fe612841 处方的回归守卫）。

#### Acceptance Scenario 4: 处方在场断言
- WHEN 运行提示词文件守卫测试
- THEN agents/planner-judge.md 缺失该处方小节时测试失败