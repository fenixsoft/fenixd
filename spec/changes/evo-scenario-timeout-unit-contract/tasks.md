## Deliverables

```yaml
- path: agents/planner-plan.md
  kind: modify
- path: core/verify_engine/scenarios.py
  kind: modify
- path: tests/test_scenario_timeout_unit_contract.py
  kind: new
```

## 1. 提示词单位约定

- [ ] 1.1 agents/planner-plan.md：timeout 与 sse_connect duration 字段描述（:124 可选字段行及特异规则节）补「单位为秒、上限 1800」显式约定与合法示例值，与校验器文案口径一致

## 2. 报错嫌疑提示

- [ ] 2.1 core/verify_engine/scenarios.py：验收层 timeout 校验分支（:1776-1780）与 duration 校验分支（:1805-1808）对「超上限且可被 1000 整除」的值附加「疑似毫秒，建议除以 1000」提示，其余超限维持现文案；:48 的 MAX_STEP_TIMEOUT 为只读引用（不改值），运行层镜像拦截（cli_runner.py:395、api_runner.py:315/:655）文案不变

## 3. 测试

- [ ] 3.1 tests/test_scenario_timeout_unit_contract.py：覆盖「毫秒形态 timeout 值报错含疑似毫秒提示」「毫秒形态 duration 值报错含同款提示」「秒级超限不误报嫌疑（如 2400）」「合法秒值通过校验」「提示词文本含 timeout/duration 单位约定且上限数值与 scenarios.MAX_STEP_TIMEOUT 一致」「含非法时长的场景集 validate_scenario errors 非空（整批退回现状回归，对应 spec『单位错误不落盘』）」六场景