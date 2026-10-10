## Deliverables

```yaml
- path: core/verify_engine/scenario_static_check.py
  kind: modify
- path: core/pm_engine/verification/pipeline.py
  kind: modify
- path: core/admin_monitor.py
  kind: modify
- path: tests/test_scenario_serve_consistency.py
  kind: new
```

## 1. 静态检查补交叉规则与挂载

- [ ] 1.1 core/verify_engine/scenario_static_check.py：scan_contract（:624 附近）入参补场景 kind 集合并新增 serve 缺失交叉规则——serve 段缺失（现 :654 直接空返回）且 kind 集含 api/web 时产出 serve 缺失 finding；serve 缺失时既有三条规则维持早退，不误报历史纯 CLI 契约。
- [ ] 1.2 core/pm_engine/verification/pipeline.py：契约静态检查挂载补全——冻结场景复用与并行出题产物消费路径（现仅 :3059 附近新鲜出题验收路径挂载）在消费前统一执行静态检查，kind 集与契约能力不匹配即打回补契约。

## 2. 前置探测收紧

- [ ] 2.1 core/admin_monitor.py：_preprobe_signal_satisfied（:2949-2952 附近）对 verify_contract_missing 的满足判定从「契约可解析」收紧为「serve 段存在或 commands.start 非占位（OR 关系），且能力可覆盖在途场景 kind 需求」；能力缺口未补齐时不 auto-resolve、信号保持 open 走正常唤起。

## 3. 测试

- [ ] 3.1 tests/test_scenario_serve_consistency.py：静态检查——kind 集含 api/web + 契约无 serve → 报 serve 缺失 finding；纯 cli + 无 serve → 不报（历史形态不回归）；serve 段存在时既有三条规则（serve_entry_missing / vs_start_mismatch / no_port_injection）行为不变。
- [ ] 3.2 tests/test_scenario_serve_consistency.py：挂载路径——冻结复用与并行产物路径的出题产物同样过静态检查，kind 不匹配被打回；新鲜出题验收路径既有行为不回归。
- [ ] 3.3 tests/test_scenario_serve_consistency.py：前置探测——契约可解析但无 serve 且在途场景含非 cli kind → 不 auto-resolve；契约补齐 serve 段后 → 恢复免唤起；start 非占位且场景全 cli → 判满足。