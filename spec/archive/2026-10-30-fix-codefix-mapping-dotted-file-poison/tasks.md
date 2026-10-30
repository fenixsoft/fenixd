## Deliverables

```yaml
- path: core/code_fix.py
  kind: modify
- path: tests/test_codefix_targeted_retry.py
  kind: modify
```

## 1. 映射输入归一（喂侧剥离）

- [x] 1.1 `core/code_fix.py` 新增模块级助手 `_snapshot_failures_for_mapping(failures) -> list`：逐条浅拷贝并剥离 `file` 键（快照 file 为 `parse_junit_xml` 的点分 classname 兜底，带入会被 `_map_junit_failures_to_nodeids` 的 file 一致性校验判不一致、映射恒失败——对齐 `map_snapshot_issues_to_nodeids` 已验证的规避方式）；非 dict 条目原样透传（交由映射函数既有 fail-closed 判）；返回新列表，MUST NOT 原地修改传入列表及其条目（快照同源供展示/落盘）。
- [x] 1.2 `_ingest_failure_round` 与定向轮 round_items 提取点（`_run_code_fix_batch` 内 `_map_junit_failures_to_nodeids` 的两处调用）改为经 1.1 归一入口喂映射，`exec_root` 传参与其余口径逐字不变；两个调用点 MUST 同经入口，不得一处剥离一处不剥。

## 2. 回归钉子（tests/test_codefix_targeted_retry.py）

- [x] 2.1 补用例：点分 file 兜底形态（`file="tests.test_x"` + `classname="tests.test_x.TestFoo"`，exec_root 下 `tests/test_x.py` 在盘）经 `_ingest_failure_round` 映射成功——`mapped=True`、落盘明细 `fallback_full=False` 且 items 非空、nodeid 为 `tests/test_x.py::TestFoo::test_bar`。
- [x] 2.2 补用例：归一入口不改原快照——传入列表及条目 `file` 键处理后原样保留（新列表浅拷贝断言）。
- [x] 2.3 补用例：定向轮 round_items 提取点同形态映射成功（与 2.1 同口径的第二调用点钉子）。
- [x] 2.4 补用例：真实测试失败（`status="failed"` + 上述可映射明细）经 `_is_regression_anomaly` 判 False——不进熔断计数；对照非 dict 条目 / 缺 classname 形态仍判 True（fail-closed 口径不变）。
