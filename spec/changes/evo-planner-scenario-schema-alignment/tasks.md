## Deliverables

```yaml
- path: core/verify_engine/scenarios.py
  kind: modify
- path: agents/planner-plan.md
  kind: modify
- path: core/pm_engine/verification.py
  kind: modify
- path: tests/test_planner_scenario_schema_alignment.py
  kind: new
```

## 1. 断言字段规则单源化

- [ ] 1.1 core/verify_engine/scenarios.py：把断言必填字段规则（output_match/file_content 需 expected、json_output 需 step+path 等）收敛为可引用的权威常量/函数（供校验与生成侧共用）
- [ ] 1.2 写端校验改读该单源（行为零变化回归）

## 2. planner 指令注入

- [ ] 2.1 agents/planner-plan.md：为每种 cli/api 断言类型给出必填字段说明与合法 JSON 样例（output_match 含 expected、json_output 含 step+path）

## 3. 写前客户端预校验

- [ ] 3.1 core/pm_engine/verification.py 落盘路径：planner 产出落盘前调用与写端一致的校验器，非法条目按条剔除留痕（场景 id + 缺失字段），合法部分照常落盘
- [ ] 3.2 整批剔除（超 20%）退回重排语义保留（回归断言）

## 4. 测试

- [ ] 4.1 tests/test_planner_scenario_schema_alignment.py：生成样例与校验规则一致性（output_match/json_output 合法样例通过写端校验）
- [ ] 4.2 单条非法剔除留痕 + 整批非法退回断言