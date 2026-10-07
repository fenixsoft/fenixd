# add-run-metrics-lane-baseline

## Why

run 指标离群初筛（add-self-review-midflight-signals，已归档）设计意图为「同 agent_type 窗口组中位数」，但 code-fix/code-review/evo/spec-review 车道从不写带 agent_type 的终态富指标行（_log_run_metrics 仅覆盖 _execute_agent 家族路径），这些 run 全部落进 unknown 混合组取中位——2026-10-08 窗口实测 21 个离群里 12 个是正常交付的 code-fix 批（turns 158-826 对混合中位 42 全员越线），100% 误报；evo-1791224502 型真实离群反被噪音稀释、靠人工挑出。加重项：unknown 组 cost_usd 有效样本为 0，成本初筛对这些车道完全失明（turns 2114、cost 85.68 美元的 code-review 全仓扫描从未被成本维度看见）。另实测：仅按车道分组修复基线语义但降不了噪（code-fix 组内中位 49×3=147<158），须叠加车道内历史批分布基线。

## What Changes

- 分组键兜底：_collect_metrics_outliers 在指标行缺 agent_type 时用 run_id 前缀推断（infer_run_agent_type）分组；RUN_ID_AGENT_PREFIXES 补 evo- 前缀，保持该表唯一真源。
- 数据源补齐：maintenance_runs 三车道（run_evolution/run_code_review/run_code_fix）收尾补 _log_run_metrics 富指标行（含 agent_type/cost_usd），context metrics 兜底行补 agent_type；或初筛侧交叉读 .fenix/cost/*_tokens.json 台账补成本维度（二选一），消除成本维度失明。
- 车道基线降噪：对 code-fix 等批量相关车道引入组内历史批分布基线（如同链/近 N 批 turns P90）替代窗口中位，或对定向重试轮单独标注。
- 验收：落地后同窗口重放复核第六节清单（基线：本窗口 12/12 全误报）——修复前后旗标集合 diff 逐条可解释：消除项与新基线一致，保留/新标项须为超分布异常批或重试轮标注；evo-1791224502 型真实离群仍在榜且不被同车道噪音稀释。

## Impact

- Affected specs: self-review-midflight-signals（MODIFIED：离群初筛分组基线与数据源）
- Affected code:
  - core/self_review.py：_collect_metrics_outliers 分组兜底与车道基线
  - core/agent_runner/run_files.py：RUN_ID_AGENT_PREFIXES 补 evo- 前缀
  - core/agent_runner/maintenance_runs.py：三车道收尾补富指标行
  - core/agent_runner/runner.py：context metrics 兜底行补 agent_type
- Tests:
  - tests/test_self_review_midflight.py 扩展
- 风险：低——读侧兜底与写侧补字段均为增量；run_files.py 前缀表为 dashboard/get_runs 同源，需回归时间线归属。