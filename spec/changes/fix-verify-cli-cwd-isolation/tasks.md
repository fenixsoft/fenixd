# Tasks: fix-verify-cli-cwd-isolation

## Deliverables

```yaml
- path: core/verify_engine/engine.py
  kind: modify
- path: core/verify_engine/cli_runner.py
  kind: modify
- path: core/verify_engine/runner.py
  kind: modify
- path: core/pm_engine/verification.py
  kind: modify
- path: tests/test_verify_cli_runner.py
  kind: modify
```

## 1. 场景执行根接线

- [ ] 1.1 `core/verify_engine/engine.py`：`VerifyEngine.__init__` 增可选参 `scenario_root: Path | None = None`（None 回退 `project_root`）；`_runner_for` 构造 Runner 时透传；`VerifyRunner` 基类（core/verify_engine/runner.py）加同名字段
- [ ] 1.2 `core/verify_engine/cli_runner.py`：`_resolve_cwd` 无显式 cwd 时返回 scenario_root（回退链 scenario_root → project_root），docstring 与实现对齐
- [ ] 1.3 `core/pm_engine/verification.py`：command-worktree 轮实例化 `VerifyEngine` 时传入本轮 serving worktree 根（新建与 HEAD 未变复用两条路径都要带出）；无 serving worktree 轮不传（回退主树）
- [ ] 1.4 `tests/test_verify_cli_runner.py` 新增用例：①双根隔离——seed 式相对写（`.fenix/STATE.md`、`spec/changes/x/tasks.md`）落 scenario_root，主树零污染；②无 scenario_root 回退 project_root 行为不变；③引擎簿记路径仍指向主树 verify-progress
- [ ] 1.5 全库 grep 既有 `test_scenarios.json` 无 cwd 的 cli 步骤做影响清点，逐条确认在 worktree 轮下语义不变或有显式 cwd 化改造，结论登记实现报告
