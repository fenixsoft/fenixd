## Deliverables

```yaml
- path: agents/planner-plan.md
  kind: modify
- path: core/agent_runner/prompt_builder.py
  kind: modify
- path: core/verify_engine/scenarios.py
  kind: modify
- path: core/pm_engine/verification/pipeline.py
  kind: modify
- path: tests/test_verify_scenarios.py
  kind: modify
- path: tests/test_planner_scenario_schema_alignment.py
  kind: modify
```

## 1. 规划任务书顶层契约

- [ ] 1.1 agents/planner-plan.md（:7-8 分批落盘工作流处）：把顶层形状升级为显式交付契约——「test_scenarios.json 顶层必须是纯 JSON 数组，MUST NOT 包裹 {"scenarios":[…]} 之类 dict」，附正反例各一行，并显式区分同目录 scenarios.json 的 dict 形态（持久化集，读端 core/verify_scenarios.py:279-284 要求 dict），说明两文件形状相反不得互抄。
- [ ] 1.2 core/agent_runner/prompt_builder.py：_scenario_schema_section（:2262 起）单源表新增顶层形态契约条目，随场景 schema 运行时注入且仅对 planner-plan 会话生效（planner-judge 等其他 agent_type 不受影响）；与 1.1 静态模板互为双保险。

## 2. 拒收路径最小修复

- [ ] 2.1 core/verify_engine/scenarios.py：load_scenarios（:1524 起）旁新增顶层拯救助手——入参顶层为 dict 且含 scenarios 数组时解包返回数组，其余形态原样报错；load_scenarios 本体语义不改（拯救由验收路径显式调用，见 2.2）。
- [ ] 2.2 core/pm_engine/verification/pipeline.py：验收失败归因点（:2097-2105）在判定失败前先走拯救助手——「dict 且含 scenarios 数组」则解包重过全部场景校验，通过即以解包结果落地并留痕（记录解包前顶层键与条目数）；仍失败照常进入 replan。REPLAN_FEEDBACK 写点（:2748-2754）按失败类别生成文案：格式类给「最小修复」指引（错误类别+修复动作），仅内容类缺失保留「重新输出全部场景」。

## 3. 测试

- [ ] 3.1 tests/test_verify_scenarios.py：补顶层门与拯救用例——非数组顶层被 load_scenarios 拒绝；拯救助手对 {"scenarios":[…]} 解包成功、对缺 scenarios 键/解包后非法的输入原样报错；纯数组输入不受影响。
- [ ] 3.2 tests/test_planner_scenario_schema_alignment.py：扩断言——planner-plan 注入内容含顶层纯数组契约与 scenarios.json dict 形态区分、planner-judge 注入不含该条目；格式类拒收的 REPLAN_FEEDBACK 文案含最小修复指引且不含「重新输出全部场景」，内容类仍保留全量重建指示。