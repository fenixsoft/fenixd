## Deliverables

```yaml
- path: core/pm_engine/verification/scenario_gate.py
  kind: modify
- path: core/pm_engine/verification/pipeline.py
  kind: modify
- path: tests/test_contract_kind_serve_precheck.py
  kind: new
```

## 1. 出题产物前置校验

- [ ] 1.1 core/pm_engine/verification/scenario_gate.py：把消费期契约静态检查中的 kind 集交叉规则校验（serve_missing_for_scenario_kinds）抽成可独立调用的入口，供产物写盘/验收点复用；消费期门行为保持不变
- [ ] 1.2 core/pm_engine/verification/pipeline.py：在出题产物写盘点与验收点按产物 kind 集调用该入口校验 .fenix/verify.yaml serve/ready 段位；命中时经既有 verify_contract_missing 通道出单条信号（实现期遵守在途 verify-contract-precheck-noise-reduction 的 info 级+同 spec 一次性语义），不阻断产物落盘、不触发 planner replan
- [ ] 1.3 信号 evidence 携带定向补段情报（scenario_kinds、契约文件路径、缺失段位清单），复用既有 evidence 形态，使代起草处置无需重新考古出题产物

## 2. 测试

- [ ] 2.1 tests/test_contract_kind_serve_precheck.py：覆盖产物 kind 集含 api/web 且契约无 serve 段→写盘时出信号、契约段位齐备→零信号、契约缺失或解析失败→fail-open 放行落盘三场景
- [ ] 2.2 tests/test_contract_kind_serve_precheck.py：回归锚——消费期静态门保留为最后防线（打回行为不变）、实现期信号 info 级一次性不召唤 Administrator、同 spec 同缺口不重复发信号