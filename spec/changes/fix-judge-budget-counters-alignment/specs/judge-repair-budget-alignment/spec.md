## ADDED Requirements

### Requirement: 修复预算耗尽后 judge 进入无修复纯归因模式

场景原地修复预算耗尽（含其后的排程重验 episode，无论是否经历 daemon 重启）后，judge 后续轮次 MUST 以无修复纯归因模式运行：可输出 product-bug / test-defect / env 定性，其中 test-defect MUST 仅记录于裁决产物而 MUST NOT 改写场景文件、MUST NOT 申报 scenario-repaired、MUST NOT 触发场景重执行重入。该模式 MUST 跨 daemon 重启持久（预算耗尽状态以 STATE 持久字段为准，不以进程内存为准）。

#### Scenario: 预算耗尽后排程重验轮不再修复
- **WHEN** 场景修复预算已耗尽（`_scenario_repair_exhausted_rounds >= 1`）且排程重验新 episode 的 judge 轮发现 test-defect
- **THEN** judge 仅在裁决产物中记录缺陷与修复建议，场景文件保持原样，无 scenario-repaired 申报、无场景重执行重入

#### Scenario: 耗尽状态跨重启持久
- **WHEN** 预算耗尽排程重验后 daemon 重启、恢复路径重入验证
- **THEN** judge 在重验轮仍处于无修复纯归因模式（耗尽状态来自 STATE 持久字段，未被重启清除）

#### Scenario: 人工解冻重置后修复通道重开
- **WHEN** 人工 unfreeze_spec（清零集含修复耗尽计数，既有语义）
- **THEN** 后续验证 episode 的 judge 修复通道恢复正常（重新获得修复预算），与既有「人工解冻重获首次排程重验体验」语义一致

### Requirement: 硬上限冻结告警附修复预算上下文

`_judge_hard_cap_freeze` 冻结的告警（description/evidence/recommended_action）MUST 附场景修复预算状态，三项各具名数据来源：①是否已耗尽（`_scenario_repair_exhausted_rounds` STATE 持久字段）；②生命周期累计修复申报轮数与耗尽后被拒轮数（受理门写点维护的预算口径计数留痕）；③最近一次修复申报摘要（judge 裁决产物，场景 id 级别即可）。MUST NOT 依赖日志回捞取数。人工裁决者 MUST 能从告警直接判断「重跑超上限」由哪类重入贡献、剩余缺陷该走修复还是归因。

#### Scenario: 告警含修复历史摘要
- **WHEN** judge 重跑计数触顶冻结，且此前存在修复申报轮
- **THEN** 告警 evidence 含修复申报轮数与最近一次申报摘要（场景 id 列表级别即可），recommended_action 指向对应处置路径
