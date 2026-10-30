# 设计：refine-midflight-outlier-dims

## 改动面

1. core/self_review.py 的 _collect_metrics_outliers（约 :950-1057）：
   - 批量车道 cost_usd/duration_seconds 维：取 run 关联的台账条目数（与初筛现有 run 元数据同源，口径与 chain rollup 的条目数一致；缺失回退绝对口径），run 值与组内基线统一换算为单位条目值后再过 :1057 的 3 倍判定；摘要行同时给摊薄前后两个数字，便于人工对账。
   - 新增纯文本轮占比维度：从 context metrics 行取原始 text_turns 与 turns，双条件判定（turns 超阈值且占比超阈值），阈值常量加在 :771-785 常量区；实现注释写明 dashboard 索引同名字段后行胜出（core/dashboard/data/runs.py:96-104）的取数坑——初筛读日志/归档行而非 dashboard 索引。
2. core/agent_runner/runner.py：context metrics 行打点（约 :6826-6862）补 model；_log_run_metrics（约 :8716）接通休眠形参 model 并写入 metric 上下文；model 取 run 启动时实际解析的模型标识原样记录，不做跨 provider 归一。
3. core/self_review.py 摘要渲染（第六节，约 :1916/:1978）：离群行输出摊薄数值与 model（有则附）。

## 取舍

- 摊薄归一而非直接套用 turns 维的 P90 车道基线：批内条目数才是两窗误报的混杂变量，摊薄直接消除；P90 车道基线可作后续演进，不在本变更内。
- 纯文本轮维度用「绝对轮数+占比」双条件，避免小 run 高占比噪音（如 4 轮中 3 轮纯文本）误标。

## 风险

- 条目数口径若与实际批大小不一（部分条目 skipped），摊薄分母偏大——统一用该 run 关联的台账条目数并与 rollup 口径一致。
- model 字段在不同 harness/provider 下命名不一，原样记录不归一，仅供人工对照。