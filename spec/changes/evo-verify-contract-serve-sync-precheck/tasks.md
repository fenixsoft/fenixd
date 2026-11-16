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

- [x] 1.1 core/pm_engine/verification/scenario_gate.py：把消费期契约静态检查中的 kind 集交叉规则校验（serve_missing_for_scenario_kinds）抽成可独立调用的入口，供产物写盘/验收点复用；消费期门行为保持不变
- [x] 1.2 core/pm_engine/verification/pipeline.py：在出题产物写盘点与验收点按产物 kind 集调用该入口校验 .fenix/verify.yaml serve/ready 段位；命中时经既有 verify_contract_missing 通道出单条信号，不阻断产物落盘、不触发 planner replan。信号落地机制（通道现硬编码 severity="major" 且语义为召唤 Administrator，须先落地）：① 通道 severity 参数化（默认 major，消费期既有调用点零变化），前置挂点传 info（info 级经 AdminStore 沉淀、既有 _handle_signal info 分支语义不召唤）；② 同 spec 一次性去重复用既有判据 store.has_unhandled_signal(spec, "verify_contract_missing")（持久判据随告警账本、daemon 重启不重发、处置后复位，口径同 admin_monitor 周期预检降噪实现）；③ info 级判定不沿用周期预检 ready/implementing 状态机窗口——出题产物挂点命中一律 info
- [x] 1.3 信号 evidence 携带定向补段情报（scenario_kinds、契约文件路径、缺失段位清单），复用既有 evidence 形态，使代起草处置无需重新考古出题产物
- [x] 1.4 去重边界锚定：前置信号去重只约束前置挂点自身（写盘点/验收点跨挂点同 spec 同缺口单条）；消费期静态门行为不变（major 打回+召唤为最后防线，不受去重抑制），design Risks 第 2 条按此口径解读

## 2. 测试

- [ ] 2.1 tests/test_contract_kind_serve_precheck.py：覆盖产物 kind 集含 api/web 且契约无 serve 段→写盘时出信号、契约段位齐备→零信号、契约缺失或解析失败→fail-open 放行落盘三场景
- [ ] 2.2 tests/test_contract_kind_serve_precheck.py：回归锚——消费期静态门保留为最后防线（打回行为不变）、实现期信号 info 级一次性不召唤 Administrator、同 spec 同缺口不重复发信号