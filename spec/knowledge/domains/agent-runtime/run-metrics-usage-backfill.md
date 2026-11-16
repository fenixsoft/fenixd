# run_metrics 用量终局回填

<!-- knowledge: capability=run-metrics-usage-backfill rev=1
     sources=spec/changes/evo-text-turn-inflation-response -->

run 终态落盘 run_metrics 时，对「网关逐消息不回传用量」的 run 从 run 末结果回填计量字段：保证 token 面可量化，同时不混用两套计量来源。

## 规则

- 触发判定：终态 run_metrics 落盘时逐消息累计载体全零（total_input_tokens 与 total_cache_read_tokens 均 0——逐消息累计侧只有 input/cache_read 两字段、无 output 载体），且读线程无残留存活（reader_stuck 时不消费共享 last_result，回填不触发）。
- 回填动作：从 run 末结果（last_result.usage）的真实用量回填既有计量键 input_tokens、cache_read_input_tokens；派生键 per_turn_input_tokens 由回填后 input 按同一整除口径重算。context_peak_tokens 为逐轮峰值，run 末聚合不可推得，保持原值不臆造。
- 单 run 不混源：逐消息累计非零时不覆盖（正常路径行为不变）——一个 run 要么整行走终局回填、要么整行走逐消息累计，不存在混合。
- 来源标注：usage_source="final_result_backfill" 仅在回填行落，转录行与同块日志侧行两 sink 同源同值均落；正常逐消息累计行不落该键，消费侧以键在场区分回填行与逐消息累计行。
- 防御与互斥：last_result 无 usage 或字段畸形时字段保持零、不异常；与击杀路径的 usage_missing 注记自然互斥（击杀无 result 时回填 no-op、注记照落）。
- 同名不同义陷阱：dsh 投影通道 result 事件另有 usage_source（available/unavailable/unobserved，表示 dsh 侧用量可得性），与本回填标注（final_result_backfill）同名不同义，消费侧勿混读。

## 代码锚点

- 主实现：core/agent_runner/runner.py（终态 run_metrics 落盘收尾块：转录行与同块日志侧行）
- 消费方：core/dashboard/data/runs.py（run_metrics 增量读侧）；usage_source 标注供需区分计量来源的消费侧过滤
- 守卫测试：tests/test_run_metrics_usage_backfill.py（全零回填+标注+派生键重算、非零不覆盖、无用量不异常、两 sink 同源同值）

## 溯源

- 2026-11-17 evo-text-turn-inflation-response（spec/changes/evo-text-turn-inflation-response/） — 新增本页：纯文本轮离群响应端交付之一，逐消息用量全零（网关逐消息不回传 usage、真实用量仅在 result 事件）时终态 metrics 落盘收尾块从 last_result 终局回填并落 usage_source 来源标注
