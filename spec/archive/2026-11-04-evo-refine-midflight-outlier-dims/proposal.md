# 提案：离群初筛按台账条目归一并新增纯文本轮占比维度

## 背景（已核实，连续两窗）

- core/self_review.py 的中途信号离群初筛以「超同型组中位 3 倍」（:836 MIDFLIGHT_OUTLIER_MULTIPLIER=3）对比 cost_usd/duration_seconds（:843 维度表），无按台账条目数归一（:1020 _collect_metrics_outliers 函数体内无条目数除法）。批量修复 run 因批量大天然超绝对阈值：
  - 2026-10-17 窗：code-fix-1792257163（修 9 条）cost_usd=3.401011 对组中位 0.4827095 标 7.05 倍、duration 521.22 对 146.85 标 3.5 倍；实际摊薄 0.378 美元/条、57.9 秒/条，与基线批 code-fix-1792170715（修 11 条，0.329 美元/条、49.2 秒/条）仅差 15-18%。组中位数已用日志原始数独立复算精确吻合（摘要嵌于 dsh-plugins 项目 .fenix/runs/archive/review-2026-10-18.jsonl）。
  - 2026-10-16 窗：code-fix-1792158323（修 19 条）被标 7.45 美元为中位 3.6 倍——即 todo 10-17 改进条『cost 计量与 token 量纲失真』，当时演化侧按单窗首现判「不需要」；本窗同根因再现，构成复发。
- 同轮真实异常观测不到：该 run turns=204 中 125 轮（61%）是无 tool_use 的纯文本轮（基线批 22/104=21%），latency_stalls=0——纯文本轮通胀是模型输出行为漂移的可见信号，cost/时长/停滞三维度均不捕获。
- 误报后果核实：仅进自省摘要（core/self_review.py 中途信号采集段 :828 一带「降噪铁律」注释，零自动动作），实损是摘要噪音与演化复核注意力：两窗各衍生一条 todo 条目，10-17 条已白跑一轮演化复核，本条再烧一轮核查。

## 提案（三件事，与 10-17 条建议合并落地）

1. 批量车道（MIDFLIGHT_BATCH_BASELINE_LANES，:850）的 cost_usd/duration_seconds 离群基线改按台账条目数摊薄对比，消除批量 run 绝对倍数误报；turns 维已有近期批 P90 车道基线（evo-add-run-metrics-lane-baseline 已落地），本提案不动它。
2. 新增 text_turns 占比维度（turns 超阈值且纯文本轮占比超阈值即标记），让无停滞的轮次通胀可观测；取数须用 context metrics 行原始值（dashboard 索引同名字段后行胜出，core/dashboard/data/runs.py:96-104，code-fix run 的 turns 在索引里被终态行覆盖为小值）。
3. run_metrics 补 model 字段：context 行与终态行（_log_run_metrics，core/agent_runner/runner.py:9132 已有休眠形参 model，:9141）落实际模型标识，使轮次通胀可与模型版本对照。

## 与存量 SPEC 的关系

- 在途 evo-add-run-metrics-lane-baseline 主题是分组键兜底+批量车道 turns P90+富指标行，不覆盖本提案三项，属自然延伸不重叠；evo-api-stall-signal-grading 是停滞信号分级。
- 归档 2026-10-03-add-self-review-midflight-signals 是初筛本体、2026-10-06-evo-add-codefix-digest-cost-metrics 把 text_turns 引入 digest 但非离群维度——均不重复。