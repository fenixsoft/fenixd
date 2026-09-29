<!-- knowledge: capability=post-recovery-patrol rev=2 sources=spec/archive/2026-09-02-improve-run-lifecycle-governance,spec/archive/2026-09-18-fix-dispatch-wakeup-gap -->

# 恢复后巡检与假就绪闭环复查

auto-recovery 之后安排闭环复查并前置就地重新派发，周期巡检覆盖假就绪滞留，同类告警按指纹限频，保证恢复动作真实生效而非制造假就绪。

## 现行规则

- 闭环复查：任何 auto-recovery 动作（状态重置、跟踪清理）完成后登记观察项，在 `pm.recovery.followup_check_minutes` 后复查该 spec 是否已真实恢复推进（已被派发或进入后续状态）。
- 复查判据以语义为准，不是「status 与登记时是否相同」：观察窗口到达时该 spec 处于 `ready` 且无活跃派发，无论 status 是否与登记时不同（典型：登记时 implementing，窗口内因中断回退 ready），均判为尚未恢复推进。
- 判为尚未恢复推进时先尝试就地重新派发（走与 `spec_ready` 事件同源的派发路径，经既有依赖/预算/内容完整性/冻结闸门）：派发成立 → 关闭观察项且不产生任何告警；派发未成立（含被预算或内容完整性闸门拦下）→ 关闭观察项并以 `dispatch_stalled` 信号唤起 Administrator 处置，处置结果可追溯到当初的恢复动作；不得仅记日志静默关闭。spec 已进入 ready 之后的后续状态（implemented / testing / verified / done / pushed）或已有活跃派发 → 关闭观察项且不告警。
- 假就绪巡检覆盖：周期巡检与 BLOCKER CHECK 检查非运行态 spec 的滞留——spec 停留 ready 超过 `pm.recovery.ready_stall_threshold_minutes` 且期间无成功派发时报告为阻塞项；「无 in-progress SPEC」不构成跳过整轮巡检的理由（不得因「No in-progress SPECs」提前返回）。
- 指纹限频：对同一 spec 的 dispatch_stalled 类信号按指纹去重——指纹未变化且处于冷却期内时记录事件但不重复拉起 Administrator（仅首次触发拉起，后续轮次只追加日志）；指纹变化或冷却期结束方可再次拉起。

## 溯源

- [2026-09-02 improve-run-lifecycle-governance](spec/archive/2026-09-02-improve-run-lifecycle-governance/) — 新增闭环复查、假就绪滞留巡检覆盖与指纹限频
- [2026-09-18 fix-dispatch-wakeup-gap](spec/archive/2026-09-18-fix-dispatch-wakeup-gap/) — 复查判据改语义口径并前置就地重新派发，覆盖「窗口内回退 ready」形态且闸门拦截不静默关单
