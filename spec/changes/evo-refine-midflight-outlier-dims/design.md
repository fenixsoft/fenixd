# 设计：refine-midflight-outlier-dims

## 改动面

1. core/self_review.py 的 _collect_metrics_outliers（:1020-1140）：
   - 批量车道 cost_usd/duration_seconds 维：取 run 关联的台账条目数——来源钉定为指标行的 spec 字段经 core/run_task_track.parse_tasks_md(project_root, spec_name)（run_task_track.py:162）取 len(all)（台账总条目，与 code_fix chain rollup 的台账口径一致，core/code_fix.py:167-178）；回退约定为**整维级**：组内该维全部有效样本 run 均可得条目数才启用摊薄口径，任一 run 缺失（spec 缺失/解析失败/条目数为 0）则该维整体回退现状绝对口径——单一基线，不把摊薄值与绝对值混进同一次中位/P90 计算。run 值与组内基线统一换算为单位条目值后再过 :1126 的 3 倍判定；摘要行同时给摊薄前后两个数字，便于人工对账。
   - 新增纯文本轮占比维度：从 context metrics 行取原始 text_turns 与 turns（两者取自**同一条** context 行，混合行比值失真），双条件判定（turns 超阈值且占比超阈值），阈值常量加在 :833-850 常量区；行缺 text_turns 字段（dsh 通道、历史行无此字段）时该 run 该维跳过（缺样不入组，与 _metrics_outlier_dims :1008 数值>0 过滤同口径）；实现注释写明 dashboard 索引同名字段后行胜出（core/dashboard/data/runs.py:96-104）的取数坑——初筛读日志/归档行而非 dashboard 索引。
2. core/agent_runner/runner.py：context metrics 行打点（转录行约 :7222、日志侧 metric_type=run_metrics 行约 :7257）补 model；_log_run_metrics（:9132）接通休眠形参 model（:9141）并写入 metric 上下文；model 取 run 启动时实际解析的模型标识原样记录，不做跨 provider 归一。
3. core/self_review.py 摘要渲染（第六节，约 :2112-2124）：离群行输出摊薄数值与 model（有则附）。

## 取舍

- 摊薄归一而非直接套用 turns 维的 P90 车道基线：批内条目数才是两窗误报的混杂变量，摊薄直接消除；P90 车道基线可作后续演进，不在本变更内。
- 纯文本轮维度用「绝对轮数+占比」双条件，避免小 run 高占比噪音（如 4 轮中 3 轮纯文本）误标。

## 风险

- 条目数口径若与实际批大小不一（部分条目 skipped），摊薄分母偏大——统一用该 run 关联的台账条目数并与 rollup 口径一致。
- model 字段在不同 harness/provider 下命名不一，原样记录不归一，仅供人工对照。