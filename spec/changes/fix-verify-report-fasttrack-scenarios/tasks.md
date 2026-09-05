## Deliverables

```yaml
- path: core/verify_report.py
  kind: modify
- path: tests/test_verify_report_gate.py
  kind: modify
```

## 1. 测试先行（TDD 红）

- [ ] 1.1 `tests/test_verify_report_gate.py` 新增用例：fast-track 结果文件（无 report.json，`verification.scenarios` 非空）经 `synthesize_verification_report` 合成后，场景明细表逐行含 `scenario_id`/`description`/`status`（预期先失败）
- [ ] 1.2 新增用例：`report.json` 顶层 `scenarios` 与结果文件并存时场景表完全取自顶层（优先级回归）；两路皆缺时场景表留空但报告其余章节照常、合成不报错

## 2. 合成器数据源回退（TDD 绿）

- [ ] 2.1 `core/verify_report.py` 的 `synthesize_verification_report`：`report["scenarios"]` 缺失/为空/非法时归一 `run_result["verification"]["scenarios"]` 为场景列表传入 `_render_scenarios_table`；渲染函数保持纯函数无 IO、签名不变
- [ ] 2.2 跑通 1.1/1.2 新用例及该文件既有全部用例（full 模式优先级与 fail-closed 语义零回归）

## 3. 真实数据离线验证

- [ ] 3.1 用存量 fast-track SPEC 真实专属副本（如 `.fenix/verify-progress/fix-admin-disposition-empty-shell/.fenix-run-result.json`，共 8 个）离线调 `synthesize_verification_report`，确认场景表行数与 Dashboard「场景结果」页签同源同量、`exempt` 等非标准状态值原样渲染不报错
