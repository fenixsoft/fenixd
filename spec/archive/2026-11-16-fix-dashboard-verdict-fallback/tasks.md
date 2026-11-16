# Tasks: fix-dashboard-verdict-fallback — Dashboard 验证裁决兜底读取 impl-result 快照

## Deliverables

```yaml
- path: core/dashboard/data/artifacts.py
  kind: modify
- path: tests/test_dashboard_data.py
  kind: modify
```

## 1. 兜底读取器三路候选

- [x] 1.1 `core/dashboard/data/artifacts.py` `_load_run_result`：候选链在私有 `.fenix/verify-progress/<spec>/.fenix-run-result.json` 之后、共享 `.fenix/.fenix-run-result.json` 之前插入 `.fenix/verify-progress/<spec>/impl-result.json`；该候选按 `data.get("spec") == spec_name` 严格归属校验（缺失/不匹配/JSONDecodeError/OSError/UnicodeDecodeError/非 dict 一律跳过继续下一路，fail-closed），docstring 同步补记三路候选与优先级理由（full 升级后新裁决压过 fast-track 旧快照）

## 2. 测试覆盖

- [x] 2.1 `tests/test_dashboard_data.py` 新增 fast-track 快照兜底用例组（夹具按 `impl-result.json` 真实形态构造：顶层 `spec` + `verification.verdict` + `verification.scenarios[].status`）：快照命中时 `parse_verdict` 返回 `exists=True` 与三桶 int 计数；私有 `.fenix-run-result.json` 与快照并存时取前者（候选序）；`spec` 字段缺失/不符、损坏 JSON、`verdict` 缺失或非法五类负例全部 `exists=False` 不抛异常；既有 `_verdict_from_run_result` 两路用例断言不动（str|int|None 三态契约防单侧归一）

## 3. 回归与收工自证

- [x] 3.1 全量跑 `python3 -m pytest tests/test_dashboard_data.py tests/test_verify_report_gate.py tests/test_facade_delegation_contract.py -q` 零失败；实测回放：对 `/root/fenixd` 项目以真实 `.fenix/verify-progress/add-spec-list-mobile-style/impl-result.json` 调 `parse_verdict` 断言 `exists=True` 且裁决为 verified（本仓自证）
