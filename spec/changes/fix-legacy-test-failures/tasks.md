# Tasks: fix-legacy-test-failures

归因三类：`[违例]` 修实现 / `[断言]` 修断言并注明复核证据 / `[隔离]` 修测试隔离与确定性 / `[WIP]` 并发工作树诱发，干净分支不复现即关闭。

## 1. 干净分支复现复核

- [ ] 1.1 从 HEAD 切出干净实现分支，逐个复现 tasks 中 11 个失败测试（单测节点级运行），产出归因表（复现=是/否 + 簇 A–G 归类），写入任务说明；不复现者按 `[WIP]` 或 `[隔离]` 归因记录
- [ ] 1.2 对照归因表确认簇 A+B 的共同根因假设（salvage 提交路径 + 分支号推进语义），定位到具体 core/ 函数与行号

## 2. 簇 A+B：code_fix salvage 链修复（6 失败）

- [ ] 2.1 修复 salvage 提交路径根因（`False is not true : salvage 提交 MUST 成功（工作区脏）`×3），涉及 core/code_fix.py 及 salvage 链实现（见 design.md 定位清单）
- [ ] 2.2 修复分支号 off-by-one 根因（1794298733 != 1794298734），核对分支复用与新建的推进语义
- [ ] 2.3 修复搁浅批合回缺失（merge_calls 0 != 1）与 diff 保真（merge_diff_names 0 != 1）根因
- [ ] 2.4 回归确认：tests/test_code_fix_api_timeout_salvage.py、tests/test_code_fix_salvage.py 及 tests/test_code_fix.py 全绿

## 3. 簇 C：declaration 解析修复

- [ ] 3.1 修复 resolve_effective_declaration 的分支版本优先失效（'main' != 'branch'），实现位于 core/agent_runner/prompt_builder.py；`[违例]` 或 `[断言]` 按复核结论归类
- [ ] 3.2 回归确认：tests/test_declaration_resolution.py 全绿

## 4. 簇 D：fake-double 测试债清零（13 处违规）

- [ ] 4.1 逐条处置 13 处违规（首个 tests/test_admin.py:2977 _ClosedExecutor），按 tests/test_fake_double_fidelity.py 自身纪律修复违规测试本体；禁止放宽守卫
- [ ] 4.2 回归确认：tests/test_fake_double_fidelity.py 全绿

## 5. 簇 E：impl code review gate home 语义

- [ ] 5.1 复现 test_home_not_rewritten_when_empty（home `None == '/tmp'`）；干净分支不复现则记 `[WIP]` 关闭；复现则修空 home 回写语义实现
- [ ] 5.2 回归确认：tests/test_impl_code_review_gate.py 全绿

## 6. 簇 F：logger 旁路违例修复

- [ ] 6.1 core/dsh_session_tidy.py:72 裸 getLogger 改用项目纪律的可传播层级日志获取；守卫测试本体不动 `[违例]`
- [ ] 6.2 回归确认：tests/test_logger_no_bypass.py 全绿

## 7. 簇 G：push ref hygiene 修复

- [ ] 7.1 修复 main diverged 场景判定反转（`True is not false`），`[违例]` 或 `[断言]` 按复核结论归类
- [ ] 7.2 回归确认：tests/test_pm_dispatch.py 全绿

## 8. 验收自检

- [ ] 8.1 全量 `python3 -m pytest tests/ -q` 两次（间隔执行）均 0 failed
- [ ] 8.2 Deliverables 机械对账通过（lint_declared / lint_tasks_parseable）；每个修复任务的归因类别与证据已在任务说明记录
- [ ] 8.3 确认零新增第三方依赖、未改 spec/ 既有能力 REQUIREMENT、未触碰 SPEC-1/SPEC-2 范围文件

## Deliverables

```yaml
- path: core/dsh_session_tidy.py
  kind: modify
- path: core/code_fix.py
  kind: modify
- path: core/agent_runner/runner.py
  kind: modify
- path: core/agent_runner/prompt_builder.py
  kind: modify
- path: core/agent_runner/maintenance_runs.py
  kind: modify
- path: core/agent_runner/result_gate.py
  kind: modify
- path: core/fast_track_result.py
  kind: modify
- path: core/pm_engine/verification/branch_guard.py
  kind: modify
- path: tests/test_fake_double_fidelity.py
  kind: modify
- path: tests/test_admin.py
  kind: modify
- path: tests/test_impl_code_review_gate.py
  kind: modify
```
