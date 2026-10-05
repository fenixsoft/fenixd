## Deliverables

```yaml
- path: core/verify_engine/scenarios.py
  kind: modify
- path: core/verify_engine/engine.py
  kind: modify
- path: core/agent_runner/prompt_builder.py
  kind: modify
- path: tests/test_verify_scenario_resource_mutex.py
  kind: new
```

## 1. 场景资源组互斥

- [ ] 1.1 core/verify_engine/scenarios.py：TestScenario 增加可选字段 resource_group（缺省空串），from_dict/to_dict 透传（沿 viewport 字段扩展先例）；评估 SCHEMA_VERSION/CONTRACT_VERSION 迁移并同步冻结场景集（test_scenarios.json 与 _scenarios_full.json 同覆盖）。
- [ ] 1.2 core/verify_engine/engine.py：_execute_parallel 增加同 resource_group 在飞互斥——组内有在飞场景时同组场景顺延下一批；批日志与报告记录互斥等待标记与有效并发度；未标记场景调度行为零变化；等待不计入场景超时。

## 2. 提示词词表与豁免上下文

- [ ] 2.1 core/agent_runner/prompt_builder.py：场景 schema 文档段注册 resource_group 词表（权威源 scenarios.py），重型场景（交叉构建/模拟器/全量 ctest）同组示例；flaky 分类提示词要求豁免附同窗并行场景清单与有效并行度。

## 3. 测试

- [ ] 3.1 tests/test_verify_scenario_resource_mutex.py：覆盖同组串行/跨组并行/未标记零变化三类调度用例（范本 tests/test_verify_parallel_backoff.py）、等待标记与有效并发度落报告断言、schema 字段 round-trip 与未知键兼容。