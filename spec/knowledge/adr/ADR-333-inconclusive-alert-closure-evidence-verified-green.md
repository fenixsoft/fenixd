# ADR-333：inconclusive_loop 告警收口证据=验证翻绿（机器裁决），安静自愈面维持排除

date: 2026-11-08
status: accepted

## Context

inconclusive_loop（env 豁免握手停车族）曾被三层刻意排除于一切自动闭环通道（不进条件映射、不进回填集、不进自愈注册表），原始理由是「豁免不得自我批准」——agent 自动收口会被读成替人工做了「不豁免」裁决。但当环境经链外修复、验证轮真翻绿（spec 到 verified/done/pushed）后，「豁免三选一」已成伪命题，告警仍以过期待决形态永久滞留人工队列（实证：升级件 9e0403d0ac94，spec 已 pushed 而告警未处理）。既有 spec 附着条件 `spec_terminal_or_unblocked` 又过宽：「离开 blocked」即解除——auto 重派反例（spec 离开停车态回 testing 但环境仍坏，16:19 在案）证明离开停车 ≠ 问题消失。

## Decision

新增 spec 附着条件 `spec_verified`（状态集 verified/done/pushed，比 `spec_terminal_or_unblocked` 严格一档）：inconclusive_loop 告警在其关联 spec 验证翻绿时自动收口。收口证据标准裁定（约束后续一切收口通道扩展）：

- 收口 =「豁免裁决问题的前提已消失」，不是「替代人工裁决」——收口不回答「要不要豁免」，三选一因翻绿而不复存在。
- 收口证据只认验证引擎的 verified 判定（洗白门禁背书：env 失败不得判 verified），不信任任何 agent 处置自述；环境修不好就永不 verified、永不收口，fail-closed 由结构自带。
- 安静时长永不构成该族收口证据：`SELF_HEAL_SIGNAL_TYPES` 维持不含 inconclusive_loop（安静 ≠ 翻绿）。
- 不建 agent 主动撤回通道（「agent 声明修复即撤回」被用户否决——自我批准风险）；收口挂既有周期扫描判定，不做 verified 落定转场即时钩子（转场钩子属第二触发点，破坏「扫描内联、零独立线程」定调）。
- verified 落定后被打回（VERIFIED→TESTING 回退）不重开已收口件：复发由新一轮信号产生新告警，审计链完整。

## Consequences

- 在案滞留件随存量回填自动清零，人工队列不再积累过期三选一告警；收口延迟=一个巡检周期（分钟级），被接受为设计内代价。
- 后续任何信号类型要求自动收口，必须锚定可机械验证的前提（引擎裁决、主体终态等），不得以 agent 自述或安静时长为据，否则保持人工闭环。
- `spec_verified` 与 `spec_terminal_or_unblocked` 的严格性分界被反例 Scenario 钉死：离开停车态不构成翻绿证据。
- 自愈注册表保持纯签名安静语义（ADR-283 两通道边界延续），inconclusive_loop 只经条件族通道收口。
