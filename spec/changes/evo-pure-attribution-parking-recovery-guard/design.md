# Design: pure-attribution-parking-recovery-guard

## 根因链

四环回环，均已回源：①受理门拒收后仅留痕（pipeline.py:1877-1990），spec 停 testing 无驱动；②orphaned_state 探测把 testing 无驱动当异常（60m 冷调节流只压频率不消解）；③Recovery（event_bus.py:640-678）守卫仅 inconclusive/undriven/admin 在飞三项，无条件重派全量验证；④judge rerun 计数在派发判定处 +1（judge_gate.py:717-760），清零点仅 verified+unfreeze——重放轮计入连败直至 6/5 冻结。

## 方案

- 停泊态复用 state_machine.py:341 既有 `_frozen_hold` 字段（零新增 schema）：纯归因进入时置位并留原因；停泊检查落 `spec_is_undriven` 共享判定单点（admin_monitor 孤儿探测与 event_bus `_recover_testing` 同源消费，勿两处各写——沿用 event_bus 既有「勿在此另写一份」纪律）。
- 防重放守卫读取末轮 judge 归因（prev-judge-result.json 的 test-defect 分类）与场景集/产物指纹（现有 verdict_stability/跨轮缓存四元组基建），命中且已复核过至少一次→跳过执行沿用归因；首次不沿用（复核豁免），与「缓存不得加固失败结论」原则兼容。「已复核过至少一次」以跨轮持久 STATE 字段记账（bump_counters 同款基建，跨重启持久；进程内变量不满足）。
- 退出锚点在 state_machine 的 unfreeze、新 run 落地、场景集写回三处既有咽喉挂解除。

## 取舍

- 不改 judge_gate 计数语义本身：重放守卫在更上游拦截，计数逻辑原样。
- 不采纳「首次耗尽即转人工」备选：保留现行「耗尽后排程一次复核重验」两态设计，防重放守卫只拦第二轮起的重放。
- 停泊态可见性不新增 UI：`frozen` 不置位故冻结标签不亮，复用受理门拒收分支既有 error 留痕与停泊位字段供 dashboard 与人工核查。

## 停泊位判定口径（复用 `_frozen_hold` 的边界约定）

- 复用仅指置位 `_frozen_hold` 本身；`frozen` 字段 MUST 保持不置位——一切派发由 `frozen` 挡、blocked_stuck 豁免、unfreeze 流程、dashboard 用户冻结标签、冻结清理豁免等连带语义均为用户冻结专用，纯归因停泊是框架有意等待态，二者不同面。
- `_frozen_hold` 单独置位按既有字段注释（state_machine.py:341 段「恢复链路不因它跳过，冻结期间由 frozen 字段挡住一切派发」）不挡任何链路——停泊的「不可调度」不靠该字段自身，靠 `spec_is_undriven` 单点停泊检查 + testing 态本无周期驱动达成。
- unfreeze 是「人工处置」退出锚点的既有咽喉；停泊态经 unfreeze 退出 MUST NOT 走 `_resolve_preserved_branch` 保留分支续做子路径（该子路径以 `_frozen_hold` 为「冻结终止现场保全」依据，state_machine.py unfreeze_spec 段），按普通解冻清理 + 重派退出——接线时对该子路径补停泊位/frozen 前置检查。