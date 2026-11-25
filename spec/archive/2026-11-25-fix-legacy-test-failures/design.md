# Design: fix-legacy-test-failures

## Context

主线基线（2026-11-10 两次全量实测，命令 `python3 -m pytest tests/ -q`）：

- builder check：**12 failed / 10181 passed**（约 11m40s）
- 本 SPEC 成文时复测（707.54s，工作树含并发会话的 dashboard WIP）：**11 failed / 10186 passed / 1 skipped / 1 xfailed**

两次数字有漂移 ⇒ 至少一个失败是 flaky 或受工作树 WIP 影响。**权威清单以本 SPEC tasks.md 所列 11 项为准，但每项必须在干净实现分支上逐一复现后再动手**——不复现者按 WIP/环境归因记录，不盲改。

11 个失败按簇与错误本质（详见 tasks.md）：

| 簇 | 测试 | 错误本质 | 初步归因 |
|---|---|---|---|
| A | tests/test_code_fix_api_timeout_salvage.py ×4 | `False is not true : salvage 提交 MUST 成功（工作区脏）`×3；分支号 1794298733 != 1794298734 off-by-one ×1 | mock 型确定性失败，真实回归嫌疑 |
| B | tests/test_code_fix_salvage.py ×2 | merge_calls 0 != 1；merge_diff_names 0 != 1 | 同上，可能与 A 同根因 |
| C | tests/test_declaration_resolution.py ×1 | declaration source `'main' != 'branch'` | 真实回归嫌疑 |
| D | tests/test_fake_double_fidelity.py ×1 | 13 处测试债违规清单（首个 tests/test_admin.py:2977 _ClosedExecutor） | 测试债累积 |
| E | tests/test_impl_code_review_gate.py ×1 | home `None == '/tmp'`（空 home 未回写） | 可能受并发 dashboard WIP 影响 |
| F | tests/test_logger_no_bypass.py ×1 | core/dsh_session_tidy.py:72 裸 getLogger（守卫指认） | 已知真实违例 |
| G | tests/test_pm_dispatch.py ×1 | push ref hygiene `True is not false`（main diverged 场景） | 真实回归嫌疑 |

相关 core 实现定位（供任务执行起点）：salvage 链散布于 core/code_fix.py、core/agent_runner/runner.py、core/agent_runner/prompt_builder.py、core/agent_runner/maintenance_runs.py、core/agent_runner/result_gate.py、core/fast_track_result.py、core/pm_engine/verification/branch_guard.py；resolve_effective_declaration 在 core/agent_runner/prompt_builder.py。

## Goals / Non-Goals

- **Goals**：全量测试 0 failed（干净实现分支）；逐项归因可追溯；零新增第三方依赖；除真实违例修复外不改行为契约。
- **Non-Goals**：Windows PAL（SPEC-1/SPEC-2）任何工作；超出生存失败的测试框架重构；对 WIP 中并发 SPEC（dashboard 相关）代码的改动。

## Decisions

1. **干净分支复现门**：每个失败先在从 HEAD 切出的干净实现分支上复现。不复现 ⇒ 记「WIP/环境诱发」归因并关闭该项，不修改任何代码。基线复测的工作树含并发 dashboard WIP（簇 E 首要嫌疑）。
2. **簇 A+B 先找共同根因**：6 个 salvage 失败高度可能收敛到 1–2 个根因（salvage 提交路径 + 分支号推进语义），先修根因再看剩余失败，禁止逐测试打补丁。
3. **簇 D 按该测试自身纪律处置**：13 处违规逐条修复违规测试（或按 test_fake_double_fidelity 既定登记机制处理），禁止简单放宽守卫清零。
4. **簇 F 修实现不改守卫**：core/dsh_session_tidy.py:72 改用项目纪律的可传播层级日志获取方式；test_logger_no_bypass.py 守卫本体不动。
5. **断言修只在现行行为正确时使用**：注明「断言脱节」归因与复核证据（对应 spec.md 的不掩盖 Scenario）。

## Risks / Trade-offs

- **修断言掩盖缺陷** → 归因强制 + tasks 说明留证据；daemon verify 车道全量回归兜底。
- **fake-double 违规修复牵连多个测试文件** → 逐条处理、逐条跑对应测试文件确认。
- **并发 WIP 噪声污染归因** → 决策 1 的干净分支复现门。
- **flaky 失败偶发复现失败** → 验收任务跑两次全量（间隔执行）确认稳定。

## Migration Plan

无迁移——本 SPEC 是测试基线修复，不改持久化格式与对外接口。

## Open Questions

- 簇 E 若在干净分支不复现：直接归因 WIP 并关闭（记录），不等待并发 SPEC 完成。
