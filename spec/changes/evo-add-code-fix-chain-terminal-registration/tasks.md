## Deliverables

```yaml
- path: core/code_fix.py
  kind: modify
- path: tests/test_code_fix_disabled_terminal_registration.py
  kind: new
```

## 1. 实现

- [x] 1.1 core/code_fix.py：在 checkpoint() 的**非在飞** disabled 终态写点（当前 5072-5085，`write_progress(running=False, phase="blocked", reason="disabled", ... **self._chain_terminal_fields("disabled"))`）落盘成功后追加 admin 告警与 todo 登记；MUST NOT 放在批在飞提示写点（5045-5071，`running` 仍为 true）。告警经 `_emit_signal` 新增 `signal_type=code_fix_disabled_terminal`、`severity="warning"`，以 fail-safe 包装（对齐 `_write_zero_progress_alert_safe`）；todo 用专用写点 `_append_disabled_terminal_todo_entry`（持 `.fenix/.todo.md.lock`，标题与 `_TODO_ENTRY_TITLE` 不同，不复用 `_append_todo_entry`）。文案含终态原因、剩余未修复条数、dashboard 重新触发入口提示（`POST /api/code-review/fix-run`）。
- [x] 1.2 core/code_fix.py：剩余未修复条数取 `count_open_items(project_root)` 实时台账 open 数，读失败回退进度 `total-done`（disabled 分支早退于 5102 的 `total_open` 计算，进度 total/done 为上一次 dispatch 的陈旧快照）。
- [x] 1.3 core/code_fix.py：同一 disabled 期去重——仅当进度已是 disabled 终态（`running is False ∧ phase=="blocked" ∧ reason=="disabled"`）才跳过；MUST NOT 以 `reason=="disabled"` 单独判重（在飞提示写点同 reason 但 running=true），MUST NOT 用同类型未处置信号判重（旧信号未处置会吞掉二次登记）。override_enabled 重新触发写回 `running=true` 后去重窗口自然重置，链再次 disabled 时落新登记。
- [x] 1.4 core/code_fix.py：fail-open——告警/todo 任一通道异常只 warning 留痕，MUST NOT 上穿 checkpoint()、MUST NOT 改变已落盘终态进度与 `{"triggered": False, "reason": "disabled"}` 返回值。

## 2. 测试

- [x] 2.1 tests/test_code_fix_disabled_terminal_registration.py：覆盖五形态——首收口落双登记（含剩余量/终态原因/触发提示/severity）、disabled 后重复 checkpoint 零新增、批在飞提示路径不登记、重新触发后再次 disabled 落新登记、登记通道异常时终态仍落盘且返回值不变。
