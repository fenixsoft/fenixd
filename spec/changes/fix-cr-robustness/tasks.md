# Tasks: fix-cr-robustness

## Deliverables

```yaml
- path: core/agent_runner/liveness.py
  kind: modify
- path: tests/test_liveness_hang_discrimination.py
  kind: modify
```

## 1. 修复审查问题

- [ ] 1.1 `core/agent_runner/liveness.py` `_supervision_deadline_action`（现 :996）：把 `run_timeout = float(self._pm._effective_run_timeout(agent_type))` 改为按 design D1 的四段解析——门面调用包在 `try/except (TypeError, ValueError, AttributeError)` 内；返回值须为 `int`/`float` 且非 `bool` 且 `> 0` 才取 `float(...)`，否则（含 `None`、非数值、异常）回退 `float(RUN_TIMEOUT_FALLBACK_SECONDS)`（自 `core.config` import，**MUST NOT** 手写 9000/3600 字面量，遵守 `tests/test_supervision_timeout_consistency.py:215` 的「无手写常数残留」约束）。兜底分支 MUST 打 WARNING（component `agent_runner`，含 `agent_type` 与原始值 `repr`）。正常路径数值必须与改造前逐位一致
- [ ] 1.2 `tests/test_liveness_hang_discrimination.py` 新增两个用例：(a) 替身门面 `_effective_run_timeout` 返回 `None` 时调 `_supervision_deadline_action`（`started_at` 取足够早、`extensions_used=0`）MUST 不抛异常，且返回 `{"action": "kill"}` 的 `reason` 内含 `absolute_max_seconds cap reached (12600s`（= 兜底 9000 + 2×1800，见 `core/config.py:1386-1388` 派生式）；(b) 替身门面抛异常时同样不抛异常并得到同一 cap。既有用例 MUST 全绿（正常路径零变化）
- [ ] 1.3 治理影响确认（无需改代码）：确认兜底不再让异常逃逸至 `core/agent_runner/runner.py:3624` 的轮询环 `except Exception`（该分支会把一次 deadline 判定升级为 `run thread crashed` 终态并 re-raise）
