# Design: pure-attribution-parking-recovery-guard

## 根因链

四环回环，均已回源：①受理门拒收后仅留痕（pipeline.py:1877-1990），spec 停 testing 无驱动；②orphaned_state 探测把 testing 无驱动当异常（60m 冷调节流只压频率不消解）；③Recovery（event_bus.py:640-678）守卫仅 inconclusive/undriven/admin 在飞三项，无条件重派全量验证；④judge rerun 计数在派发判定处 +1（judge_gate.py:717-760），清零点仅 verified+unfreeze——重放轮计入连败直至 6/5 冻结。

## 方案

- 停泊态复用 state_machine.py:341 既有 `_frozen_hold` 字段（零新增 schema）：纯归因进入时置位并留原因；orphaned_state 探测与 Recovery 守卫各加一处停泊位检查。
- 防重放守卫读取末轮 judge 归因（prev-judge-result.json 的 test-defect 分类）与场景集/产物指纹（现有 verdict_stability/跨轮缓存四元组基建），命中且已复核过至少一次→跳过执行沿用归因；首次不沿用（复核豁免），与「缓存不得加固失败结论」原则兼容。
- 退出锚点在 state_machine 的 unfreeze、新 run 落地、场景集写回三处既有咽喉挂解除。

## 取舍

- 不改 judge_gate 计数语义本身：重放守卫在更上游拦截，计数逻辑原样。
- 不采纳「首次耗尽即转人工」备选：保留现行「耗尽后排程一次复核重验」两态设计，防重放守卫只拦第二轮起的重放。
- 停泊态可见性沿用 frozen_hold 既有展示面，不新增 UI；停泊原因留痕在停泊字段供 dashboard 与人工核查。