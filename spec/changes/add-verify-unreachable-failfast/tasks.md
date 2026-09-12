# Tasks: add-verify-unreachable-failfast

## Deliverables

```yaml
- path: core/pm_engine/verification.py
  kind: modify
- path: tests/test_pm_verification.py
  kind: modify
```

## 1. 核心短路点实现

- [ ] 1.1 在 `_run_three_stage_verification` 阶段2.5（`verification.py` 应用可达性日志行之后、自愈后场景重读之前）插入短路块：`app_reachable=False and not user_blocked` 时记 error 日志、调用 `self._escalate_env_blocked(spec_name, [reach_note], title="验证环境阻塞（应用不可达）")` 并 `return`（场景执行数=0，不重读场景、不运行 VerifyEngine、不退回 plan）
- [ ] 1.2 将 `_ensure_app_reachable` 返回值解包由 `app_reachable, _user_blocked, reach_note` 改为 `app_reachable, user_blocked, reach_note`（短路条件需读 user_blocked；`_ensure_app_reachable` 内部与其余调用点不动）

## 2. 回归测试

- [ ] 2.1 `tests/test_pm_verification.py` 新增回归：monkeypatch `_ensure_app_reachable` 返回 `(False, False, "就绪探针超时（120s）: …")` → 断言 `VerifyEngine.run` 未被调用、`_escalate_env_blocked` 被调、STATE 落 blocked，且 `verify_contract_missing` 信号未被本短路重复追加（契约缺失子案的信号仍由 `_ensure_app_reachable` 内部唯一写入）
- [ ] 2.2 新增回归：返回 `(True, False, "")` → 断言短路点不触发，`VerifyEngine.run` 照常被调，行为与现状一致
- [ ] 2.3 新增回归：返回 `(False, True, "需用户登录后重试")` → 断言不短路、不落 blocked（user_blocked 守卫放行）
- [ ] 2.4 全量运行 `tests/test_pm_verification.py` 既有用例，确认零回归

## 3. 收尾

- [ ] 3.1 自查满足 spec 全部 Scenario（探针超时/prepare 失败短路、契约缺失只补落态、可达放行、user_blocked 守卫），并核对 `## Deliverables` 声明与实现分支实际改动一致