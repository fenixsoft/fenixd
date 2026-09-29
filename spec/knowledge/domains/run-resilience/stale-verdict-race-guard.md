<!-- knowledge: capability=stale-verdict-race-guard rev=1 sources=spec/archive/2026-09-12-fix-daemon-lifecycle-races -->

# 陈旧裁决竞态守卫

verifier / planner-judge 结果文件的新鲜度、归属与在飞一致性护栏：陈旧判定重放被拒，迟到结果不覆写更新的终态，也不触发补偿性重派。

## 现行规则

- 结果文件新鲜度与归属护栏：陈旧或异主（foreign）的判定结果重放被拒；更新的终态已落定后到达的迟到结果不覆写该终态。
- verifier / planner-judge 结果处理入口前置状态判据：处理时 spec 状态非 testing（如 stale-result 防护已将 spec 拨回 implemented 重派 fresh verify），结果按 DEBUG 级丢弃，日志注明 run_id 与当前状态；不执行状态迁移、不产生 ERROR 告警。
- 被状态判据拒绝的结果零派发：不存在「将 spec 转回 testing 并重新派发 verifier」的 fallback 路径，被拒结果不产生任何新的 verifier run（派发日志与 active_runs 计数可断言）。
- stale-result 防护把 testing 拨回 implemented 前，登记/取消在飞 verify run；在飞旧 verify run 完成时若 spec 已被重置，结果静默丢弃而非走失败迁移。
- 正常路径不受影响：结果到达时 spec 处于 testing，结果照常消费，testing→verified 迁移照常执行。

## 溯源

- 史前复原 — 迁移期基线：verifier 结果文件做新鲜度与归属护栏，陈旧判定重放被拒，迟到结果不覆写更新的终态
- [2026-09-12 fix-daemon-lifecycle-races](spec/archive/2026-09-12-fix-daemon-lifecycle-races/) — 结果处理入口增加在飞状态前置判据（非 testing 按 DEBUG 丢弃），拆除失败迁移 fallback 重派路径，收编 stale-result 重置与在飞 verify run 完成的竞态
