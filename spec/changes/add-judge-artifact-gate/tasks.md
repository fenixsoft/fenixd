# Tasks: add-judge-artifact-gate

## Deliverables

```yaml
- path: core/agent_runner/runner.py
  kind: modify
- path: core/agent_runner/prompt_builder.py
  kind: modify
- path: agents/planner-judge.md
  kind: modify
- path: tests/test_agent_runner_gate.py
  kind: new
```

## 1. 结果文件硬门

- [ ] 1.1 core/agent_runner/runner.py：`_execute_agent` 成功判定处（exit 0 分支）对 `agent_type ∈ {planner-judge, planner-plan}` 追加产物校验——结果文件路径与 prompt_builder 注入的 `{result_path}` 同源计算（从 prompt_builder 抽取路径函数共用，防双实现漂移）；文件缺失/为空/非法 JSON → `success=False`，error 注明「exit 0 但结果文件缺失（judge 产物硬门）」，落入既有瞬态退避重试通道
- [ ] 1.2 core/agent_runner/prompt_builder.py：抽取 `planner_result_path(project_root, spec_name, agent_type)` 供注入与校验两侧共用；judge prompt 契约段注入「结果文件缺失 = run 失败」语义
- [ ] 1.3 tests/test_agent_runner_gate.py：exit 0 无产物 → success=False + 瞬态重试判定（不进裁决重试预算）；结果文件空/非法 JSON 同判；产物合规放行；planner-plan 无 test_scenarios.json 同判

## 2. judge 逐场景增量写盘

- [ ] 2.1 agents/planner-judge.md：步骤 4 改为逐场景 checkpoint（每归类一个非 PASS 场景立即原子覆盖写回 report.json，temp+rename 语义）；步骤顺序调整为先全部最小增强落盘、再深入调查复现；效率纪律段补「先落盘再深入」
- [ ] 2.2 core/agent_runner/prompt_builder.py：judge prompt 注入截断恢复段——重试时 report.json 可能含上轮部分增强，已带合法 classification 的场景直接沿用、只补缺失/非法场景
- [ ] 2.3 tests/test_agent_runner_gate.py：模拟部分增强的 report.json → 重试 prompt 含「沿用已归因场景」注入段；已归因场景不被二次改写（读侧校验）

## 3. 回归验证

- [ ] 3.1 既有回归全绿：test_pm_promotion_gate.py（judge 链）、test_pm_engine_dispatch_fixes.py、verify 相关测试无回归
- [ ] 3.2 端到端语义核对：模拟 judge exit 0 无产物 → 瞬态重试而非 validate_report 阻断；模拟中途截断 → report.json 含已归因场景合法分类
