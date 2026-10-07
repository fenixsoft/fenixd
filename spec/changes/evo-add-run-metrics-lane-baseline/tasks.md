## Deliverables

```yaml
- path: core/self_review.py
  kind: modify
- path: core/agent_runner/run_files.py
  kind: modify
- path: core/agent_runner/maintenance_runs.py
  kind: modify
- path: core/agent_runner/runner.py
  kind: modify
- path: tests/test_self_review_midflight.py
  kind: modify
```

## 1. 分组基线修复

- [x] 1.1 core/self_review.py：_collect_metrics_outliers 分组键兜底——指标行缺 agent_type 时用 run_id 前缀经 infer_run_agent_type 推断车道归属，不再落入 unknown 混合组；组内样本不足的既有跳过语义不回退；越线倍数与最小样本常量不动
- [x] 1.2 core/agent_runner/run_files.py：RUN_ID_AGENT_PREFIXES 补 evo- 前缀（归 evolution），保持该表唯一真源；按 design 方案 1 的消费方核对清单逐项确认同源行为（dashboard/get_runs 时间线归属 agent→evolution 为预期变化；run_spec_part、admin_monitor 归一/驱动判定、pm_engine 归属/取消/活动判定、前端 AGENT_CATS 归族不回退）
- [x] 1.3 core/agent_runner/maintenance_runs.py 与 core/agent_runner/runner.py：补齐未分组车道数据源——maintenance 三车道（run_evolution/run_code_review/run_code_fix）收尾补 _log_run_metrics 富指标行（含 agent_type/cost_usd），context metrics 兜底行补 agent_type；若该点成本不可得则初筛侧交叉读 .fenix/cost/*_tokens.json 台账补成本维度，消除成本维度 0 样本失明

## 2. 车道基线降噪

- [x] 2.1 core/self_review.py：对 code-fix 等批量相关车道引入组内近期批分布 turns 基线（按 design 方案 3 参数约定：同车道近 N=10 批 P90、有效样本不足回退窗口中位、重试轮按 -r/-a 后缀辨识且不可辨不排除），并对定向重试轮单独标注或排除出基线样本，使正常长批不再越线、异常批仍被标出

## 3. 测试

- [x] 3.1 tests/test_self_review_midflight.py：补无 agent_type 指标行 + code-fix/evo/spec-review 混合窗口的分组断言、evo- 前缀推断断言、组内样本不足跳过语义、P90 基线与重试轮标注用例、成本维度台账交叉读取用例
- [x] 3.2 tests/test_self_review_midflight.py：补 run_files.py 前缀表变更对 dashboard/get_runs 同源行为的时间线归属回归断言（agent→evolution），及 evo-<epoch> run_id 的 run_spec_part 语义不回退断言（不得解析出真实 spec 名）