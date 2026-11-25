# Tasks: fix-legacy-test-failures

归因三类：`[违例]` 修实现 / `[断言]` 修断言并注明复核证据 / `[隔离]` 修测试隔离与确定性 / `[WIP]` 并发工作树诱发，干净分支不复现即关闭。

## 1. 干净分支复现复核

- [x] 1.1 从 HEAD 切出干净实现分支，逐个复现 tasks 中 11 个失败测试（单测节点级运行），产出归因表（复现=是/否 + 簇 A–G 归类），写入任务说明；不复现者按 `[WIP]` 或 `[隔离]` 归因记录 —— **归因表**：本分支（fenix/fix-legacy-test-failures-1794300907，HEAD c5b72688e）单测节点级批量复测 7 文件=2 failed/137 passed；全量 run1（744.7s，--json）失败集=仅 D/F 两项。复现=是：簇 D（test_fake_double_fidelity，13 处违规）、簇 F（test_logger_no_bypass，dsh_session_tidy 裸 getLogger）；复现=否 → `[WIP]`（原基线工作树含并发 dashboard WIP，design Context 实证）：簇 A×4（test_code_fix_api_timeout_salvage）、簇 B×2（test_code_fix_salvage）、簇 C（test_declaration_resolution）、簇 E（test_impl_code_review_gate）、簇 G（test_pm_dispatch），共 9 项，按 design 决策 1 关闭不改代码
- [x] 1.2 对照归因表确认簇 A+B 的共同根因假设（salvage 提交路径 + 分支号推进语义），定位到具体 core/ 函数与行号 —— 簇 A+B 六项失败在本分支单测节点与全量（run1）均不复现 → 共同根因假设不适用（无失败即无根因可定位），按 `[WIP]` 关闭，不修改 core/code_fix.py salvage 链

## 2. 簇 A+B：code_fix salvage 链修复（6 失败）

- [x] 2.1 修复 salvage 提交路径根因（`False is not true : salvage 提交 MUST 成功（工作区脏）`×3），涉及 core/code_fix.py 及 salvage 链实现（见 design.md 定位清单） —— `[WIP]` 复现门关闭：失败在本干净分支单测节点级不复现（tests/test_code_fix_api_timeout_salvage.py 全绿），原基线失败系并发工作树 WIP 诱发；按 design 决策 1 不修改任何代码
- [x] 2.2 修复分支号 off-by-one 根因（1794298733 != 1794298734），核对分支复用与新建的推进语义 —— `[WIP]` 复现门关闭：同 2.1，不复现不改代码
- [x] 2.3 修复搁浅批合回缺失（merge_calls 0 != 1）与 diff 保真（merge_diff_names 0 != 1）根因 —— `[WIP]` 复现门关闭：tests/test_code_fix_salvage.py 单测节点全绿，不复现不改代码
- [x] 2.4 回归确认：tests/test_code_fix_api_timeout_salvage.py、tests/test_code_fix_salvage.py 及 tests/test_code_fix.py 全绿 —— 三文件实测全绿（修复批回归 583 passed 含 test_code_fix.py 全量通过）

## 3. 簇 C：declaration 解析修复

- [x] 3.1 修复 resolve_effective_declaration 的分支版本优先失效（'main' != 'branch'），实现位于 core/agent_runner/prompt_builder.py；`[违例]` 或 `[断言]` 按复核结论归类 —— `[WIP]` 复现门关闭：tests/test_declaration_resolution.py 单测节点与全量均绿，失败不复现，不改代码
- [x] 3.2 回归确认：tests/test_declaration_resolution.py 全绿 —— 实测全绿（7 文件批量复测 137 passed 之一）

## 4. 簇 D：fake-double 测试债清零（13 处违规）

- [x] 4.1 逐条处置 13 处违规（首个 tests/test_admin.py:2977 _ClosedExecutor），按 tests/test_fake_double_fidelity.py 自身纪律修复违规测试本体；禁止放宽守卫 —— 守卫扫描直取 13 处违规清单；逐条把替身签名显式化对齐生产（submit 类统一 `(self, fn, ctx=None)` 形态、jobs 存 `(fn, (ctx,) if ctx is not None else ())` 保真回放；_write_provider_marker `*attempt`→`attempt=None` 对齐 provider_circuit.py:864 生产可选参），同步改造 3 处 jobs 三元解包消费点（test_code_fix.py run_one、test_codefix_digest_metrics.py:537/599）；守卫与白名单零改动
- [x] 4.2 回归确认：tests/test_fake_double_fidelity.py 全绿 —— 实测全绿（13 违规清零，守卫有牙自检通过）

## 5. 簇 E：impl code review gate home 语义

- [x] 5.1 复现 test_home_not_rewritten_when_empty（home `None == '/tmp'`）；干净分支不复现则记 `[WIP]` 关闭；复现则修空 home 回写语义实现 —— `[WIP]` 关闭：tests/test_impl_code_review_gate.py 单测节点与全量均绿（design Open Questions 预判成立——原基线并发 dashboard WIP 诱发），不改代码
- [x] 5.2 回归确认：tests/test_impl_code_review_gate.py 全绿 —— 实测全绿

## 6. 簇 F：logger 旁路违例修复

- [x] 6.1 core/dsh_session_tidy.py:72 裸 getLogger 改用项目纪律的可传播层级日志获取；守卫测试本体不动 `[违例]` —— 证据：原值 `logging.getLogger("fenix.dsh_session_tidy")` 层级名缺 `d`（`fenix.` ≠ 纪律前缀 `fenixd.`，守卫 `_is_allowed_arg` 仅放行 fenixd 前缀字面量），已改 `fenixd.dsh_session_tidy`；core/logger.py:288 证实全局 "fenixd" 根日志器为 fenixd.* 传播挂载点；`[违例]` 修实现、守卫零改动
- [x] 6.2 回归确认：tests/test_logger_no_bypass.py 全绿 —— 实测全绿

## 7. 簇 G：push ref hygiene 修复

- [x] 7.1 修复 main diverged 场景判定反转（`True is not false`），`[违例]` 或 `[断言]` 按复核结论归类 —— `[WIP]` 复现门关闭：tests/test_pm_dispatch.py 单测节点与全量均绿，失败不复现，不改代码
- [x] 7.2 回归确认：tests/test_pm_dispatch.py 全绿 —— 实测全绿

## 8. 验收自检

- [x] 8.1 全量 `python3 -m pytest tests/ -q` 两次（间隔执行）均 0 failed；若出现 tasks 所列 11 项之外的新失败，按同款归因纪律处置（干净分支复现 → 修并补归因记录；不复现 → 记 `[WIP]`/`[隔离]` 关闭），不得删除或放宽测试 —— 证据：经有界入口 bin/run_full_suite.py 三次全量——run1（修复前基线复核，744.7s）失败集=仅 D/F 两项（11 项中其余 9 项不复现）；run2（修复后 730.0s）与 run3（修复后 733.0s，间隔执行）均 rc=0 / 0 failed / 无挂起，摘要 JSON 归档 .fenix/verify-evidence/fix-legacy-test-failures/
- [x] 8.2 Deliverables 机械对账通过（lint_declared / lint_tasks_parseable）；每个修复任务的归因类别与证据已在任务说明记录 —— lint_declared 与 lint_tasks_parseable 实测双 PASS；归因注记已逐任务落 tasks.md（D=`[违例类替身债]` 13 处签名显式化、F=`[违例]` 层级名修正、其余 9 项=`[WIP]` 复现门关闭）
- [x] 8.3 确认零新增第三方依赖、未改 spec/ 既有能力 REQUIREMENT、未触碰 SPEC-1/SPEC-2 范围文件 —— diff 复核：实现改动仅 core/dsh_session_tidy.py 层级名一行 + 9 个测试替身签名 + .gitignore；零新增 import（标准库已有）；spec/ 既有能力 REQUIREMENT 零改动（仅本 SPEC tasks.md 勾选）；core/platform/（SPEC-1/SPEC-2 范围）零触碰

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
- path: tests/test_api_stall_disposition.py
  kind: modify
- path: tests/test_code_fix.py
  kind: modify
- path: tests/test_code_fix_manual_trigger.py
  kind: modify
- path: tests/test_code_review.py
  kind: modify
- path: tests/test_codefix_digest_metrics.py
  kind: modify
- path: tests/test_maintenance_lane_failover.py
  kind: modify
- path: tests/test_push_retry_recovery.py
  kind: modify
- path: tests/test_regression_autofix.py
  kind: modify
- path: tests/test_impl_code_review_gate.py
  kind: modify
```
