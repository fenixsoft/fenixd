# 验证报告：evo-add-run-metrics-lane-baseline

> ⚠️ 本报告由框架于 2026-10-07T18:23:34Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-10-07T18:23:33.875731+00:00+run-result@mtime1791397413907586716

## 结论：✅ 通过（verified）

**状态：verified — 5/5 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 5/5 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 5 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 3.17M |
| 本链增量 Token（输出） | 0.06M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| metrics-grouping-fallback-evo-prefix | 1.1 分组键兜底 + 1.2 evo- 前缀推断（行为级）：构造无 agent_type 字段的 run_metrics 行（maintenance 三车道/context metrics 兜底行形态，runner.py:6429-6460 兜底行现无 agent_type），验证 _collect_metrics_outliers 分组键优先 metric.agent_type、缺失时按 run_id 前缀经 infer_run_agent_type 归组——code-fix- 前缀归 code-fix、evo- 前缀归 evolution，均不落入 unknown 混合组；spec-review 组样本 <3 保持既有跳过语义（core/self_review.py:826-840）；infer_run_agent_type('evo-<epoch>') 归 ('evolution', …)（run_files.py:56）；未识别前缀回退 ('agent', …)；run_spec_part('evo-<epoch>') 不解析出真实 spec 名（run_files.py:144-166） | pass | 0/8 | - |
| get-runs-timeline-attribution-evo | 1.2 RUN_ID_AGENT_PREFIXES 补 evo- 后的 dashboard/get_runs 时间线归属回归（行为级）：core/dashboard/data/runs.py:607 经 infer_run_agent_type 归属，evo-<epoch> run 由 agent → evolution（预期变化，design 方案 1 消费方核对清单）；code-fix-/impl- 前缀归属不回退 | pass | 0/4 | - |
| p90-lane-baseline-noise-reduction | 2.1 车道基线降噪（行为级）：code-fix 车道组内近期批分布 turns 基线（design 方案 3：近 N=10 批 P90、样本不足回退窗口中位、重试轮 -r/-a 后缀辨识）——构造近 10 批 turns 分布 [25,30,35,40,45,58,62,66,70,80]（组中位 51.5、P90≈71），验证正常长批 158 不再越线（P90×3≈213>158，而窗口中位×3≈154.5<158 精确区分新旧实现）、超分布批 500 仍被标出（>213）；重试轮 400（code-fix-*-r1 后缀）观察输出供实现者对照（单独标注或排除出基线样本均达标，行为由实现者测试 3.1 覆盖） | pass | 0/3 | - |
| cost-dim-lane-via-rich-row | 1.3 成本维度可观测（写侧富指标行主路径，行为级）：design 方案 2 为二选一且优先写侧（maintenance 三车道收尾补 _log_run_metrics 富指标行，maintenance_runs.py:1235/:1917/:2772 已落 agent_type/cost_usd），读侧台账交叉读仅是「写点成本不可得」的条件兜底（tasks.md 1.3「若该点成本不可得则」）——本场景按设计采用的主路径验证成本维度参与车道基线：3 个 code-fix 富指标行（context 含 agent_type/cost_usd，_log_run_metrics 同形态）turns 10/11/12 无 turns 离群，cost 1.0/1.2/5.0 使 5.0 批越线被标出，消除成本维度 0 样本失明 | pass | 0/3 | - |
| midflight-test-suite-regression | 3.1/3.2 测试交付回归（回归点）：pytest tests/test_self_review_midflight.py -v --tb=short 全文件通过（含实现者新增的分组兜底/evo 前缀推断/样本不足跳过/P90 基线/成本台账交叉读取用例，3.1）；run_files.py 前缀表变更的 dashboard/get_runs 时间线归属回归断言（agent→evolution）与 evo-<epoch> run_spec_part 语义不回退断言亦在本文件内（3.2）；存量用例 PASSED 不回退（分组中位/样本不足跳过/成本全缺失跳过/索引异常空返回） | pass | 0/6 | - |

## 本轮场景集变更

当前稳定场景集共 6 个（第 1 轮）。

- 首轮写入 6 个场景

