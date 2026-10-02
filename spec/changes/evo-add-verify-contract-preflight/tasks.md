## Deliverables

```yaml
- path: core/verify_contract.py
  kind: modify
- path: core/admin_monitor.py
  kind: modify
- path: tests/test_verify_contract_template_preflight.py
  kind: new
```

## 1. 落地校验

- [ ] 1.1 core/verify_contract.py：新增公共只读判定函数（如 `contract_file_unresolvable(project_root) -> bool`）：`.fenix/verify.yaml` 文件存在且 `_load_verify_contract_with_raw`（:252）返回 (None, None) 时为 True；文件缺失时为 False（维持「无契约回退」既定语义）；内部复用既有 loader，不二次 read_text、不引入第二套解析口径。
- [ ] 1.2 core/admin_monitor.py：新增检测器 `_detect_verify_contract_unresolved(specs)` 并挂入 `_detect`（:1932 汇总列表）：存在状态为 ready 或 implementing 的 spec 且 1.1 判定为 True 时，返回 `verify_contract_missing` 信号（spec 名、description 注明「前置预检：验证契约仍为未裁决模板态；spec 仍在实现流程中，起草落位即可，勿复位 spec 状态」、evidence 含项目根与契约路径、recommended_action 沿用 :346 既有起草指引）；**项目级单例**：同项目多个 spec 命中时仅返回一条信号（spec 字段取首个命中 spec），契约是项目级产物，不得按 spec 数量放大唤起（既有节流按 (spec, signal_type) 判定、对不同 spec 不互斥）；testing 及之后状态不触发；信号写入走既有 store 通道与节流，不新增去重机制；检测器自身异常按巡检惯例 fail-open。

## 2. 测试

- [ ] 2.1 tests/test_verify_contract_template_preflight.py：覆盖——(a) 全注释模板 + ready spec → 检测器产出 `verify_contract_missing` 信号且 spec 字段正确；(b) 有效契约（含实质 prepare/regression 段）+ ready spec → 不产出信号；(c) 契约文件缺失 + ready spec → 不产出信号；(d) 模板态但 spec 已 testing → 不产出信号；(e) 契约在信号在途期间被修正为可解析 → 既有 PREPROBE 探测判满足、免唤起 Administrator；(f) 检测器在 loader 抛异常时不阻断其余检测器执行；(g) 全注释模板 + implementing 状态 spec → 产出信号（implementing 分支覆盖）；(h) 多个 ready/implementing spec 命中 → 仅产出一条信号（spec 字段为首个命中 spec），不按 spec 数量放大。