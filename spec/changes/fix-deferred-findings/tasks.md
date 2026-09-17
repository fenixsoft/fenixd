# Tasks: fix-deferred-findings

## Deliverables

```yaml
- path: core/dashboard/data/timeline.py
  kind: modify
- path: core/pm_engine/verification/serving.py
  kind: modify
- path: core/pm_engine/verification/infra_classify.py
  kind: modify
- path: core/pm_engine/verification/escalation.py
  kind: modify
- path: core/pm_engine/verification/verdict_evidence.py
  kind: modify
- path: core/pm_engine/verification/legacy.py
  kind: modify
- path: core/pm_engine/verification/report_gate.py
  kind: modify
- path: tests/test_characterization_dashboard_data.py
  kind: modify
- path: tests/test_deferred_findings_fixes.py
  kind: new
- path: spec/changes/fix-deferred-findings/findings-ledger.md
  kind: new
```

> 本 spec **MUST NOT** 修改在飞重构 spec 作业面文件（`core/worktree_manager.py`、`core/pm_engine/dispatch.py`、`core/dashboard/server.py`、`core/pm_engine/engine.py`、`core/pm_engine/verification/pipeline.py`、`core/agent_runner/runner.py`）。
> CYC-1 的 `engine.py` 子项、B4（`_last_freeze_rejected*` 声明）、B6（陈旧 docstring）已登记为**转移清单**（design D3），不在本变更交付集内。
> CYC-1 的非重叠子项若需新建中性模块，实现时在其 `.fenix-run-result.json` findings 登记实际落点路径。

## 1. 阶段 1：P0 真 bug 修复（timeline 排序键）

- [ ] 1.1 复现 `_timeline_sort_key` 无效时间戳分支的 `TypeError`（`_tz` 为 `timezone` 类非实例），记录当前 characterization 测试 `test_timeline_sort_key_invalid_time_sorts_later` 的「锁死抛错」断言
- [ ] 1.2 修复：`_tz` → `timezone.utc`；并按 design D2 在 `_parse_iso_ts` 内给 naive 结果补 `tzinfo=utc`
- [ ] 1.3 改写 `tests/test_characterization_dashboard_data.py::test_timeline_sort_key_invalid_time_sorts_later`：由「断言抛 TypeError」改为「断言排序结果」（无效事件排在合法事件之后）
- [ ] 1.4 补 naive 输入（无时区后缀）的解释测试（按 UTC）

## 2. 阶段 2：P1 性能修复（端口探测）

- [ ] 2.1 确认 `_port_responds` 串行探测的两处调用点（`_serve_command_in_worktree` / `_serve_command_in_main`）与探测器实现
- [ ] 2.2 改造为并发探测（如 `ThreadPoolExecutor`）+ 超时收敛，**保持 `pre` 端口集合语义逐元素一致**
- [ ] 2.3 补 mock urlopen 的并发一致性测试（改造前后 `pre` 集相等）

## 3. 阶段 3：整洁与健壮性条目

- [ ] 3.1 删除 `verification/serving.py` 与 `verification/infra_classify.py` 内 3 处冗余 late-import `import re as _re`（两文件顶部已有 `import re`）
- [ ] 3.2 `verification/escalation.py::_escalate_env_blocked` 的两处 `error_msg[:300]` 截断加省略号标注（`...`）
- [ ] 3.3 `verification/verdict_evidence.py::_record_verdict_adoption` 的 `_judge_token_baseline` 解析失败分支加 `logger.warning`（保留 fallback 行为）
- [ ] 3.4 抽共享小助手消除 `verification/legacy.py` 与 `verification/report_gate.py` 的 fallback 路径重复（helper 落 `report_gate.py`，不触 pipeline.py）
- [ ] 3.5 `verification/serving.py::_ensure_serving_worktree` 中 `old_server.stop()` 的 `except` 补 `logger.warning`（对齐 `_evict_spec_serving` 样板，**不调换 unregister 顺序**）
- [ ] 3.6 补 `tests/test_deferred_findings_fixes.py`：>300 字符截断标注、坏 baseline → 告警用例

## 4. 阶段 4：CYC-1 非重叠子项（分层倒置）

- [ ] 4.1 `find_impl_run_file` / `parse_run_task_done` 的消费点改从真源 `core/run_task_track` 导入（非 engine.py 侧，零搬移）
- [ ] 4.2 把 `get_runs` / `record_project_event` / `request_admin_invoke` / `parse_verify_progress` 搬入中性模块，`core/dashboard/data` 门面 re-export 保住既有导入路径
- [ ] 4.3 更新 `verification/escalation.py`、`verification/report_gate.py` 的 late import 指向中性模块
- [ ] 4.4 补「pm_engine 侧不 import `core.dashboard.data`」守卫断言（纳入现有 contract 测试或新测试）

## 5. 阶段 5：回归与收尾

- [ ] 5.1 运行 `bin/run_full_suite.py` 与基线比对，确认不新增失败
- [ ] 5.2 逐条核对「记录不修」项未被误改（`_should_overlay`、`shell=True`、config 缓存键、位移降档）
- [ ] 5.3 落盘 `findings-ledger.md`：14 条逐条最终态（已修 / 记录不修 / 转移）+ 转移去向
- [ ] 5.4 逐项勾选本 tasks.md 全部已完成任务
