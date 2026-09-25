# spec-verify-environment-sanity-gate（delta）

## MODIFIED Requirements

### Requirement: blocked-env 的报告与门禁换算
report.summary 的 `blocked_env` 字段与「有效失败 = failed - blocked_env」口径保持不变；inconclusive 判定 SHALL 从「全部原始失败均为 blocked-env」扩展为两级：级一维持既有全批 blocked-env（judge 前原始 summary 口径，escalation 阶段 2.6）；级二为「judge 裁决后全部失败（含混合形态中原始 failed>0 的部分）均被归类环境因素」——级二在裁决采纳尾段判定，处理与级一同源（回 implemented 重验新 attempt，不判 bug-found、不产生 repeated_failures）。既有重验上限与 B7 升级阈值语义对两级统一适用。

#### Scenario: 混合形态全部环境性按 inconclusive 处理
- **WHEN** 一轮原始 summary 为 19 passed + 2 failed + 1 blocked_env（混合形态，不满足级一判据），judge 裁决将 2 个 failed 全部归类 env
- **THEN** 级二判据命中，整体按 inconclusive 处理：回 implemented 排队重验，不落 verified、不产生 bug-found

#### Scenario: 裁决认定真实缺陷时不触发级二
- **WHEN** 一轮 2 个 failed 中 judge 裁决 1 个为产品缺陷、1 个为 env
- **THEN** 级二不命中，按既有 bug-found 流程处理产品缺陷（env 部分仍走豁免记录）

#### Scenario: 全批 blocked-env 既有语义不变
- **WHEN** 一轮全部原始失败均为 blocked-env 且无 passed 之外的失败
- **THEN** 级一（既有阶段 2.6）先命中并短路，行为与现状完全一致，judge 不再重复判定
