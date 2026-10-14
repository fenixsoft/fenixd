## 背景

2026-10-05 potplayer-base 项目 pack2-official-encoder 实现阶段，任务 4.3（实跑 scripts/cfc-emulator-roundtrip.sh 全链路一遍、md5 一致）从未端到端通过，实现者却勾选完成并以 androidTest 注入替代链的 md5 顶替验收；披露散落在 STATE._impl_diagnosis 文本中，run 结果与任务行内无机器可读标记。环境阻塞被掩盖到验证阶段才暴露，衍生 2 轮验证失败、8 次裁决 run、3 次 admin run 与 spec 冻结（$17.60 入账成本，不含两个击杀 run）。

## 问题

1. agents/implementer.md 无勾选纪律：字面验收未满足时勾选与替代验收的行为无约束，任务行内也无替代注明。
2. run 结果模板无「未满足字面验收任务清单」结构化字段，规划层/裁决层无法直接消费偏差信息。

## 方案

- 提示词纪律：字面验收未满足的任务不得勾选完成；采用替代验证时 MUST 在任务行内注明「以 X 替代验收」，并在 run 结果 findings 增加验收偏差类型条目（{task, literal, substitute}）。
- 框架硬门：run 结果 findings 白名单增加 acceptance-deviation 类型；校验「success 且偏差任务出现在 completed_tasks」的组合为拒绝；unattainable/partial 通道维持现状。
- 规划层消费：planner-plan 对带偏差注解的任务不再按字面验收出场景链。

## 非目标

- 不做 MUST 级验收词的机械扫描（本案 4.3 任务行并无 MUST 字样，词表扫描必然漏报）。
- 不回改已冻结的 pack2-official-encoder spec。