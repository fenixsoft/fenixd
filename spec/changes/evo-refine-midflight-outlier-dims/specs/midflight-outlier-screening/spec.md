# 能力：midflight-outlier-screening（自省中途信号离群初筛）

## 需求

### R1 批量车道按条目归一

- 对 MIDFLIGHT_BATCH_BASELANES（core/self_review.py:785）内车道的 cost_usd 与 duration_seconds 维，离群对比改用按台账条目数摊薄的口径：run 值与组基线均换算为单位条目值后再做 3 倍判定；条目数不可得时回退现状绝对口径。
- 单条目 run 行为与现状一致（摊薄后等于原值）。
- turns 维的近期批 P90 车道基线（evo-add-run-metrics-lane-baseline 已落地）保持不变。

### R2 纯文本轮占比维度

- 新增离群维度：turns 超过阈值（缺省 100）且 text_turns 与 turns 之比超过阈值（缺省 50%）即标离群，kind 标明为纯文本轮占比；阈值常量与 MIDFLIGHT_OUTLIER_* 同处收口（core/self_review.py:771-785 一带）。
- 取数用 context metrics 行的原始 text_turns 与 turns（非 dashboard 索引合并后的同名覆盖值，见 core/dashboard/data/runs.py:96-104 的后行胜出语义）。

### R3 run_metrics 补 model 字段

- context metrics 行与终态 run metrics 行均记录实际使用的模型标识 model；终态行接通 _log_run_metrics 既有休眠形参（core/agent_runner/runner.py:8716）。
- 离群行与摘要行在有 model 值时附带输出，便于轮次通胀与模型版本对照。

## Scenario

- Scenario 批量 run 不再误标：修 9 条、cost 3.401、521 秒、组内为单条目小 run 集合 → 摊薄后不标离群。
- Scenario 真实异常仍可标：摊薄值超组摊薄中位 3 倍 → 标离群。
- Scenario 纯文本轮通胀可观测：turns=204、text_turns=125 → 标纯文本轮占比离群；turns=104、text_turns=22 → 不标；低轮数高占比（如 4 轮中 3 轮纯文本）→ 不标。
- Scenario model 可对照：run_metrics 两行均含 model 字段，摘要离群行附带输出。