## Deliverables

```yaml
- path: core/verify_contract.py
  kind: modify
- path: core/verify_contract_template.yaml
  kind: modify
- path: tests/test_regression_coverage_gap.py
  kind: new
```

## 1. 一致性预检（core/verify_contract.py）

- [x] 1.1 core/verify_contract.py：契约解析/校验路径新增 prepare↔regression 交叉比对——prepare 步骤按 `--dir <pkg> install/build` 形态提取包目录集，与 regression cmd 文本引用集比对；命中缺口发 `regression_coverage_gap` WARNING（附缺口包清单与 regression 段行号指引），不阻断加载；识别不出形态、regression 段缺省（引导态合法形态）均保守跳过；提取形态覆盖 install（含尾随 flags）与 run build 两变体
- [x] 1.2 core/verify_contract.py：对称契约与纯 pytest 形态契约零输出回归保护（既有解析结果与校验违例集合零变化）

## 2. 模板指引（core/verify_contract_template.yaml）

- [x] 2.1 core/verify_contract_template.yaml：regression 段指引补「新增被测插件进 prepare（install/build）时 MUST 同步注册 regression install+test 条目（--frozen-lockfile --prefer-offline 形态）」；prepare 段指引补对称提示

## 3. 测试（新建 tests/test_regression_coverage_gap.py）

- [x] 3.1 tests/test_regression_coverage_gap.py：半收编契约（prepare 有 pnpm --dir 条目、regression 无该包引用）→ 发 regression_coverage_gap WARNING 且缺口清单含包名、加载不阻断
- [x] 3.2 tests/test_regression_coverage_gap.py：对称契约（cc-import/dashboard-bridge 形态）与纯 pytest 契约 → 零 WARNING、既有校验结果零变化