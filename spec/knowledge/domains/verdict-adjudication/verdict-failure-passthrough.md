<!-- knowledge: capability=verdict-failure-passthrough rev=1 sources=spec/archive/2026-09-15-fix-verdict-retry-misattribution -->

# 失败结论透传

裁决失败信息的结构化透传：violations 明细、失败分型与轮间 diff 进入告警，error 文案与事实一致，两套轮次口径显式区分。

## 现行规则

- `cause=violations` 触发的 `verdict_evidence_invalid` 告警在 evidence 中携带结构化 violations 明细：逐条 `scenario_id` + `reason`，超过 20 条截断并注明总数；不只输出固定概要文案（人工无需读 report.json 即可定位违规形状）。
- STATE error 按 cause 生成：「重试一次仍不合规」表述仅出现在 `cause=violations`（重试确实发生）路径；frozen/cancelled/异常/派发失败路径不产出引用「已重试」的文案（让位路径按 verdict-failure-semantics 零写入，不落 error）。
- 失败历史侧车：pm_engine 维护 `.fenix/verify-progress/<spec>/fail_history.json`，每轮裁决采纳失败时原子追加 `{round, cause_type, failed_scenarios}` 条目；spec 进入终态（verified/pushed）时清空；侧车写盘失败静默降级（分型标注 unknown），不阻断升级闸门。
- `verify_fail_escalation` 告警 evidence 携带：① 失败分型——各失败轮归类为 `evidence-invalid`（证据校验不合规）/ `real-bugs`（真缺陷）/ `repeat`（失败场景集与上轮完全相同）/ `unknown`（侧车缺失）；② 相邻两轮 failed_scenarios 的 diff（新增/消失/持留）。`fail_rounds` 计数逻辑本身保持不变（仅增强透传）。
- 轮次口径命名区分：涉及验证失败轮次的日志与告警文案显式区分「原地打回第 N 轮」（bug-found 打回链计数）与「升级闸门连续失败第 N 轮」（fail_rounds 计数），不使用不带限定的「第 N 轮 / 连续失败 N 轮」裸表述。

## 溯源

- 2026-09-15 fix-verdict-retry-misattribution（spec/archive/2026-09-15-fix-verdict-retry-misattribution） — 确立 violations 明细入告警、STATE error 按 cause 生成、fail_history.json 失败历史侧车、升级告警失败分型与轮间 diff、双轮次口径限定词
