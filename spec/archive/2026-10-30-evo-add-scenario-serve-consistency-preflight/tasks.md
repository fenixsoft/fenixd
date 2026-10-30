## Deliverables

```yaml
- path: core/verify_engine/scenario_static_check.py
  kind: modify
- path: core/pm_engine/verification/pipeline.py
  kind: modify
- path: core/pm_engine/verification/scenario_gate.py
  kind: modify
- path: core/admin_monitor.py
  kind: modify
- path: tests/test_scenario_serve_consistency.py
  kind: new
```

## 1. 静态检查补交叉规则与挂载

- [x] 1.1 core/verify_engine/scenario_static_check.py：scan_contract（:624 附近）以**可选参数**补场景 kind 集合与 commands.start 兜底形态（默认 None：缺省时跳过新增交叉规则，既有单参调用方 tests/test_verify_preflight_gate.py 全部不破）并新增 serve 缺失交叉规则——serve 段缺失（现 :654 直接空返回）且 kind 集含 api/web 且 start 无有效兜底（空或占位哨兵，口径同 serving.py:1098-1099）时产出 serve 缺失 finding；serve 缺失时既有三条规则维持早退，不误报历史纯 CLI 契约与 start 兜底存量形态。
- [x] 1.2 core/pm_engine/verification/pipeline.py + core/pm_engine/verification/scenario_gate.py：契约静态检查挂载补全——冻结场景复用（_load_frozen_or_escalate :1414，消费点 :2860 附近）与并行出题产物消费（_consume_parallel_plan_product :2650，消费点 :2856 附近）在消费前统一执行静态检查；既有新鲜出题验收路径的调用方 scenario_gate.py:862 同步传入 kind 集与 start 兜底形态（否则新规则在主路径永不生效）。「打回」机制对齐 selfcheck 先例（pipeline.py:3153-3175）：serve 缺失 cross finding 走 _write_verify_contract_missing 通道阻断场景执行、派发 Administrator 起草，不触发 planner replan（重排出题无助于契约缺口）；既有三条规则维持留痕不阻断；检查器异常沿用 scan_contract 既有 fail-open 不阻断验证。

## 2. 前置探测收紧

- [x] 2.1 core/admin_monitor.py：_preprobe_signal_satisfied（:2949-2952 附近）对 verify_contract_missing 的满足判定从「契约可解析」收紧为「serve 段存在或 commands.start 非占位（OR 关系），且能力可覆盖在途场景 kind 需求」；能力缺口未补齐时不 auto-resolve、信号保持 open 走正常唤起。实现约定：谓词需扩参传入 spec 名（现签名只收 stype，调用方持 rec/spec 可直传）；在途场景 kind 集从 verify-progress/<spec>/ 场景文件按执行 kind 原样统计（与执行期 serving.py 同口径），文件缺失/不可解析时 kind 集按空集处理（退化为 serve/start 存在性判定）；「非占位」判定口径同 serving.py:1098-1099 哨兵；共用分支的 verify_regression_missing 语义（regression 段存在性）不得变动。

## 3. 测试

- [x] 3.1 tests/test_scenario_serve_consistency.py：静态检查——kind 集含 api/web + 契约无 serve + start 占位/缺失 → 报 serve 缺失 finding；kind 集含 api/web + 契约无 serve + start 非占位（commands.start 兜底存量形态）→ 不报；纯 cli + 无 serve → 不报（历史形态不回归）；不传 kind 集（既有单参调用）→ 行为与现状一致；serve 段存在时既有三条规则（serve_entry_missing / serve_entry_vs_start_mismatch / serve_entry_no_port_injection）行为不变。
- [x] 3.2 tests/test_scenario_serve_consistency.py：挂载路径——冻结复用与并行产物路径的出题产物同样过静态检查，kind 不匹配被打回；新鲜出题验收路径既有行为不回归。
- [x] 3.3 tests/test_scenario_serve_consistency.py：前置探测——契约可解析但无 serve 且在途场景含非 cli kind → 不 auto-resolve；契约补齐 serve 段后 → 恢复免唤起；start 非占位且场景全 cli → 判满足。