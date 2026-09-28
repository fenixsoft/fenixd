# design — verify-report-scenario-section-commit

## 根因：次序缝而非异相路径

采纳流程内的执行次序：judge 裁决 → pipeline.py:2807/2810 → _apply_verified(:1089) / _apply_bug_found(:915) → 报告闸门提交（:1120 / :948）→ 状态 transition → 场景段渲染写盘（:1194 / :1034 → scenario_gate.py:499，:548 _atomic_write_text）。提交发生在追加之前且之后无提交点。todo 所设「渲染挪到放行出口之后」（建议 B）按字面是无操作；其反向变体（挪到闸门前）更劣：synthesized 路径报告尚不存在（scenario_gate.py:535-536 早退丢小节）、resynthesized 路径小节会被随后的合成覆盖、且 :502 docstring 明示依赖「报告闸门已保证文件存在」前置。故取建议 A：写盘成功后立即提交。

## 实现

- 落点：core/pm_engine/verification/scenario_gate.py:548 原子写回成功分支后，函数内 import core.verify_report 并调用 _commit_verification_report(project_root, spec_name, logger)（core/verify_report.py:805，签名直接可用；函数体内 import 遵该文件 D4 惯例）。
- 幂等：提交器内置 diff --cached 对 HEAD 的探测（:856-864），重复触发零副作用；:541 幂等判重保证每报告至多一段，额外提交至多一次。
- 失败语义：提交失败仅 WARNING（:825-827 既有文案风格），不扰渲染写盘与验证主流程；非 git 项目静默跳过（:832-840）。

## 测试

- tests/test_verification_report_commit.py（已有临时 git 仓 _CommitTestBase 与真实夹具）：新增 TestScenarioSectionCommit——种子报告 + 桩 pipeline 上下文（_context.project_root/logger、_last_scenario_diff/_last_freeze_owner 归属戳）调真渲染函数，断言 HEAD 含小节、pathspec 干净；隔离用例照抄 TestPathspecPrecision(:203-223) 的 staged 草案 + 未暂存修改保全断言；幂等用例二次触发零提交零 WARNING。
- 存量桩测试（test_pm_verification.py、test_pm_recovery.py、test_verify_parallel_backoff.py 等 MagicMock 打桩处）零扰动，跑定向回归确认。

## Risks

- 每次采纳多一枚小提交：因 :541 幂等，实际每报告至多一次，可接受。
- 与既有放行出口重复提交：幂等探测天然去重。
- 存量 11 份不回填：沿 commit-on-write 非目标先例，归档整目录 add 兜底承接。