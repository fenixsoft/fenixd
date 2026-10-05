## Deliverables

```yaml
- path: agents/implementer.md
  kind: modify
- path: agents/planner-plan.md
  kind: modify
- path: core/agent_runner/prompt_builder.py
  kind: modify
- path: core/agent_runner/result_gate.py
  kind: modify
- path: tests/test_honest_exit_convergence.py
  kind: modify
- path: tests/test_agent_prompt_files.py
  kind: modify
```

## 1. 勾选纪律与提示词同步

- [x] 1.1 agents/implementer.md：任务勾选纪律——字面验收未满足 MUST NOT 勾选完成；替代验证 MUST 在任务行内注明「以 X 替代验收」并在 run 结果 findings 登记验收偏差条目（{task, literal, substitute}，附替代证据路径）。
- [x] 1.2 core/agent_runner/prompt_builder.py：与 result_gate 单源同步勾选纪律措辞进实现者提示词，防两侧漂移。

## 2. findings 白名单与硬门校验

- [x] 2.1 core/agent_runner/result_gate.py：impl run 结果新增 findings 数组字段（条目 {type: "acceptance-deviation", task, literal, substitute}，implementer/fast-track 两车道同义生效，提示词结果模板段同步字段说明）；新增组合校验——run 结果 success 且偏差任务出现在 completed_tasks 时拒绝（复用 artifact-structural 标签路径）；partial/unattainable 通道不感知该字段、语义不变。
- [x] 2.2 agents/planner-plan.md：带验收偏差注解的任务按替代方式出验证场景，不按字面验收出场景链。

## 3. 测试

- [x] 3.1 tests/test_honest_exit_convergence.py：新增用例——success∧偏差∈completed_tasks 被拒、partial 携带偏差放行、无偏差零影响、闭环路径（偏差任务经 unfinished 申报 partial 后，重规划替代场景链验收的后续 success 轮不含偏差条目可勾选通过）。
- [x] 3.2 tests/test_agent_prompt_files.py：新增提示词契约断言——implementer/planner-plan 含勾选纪律与替代注明措辞（与 result_gate 单源一致）。