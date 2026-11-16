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

- [ ] 1.1 agents/planner-plan.md：timeout 字段描述（约 :124）补「单位为秒、上限 1800」显式约定与合法示例值，与校验器文案口径一致

## 2. 报错嫌疑提示

- [ ] 2.1 core/verify_engine/scenarios.py：timeout 校验分支（约 :48）对「超上限且可被 1000 整除」的值附加「疑似毫秒，建议除以 1000」提示，其余超限维持现文案

## 3. 测试

- [ ] 3.1 tests/test_scenario_timeout_unit_contract.py：覆盖「毫秒形态值报错含疑似毫秒提示」「秒级超限不误报嫌疑」「合法秒值通过校验」「提示词文本含 timeout 单位约定」四场景