## Deliverables

```yaml
- path: core/verify_engine/scenarios.py
  kind: modify
- path: core/verify_engine/engine.py
  kind: modify
- path: core/agent_runner/prompt_builder.py
  kind: modify
- path: core/verify_report.py
  kind: modify
- path: tests/test_verify_scenario_resource_mutex.py
  kind: new
```

## 1. 场景资源组互斥

- [x] 1.1 core/verify_engine/scenarios.py：TestScenario 增加可选字段 resource_group（缺省空串），from_dict/to_dict 透传（沿 viewport 字段扩展先例）；评估 SCHEMA_VERSION/CONTRACT_VERSION 迁移并同步冻结场景集（test_scenarios.json 与 _scenarios_full.json 同覆盖）。
- [x] 1.2 core/verify_engine/engine.py：_execute_parallel 增加同 resource_group 在飞互斥——组内有在飞场景时同组场景顺延下一批；批日志与报告记录互斥等待标记与有效并发度；未标记场景调度行为零变化；等待不计入场景超时；既有 report 顶层 effective_parallel 语义不变（配置/override 值），互斥等待标记与实测并发用新键承载。

## 2. 提示词词表与豁免上下文

- [x] 2.1 core/agent_runner/prompt_builder.py：场景 schema 文档段注册 resource_group 词表（权威源 scenarios.py），重型场景（交叉构建/模拟器/全量 ctest）同组示例；flaky 分类提示词要求豁免附同窗并行场景清单与有效并行度。
- [x] 2.2 core/verify_engine/engine.py：场景结果附同窗并行上下文（同批场景 id 清单+实测并行度）；core/verify_report.py：合成报告时豁免条目（场景级 flaky/env 分类行、断言级豁免清单）缺该上下文时落「证据不全」标记（spec.md Requirement 2 的确定性实现路径）。

## 3. 测试

- [x] 3.1 tests/test_verify_scenario_resource_mutex.py：覆盖同组串行/跨组并行/未标记零变化三类调度用例（范本 tests/test_verify_parallel_backoff.py）、等待标记与实测并发新键落报告断言（既有 effective_parallel 语义回归断言沿用 tests/test_verify_parallel_backoff.py 口径）、豁免条目缺并行上下文时报告落「证据不全」标记断言、schema 字段 round-trip 与未知键兼容。