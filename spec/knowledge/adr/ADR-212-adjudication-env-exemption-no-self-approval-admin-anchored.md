# ADR-212：裁决 env 豁免不得自我批准（重验穷尽 + admin 处置锚定）

date: 2026-10-03
status: accepted

## Context

验证链的环境防御（应用不可达升级、全批 blocked-env inconclusive、同因失败哨）全部以 judge 之前的原始 summary 口径判定，混合形态（19 passed + 2 failed + 1 blocked_env）全部漏出；judge 裁决把失败断言单方面归类 env（断言级豁免，场景级 classification 未标）后自我批准 verified——豁免不回流任何升级计数器，admin 全程未介入，dist 陈旧无人重建。fail-open 的正确语义是「框架穷尽自动化补救后仍无法解决才留报告给人」，缺失的正是补救动作与握手环节。

## Decision

- 「失败全部为环境性」的轮次无论判定时点一律转 inconclusive 重验链，不当健康轮放行：级一维持 judge 前全批 blocked-env 短路，级二挂 judge 裁决采纳尾段（断言级 assertion_triage 全 env 判据，不新增阶段），级二先于场景级洗白门禁且命中即不再到达后者（同一轮两道裁决后防线不叠加动作）。
- 级一级二共享同一 inconclusive 计数器（同一重验上限与升级阈值）；级一命中即 return、judge 不跑，单轮内两级互斥，禁双计数器漂移。
- 豁免不得自我批准：重验穷尽走既有 B7 SIGNAL 通道唤起 Administrator；env 豁免最终生效以 AdminStore 的 DISPOSITION 放行记录为唯一锚（查得即本轮放行、查不得转重验），admin 介入前框架 MUST NOT 以豁免清单为依据自行产出 verified；不新增状态机状态。
- 重验派发前必须执行框架权限内的环境补救（serving 层 dist 新鲜度探针 + 自动重建），补救失败记入错误现场禁静默；框架权限外的环境修复（事件源诊断等）归 admin，框架不自作主张改环境。

## Consequences

- 豁免不再是裁决 agent 的单方面决定，混合形态不再被洗白为 verified；代价是「裁决全部豁免」的健康轮会被打回重验（既有重验上限 + 并行度逐轮减半封顶约束成本）。
- 豁免链路跨 verification pipeline / escalation / admin_store / serving 四模块，后续任何想放宽或绕过豁免握手的能力都必须对齐「重验穷尽 + admin 锚定」两道闸。
- dist 重建从 merge-back 单点扩散为多触发点（serving 探针为第二触发点），构建执行体提取为模块级函数供两处复用。
