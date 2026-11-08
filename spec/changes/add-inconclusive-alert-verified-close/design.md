# 设计：inconclusive 告警验证翻绿自动消解

## Context

处置链终点上升件中 `inconclusive_loop` 族（judge 全裁 env + 豁免握手拦截停车 → 升级人工三选一）被三层刻意排除：不在 `_SIGNAL_CONDITIONS`（无 trigger）、不在 `BACKFILL_SIGNAL_TYPES`（回填不收）、不在 `SELF_HEAL_SIGNAL_TYPES`（永不安静自愈）——原始理由是「豁免不得自我批准」：agent 自动收口该告警会被读成替人工做了「不豁免」裁决。

但 add-integration-test-env 事故（2026-11-07）暴露了该排除的盲区：链升级后环境被**链外** admin run 修复（宿主代理管道），重验 6/6 真翻绿、spec 走到 pushed——三选一已无意义，告警 9e0403d0ac94 仍滞留人工队列。用户定调（2026-11-08 排查会话）：**告警应在验证翻绿那一刻自动消失、人工零感知**。

既有机器（全部复用，零新发明）：trigger 写侧埋点（`build_trigger`/`attach_trigger`）、条件族单源 `_SIGNAL_CONDITIONS`、识别门 `_recognized`、存量回填 `BACKFILL_SIGNAL_TYPES`、周期扫描内联判定（`find_resolvable` → `evaluate_alert`，不引入独立线程）、auto-resolve 写回形态（`handled_by`/`resolve_note`/人工记录不可覆盖）。

## Goals / Non-Goals

- **Goals**：翻绿即收口（延迟=一个巡检周期）；人工零感知（待处理横幅不再出现）；fail-closed（环境修不好 → 永不 verified → 永不收口）；复发开新件（既有语义，审计链完整）；存量滞留件随启动回填清零。
- **Non-Goals**：不改自愈注册表（inconclusive_loop 保持不在安静自愈族——安静 ≠ 翻绿证据）；不建 agent 主动撤回通道（用户否决了「agent 声明修复即撤回」形态——自我批准风险）；不动 `CLOSED_BY_CHAIN`/链外收口对账缺口（todo.md:194-205 在案，另行治理）；不改验证管线与洗白门禁。

## Decisions

**D1 新条件 `spec_verified`，状态集 = `("verified", "done", "pushed")`。**
`verified` 为锚点；`done`/`pushed` 是其后的终态（覆盖扫描滞后窗口内已推进的 spec）。**比既有 `spec_terminal_or_unblocked` 严格一档**：`testing`/`implementing`/`blocked`/状态缺失一律不收口——实证反例（16:19 auto 重派：spec 离开停车态回 testing 但环境仍坏）必须保持原状，本条件以 Scenario 钉死。

**D2 收口语义 =「问题前提已消失」，非「替代人工裁决」。**
收口证据 = 验证引擎的 verified 判定，而 verified 已被洗白门禁背书（env 失败不得判 verified）。豁免三选一的「问」因翻绿而不复存在，收口不回答「要不要豁免」——这是对「inconclusive_loop 永不自动闭环」条款的显式修订；修订边界：**安静自愈面维持排除**（注册表注释同步改写，防语义漂移）。

**D3 挂靠既有周期扫描，不新增触发点。**
判定进 `evaluate_alert` 条件分支（`has_trigger` 路径按 condition 分派 + 非 trigger 回填路径按 signal_type 推断同条件），消费方 `find_resolvable`/周期巡检零改动。收口延迟一个巡检周期（分钟级），「翻绿那一刻」在此精度下成立；`verified` 落定转场的即时钩子**不做**（转场钩子属第二触发点，破坏「扫描内联、零独立线程」架构定调）。

**D4 双 kind 同治 + 回填收录。**
`inconclusive_loop` 入 `_SIGNAL_CONDITIONS` 后，未来产生的 escalation 与 kind=signal 条目都自动携带 trigger 进入 spec 附着族；`BACKFILL_SIGNAL_TYPES` 收录 `inconclusive_loop`，存量无 trigger 条目按**同一新条件**推断（回填条件必须与在册映射一致，MUST NOT 回填成宽松的 terminal_or_unblocked）。

**D5 注记与审计形态。**
`handled_by=auto-resolve`、无 `close_cause`（条件族通道既有三分审计口径不变）；注记：`spec <X> 验证已翻绿（状态 verified）——env 豁免裁决问题前提消失（验证翻绿收口）`，附状态表 `updated` 时刻（缺失不硬造，沿用 `_resolve_note_for_condition` 风格）。

**D6 保守缺省全保留。**
人工已处理（handled=True）逐位不变；spec 不在状态表/字段缺失不收口；`verified` 落定后被打回（VERIFIED→TESTING 回退存在）不重开已收口件——打回后再现 env 停车由新一轮信号产生**新**告警。

## Risks / Trade-offs

- **[收口延迟] 翻绿与收口间有分钟级窗口** → 接受：横幅在下一巡检消失，无中间误操作面；不做转场钩子（D3）。
- **[打回场景] verified 后打回重验再坏** → 旧件已收口、新件新告警，审计链完整；不重开（D6，既有语义）。
- **[语义漂移] 实现者只加映射不改注释，注释仍写「永不自动闭环」** → 任务显式列出三处注释改写点并作为验收项。
- **[假翻绿] 环境瞬态窗口巧合通过** → verified 门禁背书下「通过」即合法收敛；后续复发开新件，不构成静默丢失。

## 设计约束

无界面改动，`DESIGN.md` 不涉及。
