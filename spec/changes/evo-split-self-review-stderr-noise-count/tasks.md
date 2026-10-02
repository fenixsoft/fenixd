## Deliverables

```yaml
- path: core/self_review.py
  kind: modify
- path: tests/test_self_review_midflight.py
  kind: modify
- path: core/agent_runner/provider_circuit.py
  kind: reference
```

## 1. 落地校验

- [x] 1.1 core/self_review.py：`_scan_run_midflight`（约 :864-941）stderr 分支做计数分离——新增 `stderr_noise_count` 状态，逐行经 `is_cli_stderr_noise`（复用本函数既有 :882 延迟导入的单源判别，不复制 pattern）命中则 `stderr_noise_count += 1`，否则 `stderr_count += 1`；first_stderr 选取逻辑（跳过噪声行、全噪声置空）保持零改动，但其内联注释（约 :915-919）中「stderr_count 仍保留全量计数」的旧口径表述须同步改写为新口径（逻辑零改动 ≠ 注释零改动），函数 docstring（约 :871）中「D2，计数保留全量」的旧口径表述一并改写；返回 dict 增 `stderr_noise_count` 键（`_collect_midflight_scans` 经 `**scan` 整体透传，编排层无需另改），函数 docstring 与 `_collect_midflight_scans` docstring（约 :957-958）的 Returns 键清单同步补记
- [x] 1.2 core/self_review.py：`_collect_midflight_section` 深扫行渲染（约 :1470-1477）改口径——「中途stderr=」取 `stderr_count`（非噪声计数），当 `s.get("stderr_noise_count")` 为正整数时在同行追加「（另 {N} 条已知 CLI 启动噪声）」；`stderr_noise_count` 为 0 或缺省（旧 scan dict 兼容）时不产生注记、行形态与现状一致

## 2. 测试

- [x] 2.1 tests/test_self_review_midflight.py：按本文件既有 env 装置与用例形态（参照 :270 `test_first_stderr_skips_cli_noise_line`、:288 `test_all_noise_stderr_left_blank`）更新计数口径断言——混合行用例断言 `stderr_count == 1`（仅真实行）且 `stderr_noise_count == 1`；全噪声用例断言 `stderr_count == 0`、`stderr_noise_count == 行数`、`first_stderr` 置空；同步修正既有「计数保留全量」断言为新口径（需改值的是 :285/:299；:265 所在用例的 `_stall_transcript` 夹具两条 stderr 均为真实行、新口径下计数仍应为 2，补 `stderr_noise_count == 0` 断言即可、勿改值），既有 first_stderr 断言（:266/:286/:300）不动；用例 docstring/注释中「计数保留全量」「计数仍计」旧口径表述（约 :274/:289）一并同步
- [x] 2.2 tests/test_self_review_midflight.py：新增渲染注记用例——构造含 1 条 `[claude-code:unrecognized_model]` 噪声行的离群 run 档案，断言深扫行含「中途stderr=0」与「（另 1 条已知 CLI 启动噪声）」注记；再构造无噪声行（真实诊断行 1 条）的对照档案，断言行形如「中途stderr=1」且不含注记