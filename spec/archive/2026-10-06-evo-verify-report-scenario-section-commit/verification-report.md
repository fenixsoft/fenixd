# 验证报告：evo-verify-report-scenario-section-commit

> ⚠️ 本报告由框架于 2026-09-28T18:52:54Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-09-28T18:52:54.605437+00:00

## 结论：✅ 通过（verified）

**状态：verified — 9/9 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 9/9 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 9 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 1.91M |
| 本链增量 Token（输出） | 0.04M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| section-commit-e2e-head-and-pathspec | 场景段写盘即入库E2E探针：临时git仓种入已入库无小节报告+真实diff归属戳，调真实 _render_scenario_change_section_to_report 后 HEAD 含「本轮场景集变更」小节与超发拦截变更行、该pathspec对HEAD干净、HEAD提交仅触及报告文件、提交数+1、零WARNING（specs/verification-report/spec.md 场景「场景段随写盘入库」；实现 core/pm_engine/verification/scenario_gate.py:558-565、提交器 core/verify_report.py:805） | pass | 0/8 | - |
| section-commit-pathspec-isolation | 场景段提交pathspec隔离E2E探针：其它spec在途草案（staged）与已跟踪README未暂存修改在场时，渲染触发的提交仅含报告文件，外来staged条目（A  状态）与未暂存修改（ M 状态）原样保留、报告不出现在status（spec.md 场景「场景段随写盘入库」AND 子句「其他 spec 的在途草案与 staged 内容不受牵连」；tests/test_verification_report_commit.py:334 同构断言） | pass | 0/7 | - |
| section-commit-render-idempotent | 重复触发幂等E2E探针：同一报告二次触发渲染，提交数不变、logger零新增记录且全程零WARNING、HEAD仍含小节（spec.md 场景「重复触发幂等」；scenario_gate.py:541 幂等判重提前返回 + core/verify_report.py:856-864 探测式静默跳过双保险） | pass | 0/7 | - |
| section-commit-git-add-failure-degrades | git失败降级E2E探针：预置 .git/index.lock 令 git add 失败，渲染函数不抛穿、报告文件仍写盘含小节、仅落一条「验证报告入库失败…git add 失败」WARNING、HEAD仍无小节（spec.md Requirement「提交失败降级」场景「git 失败不扰主流程」；core/verify_report.py:823-827 失败仅WARNING文案） | pass | 0/6 | - |
| section-commit-committer-crash-degrades | 提交器意外异常外层兜底E2E探针：monkeypatch core.verify_report._commit_verification_report 抛 RuntimeError，渲染函数正常返回不抛穿、报告文件仍写盘含小节、WARNING 含「场景集变更小节入库失败」与异常原文、HEAD仍无小节（scenario_gate.py:559-565 外层防御分支——单测未覆盖的 pragma 分支，探针补真实覆盖） | pass | 0/5 | - |
| section-commit-non-git-silent-skip | 非git项目静默跳过E2E探针：无git仓库临时项目根先自证 rev-parse 探测失配，再调真实渲染函数，报告正常写盘含小节且logger零记录（spec.md「非 git 项目静默跳过」；core/verify_report.py:813-820 探测失败静默 return 不落WARNING） | pass | 0/5 | - |
| pytest-scenario-section-commit-class | 交付物测试组直跑：pytest -v 运行 tests/test_verification_report_commit.py::TestScenarioSectionCommit 三用例全绿——场景段提交入库（test_section_write_is_committed）、pathspec隔离（test_section_commit_is_pathspec_isolated）、幂等零WARNING（test_second_render_no_new_commit_no_warning），断言文案照抄实测输出行（tasks.md 2.1-2.3；pytest 9.1.1 实测 3 passed） | pass | 0/5 | - |
| pytest-commit-file-full-green | 提交器既有降级用例回归：pytest 运行 tests/test_verification_report_commit.py 全文件 11 用例全绿——含 git add 失败/commit 失败仅WARNING（test_git_add_lock_conflict_only_warning / test_git_commit_failure_only_warning）、闸门重复放行零WARNING（test_repeated_gate_no_new_commit_no_warning）、非git静默跳过（test_gate_skips_commit_silently_without_git_repo），确认存量桩测试不受本次改动扰动（tasks.md 2.4 邻接面；实测 11 passed） | pass | 0/2 | - |
| regression-six-files-green | 定向回归六文件全绿：tests/test_pm_verification.py、tests/test_pm_recovery.py、tests/test_verify_parallel_backoff.py、tests/test_verify_report_gate.py、tests/test_verify_scenarios.py、tests/test_facade_delegation_contract.py——tasks.md 2.4 回归自检清单原样执行，存量 MagicMock 桩与门面委托映射桩零扰动（实测摘要行 178 passed, 1 xfailed, 546 subtests passed） | pass | 0/2 | - |

## 本轮场景集变更

当前稳定场景集共 9 个（第 1 轮）。

- 首轮写入 9 个场景

