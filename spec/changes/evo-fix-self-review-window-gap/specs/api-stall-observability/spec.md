# api-stall-observability

## MODIFIED Requirements

### Requirement: 聚合窗口归属判据（终态归窗）
run 级聚合（数据摘要第 2 节 runs 统计与第 6 节逐 run api-stall 行）的窗口归属 SHALL 以 run 终态事件时刻为准：已终态 run 的终态时刻（取 run jsonl 产物文件 mtime；result 行无 timestamp 字段，MUST NOT 以 run_id 内嵌 epoch 归窗）落入 [window_start, window_end] 即归本窗。聚合时刻仍在飞（无终态产物）的 run 不列终态统计；起点晚于 window_start 的在飞 run 维持「在跑」展示口径。窗口按锚点链顺序分区，任一已终态 run 恰归一窗。

#### Scenario: 起点早于锚点但终态在窗内（夜间审查缝隙回归）
- **WHEN** run 起点早于 window_start（含亚秒级缝隙，如 run_id 内嵌 16:03:19.000 对锚点 16:03:19.776783）且聚合时已终态、终态时刻落在窗内
- **THEN** 该 run 计入本窗第 2 节与第 6 节聚合，停滞次数与合计同档案 run_metrics 一致

#### Scenario: 聚合时仍在飞
- **WHEN** run 在聚合时刻尚无终态产物
- **THEN** 本窗不列其终态统计；起点晚于 window_start 的在飞 run 计入「在跑」展示

#### Scenario: 终态跨窗补列不重计
- **WHEN** run 起点早于本窗锚点且聚合时仍在飞，其终态落入后续窗
- **THEN** 由后续窗按终态归窗补列，前窗不回溯重计，任一 run 全生命周期恰被一窗消费