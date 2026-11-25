# 验证报告：fix-legacy-test-failures

> ⚠️ 本报告由框架于 2026-11-10T10:13:21Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-11-10T10:13:21.060059+00:00+run-result@mtime1794305601105857806

## 结论：✅ 通过（verified）

**状态：verified — 12/12 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 12/12 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 12 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 2.01M |
| 本链增量 Token（输出） | 0.04M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| legacy-inventory-intact | 反掩盖探针（specs/legacy-test-baseline-green/spec.md「修复不掩盖真实缺陷」Scenarios）：tasks.md 所列 11 项存量失败用例名（簇 A×4/B×2/C×1/D×1/E×1/F×1/G×1）仍在对应测试文件中（def <name> 在场——修复 MUST NOT 以删除测试使套件变绿），且两个守卫测试本体的扫描标记在场（test_fake_double_fidelity.py 的 violations 扫描与有牙自检 test_seam_set_is_large_enough、test_logger_no_bypass.py 的 getLogger 扫描与 test_no_bare_getlogger_in_core——修复 MUST NOT 放宽守卫清零）。出处：spec/changes/fix-legacy-test-failures/tasks.md §2–§7 与 design.md 决策 3/4/5；用例名逐个取自 tests/ 源码（test_code_fix_api_timeout_salvage.py:312/329/345/365、test_code_fix_salvage.py:155/230、test_declaration_resolution.py:136、test_fake_double_fidelity.py:270、test_impl_code_review_gate.py:138、test_logger_no_bypass.py:75、test_pm_dispatch.py:371）。 | pass | 0/3 | - |
| salvage-api-timeout-file-green | 簇 A 回归确认（tasks 2.1/2.2/2.4）：tests/test_code_fix_api_timeout_salvage.py 全绿。主树基线 4 项失败（salvage 提交 MUST 成功（工作区脏）×3 + 分支号 off-by-one ×1）——干净实现分支当前实测已绿（WIP 诱发嫌疑，按 design 决策 1 复现门归因），本场景锁定终态：全文件 exit 0 且 4 个存量失败用例 PASSED（只带 -v 不带 -q，pytest 9 中 -q 吞掉 PASSED 行；断言子串照抄 -v 真实输出形态「tests/...::<Class>::<test> PASSED」的用例名段）。出处：tests/test_code_fix_api_timeout_salvage.py:312-359（TestSalvageLegacyClaimPath）、:365（TestApiTimeoutSalvageChain 全链）；tasks.md §2.4。 | pass | 0/6 | - |
| salvage-stranded-merge-file-green | 簇 B 回归确认（tasks 2.3/2.4）：tests/test_code_fix_salvage.py 全绿。主树基线 2 项失败（merge_calls 0 != 1 搁浅批合回缺失；merge_diff_names 0 != 1 diff 保真）——干净实现分支当前实测已绿（WIP 诱发嫌疑），本场景锁定终态：全文件 exit 0 且两个存量失败用例 PASSED。出处：tests/test_code_fix_salvage.py:155（test_stranded_batch_salvaged_and_merged）、:230（test_salvage_diff_matches_working_tree_without_noise）；tasks.md §2.4。 | pass | 0/4 | - |
| declaration-resolution-green | 簇 C 回归确认（tasks 3.1/3.2）：tests/test_declaration_resolution.py 全绿。主树基线 1 项失败（declaration source 'main' != 'branch'——resolve_effective_declaration 分支版本优先失效，实现在 core/agent_runner/prompt_builder.py；[违例] 或 [断言] 按复核结论归类）——干净实现分支当前实测已绿（WIP 诱发嫌疑），本场景锁定终态：全文件 exit 0 且分支版本优先语义用例 PASSED。出处：tests/test_declaration_resolution.py:136（test_branch_version_preferred）、:178（test_worktree_version_preferred_over_branch）；tasks.md §3.2。 | pass | 0/4 | - |
| fake-double-fidelity-green | 簇 D 回归确认（tasks 4.1/4.2）：tests/test_fake_double_fidelity.py 全绿。基线 1 项失败：test_current_tests_have_zero_violations 报 13 处测试债违规清单（首个 tests/test_admin.py:2977 _ClosedExecutor）——13 处违规须按该守卫自身纪律逐条修复违规测试本体（Deliverables 所列其余 12 个 tests/ 文件即违规散布面），禁止放宽守卫清零。本场景锁定终态：守卫全文件 exit 0 且存量失败用例与有牙自检 PASSED（test_seam_set_is_large_enough 在场即守卫仍有牙、未退化）。出处：tests/test_fake_double_fidelity.py:270（test_current_tests_have_zero_violations）、:241（test_seam_set_is_large_enough）；design.md 决策 3；tasks.md §4.1/§4.2。 | pass | 0/4 | - |
| impl-review-gate-home-green | 簇 E 回归确认（tasks 5.1/5.2）：tests/test_impl_code_review_gate.py 全绿。主树基线 1 项失败：test_home_not_rewritten_when_empty（home None == '/tmp'，空 home 未回写）——干净实现分支当前实测已绿（93 passed / 8.5s，2026-11-10 本机实测；design.md Open Questions：干净分支不复现则记 [WIP] 关闭），本场景锁定终态：全文件 exit 0 且该用例 PASSED（wrapper_path 为 @pytest.fixture 非参数化，-v 输出形如「tests/...::test_home_not_rewritten_when_empty PASSED」，无 [参数] 后缀）。出处：tests/test_impl_code_review_gate.py:138、:95-96（fixture）；tasks.md §5.1/§5.2。 | pass | 0/3 | - |
| logger-no-bypass-green | 簇 F 回归确认（tasks 6.1/6.2）：tests/test_logger_no_bypass.py 全绿。基线 1 项失败：test_no_bare_getlogger_in_core——守卫指认 core/dsh_session_tidy.py:72 裸 getLogger（core/ 真实违例，非环境差异）；修复=该违例点改用项目纪律的可传播层级日志获取方式，守卫测试本体不动（design.md 决策 4 [违例]）。本场景锁定终态：守卫全文件 exit 0 且 test_no_bare_getlogger_in_core PASSED。出处：tests/test_logger_no_bypass.py:75；core/dsh_session_tidy.py:72；tasks.md §6.1/§6.2。 | pass | 0/3 | - |
| pm-dispatch-push-hygiene-green | 簇 G 回归确认（tasks 7.1/7.2）：tests/test_pm_dispatch.py 全绿。主树基线 1 项失败：test_main_diverged_failure（push ref hygiene True is not false，远端 main 分叉非 FF 场景判定反转；[违例] 或 [断言] 按复核结论归类）——干净实现分支当前实测已绿（93 passed / 8.5s 批跑含本文件），本场景锁定终态：全文件 exit 0 且分叉失败语义与首推成功语义两用例 PASSED。出处：tests/test_pm_dispatch.py:371（test_main_diverged_failure）、:360（test_main_first_push_success）；tasks.md §7.1/§7.2。 | pass | 0/4 | - |
| code-fix-regression-green | 簇 A/B 修复面回归确认（tasks 2.4）：tests/test_code_fix.py（91 用例）全绿——salvage 链修复（core/code_fix.py 等）不得破坏 code-fix 主套件的既有行为契约（proposal.md：除真实违例修复外不改变既有行为）。断言 exit 0 + 汇总行 passed（不并列 -v/-q；91 用例带真实 git 操作，timeout 放宽至 600s）。出处：tasks.md §2.4；tests/test_code_fix.py。 | pass | 0/2 | - |
| deliverable-boundary-intact | 交付边界探针（tasks 8.3）：git diff main...HEAD 的全部改动路径 MUST 落在 core/ tests/ 允许域——即零新增第三方依赖（requirements/pyproject 等依赖清单零触碰）、未改 spec/ 既有能力 REQUIREMENT、未触碰 SPEC-1/SPEC-2 范围文件。越界路径（docs/、spec/、依赖清单等）逐条打印并 exit 1。出处：tasks.md §8.3；proposal.md Impact；spec/changes/fix-legacy-test-failures/tasks.md Deliverables（8 个 core/ + 11 个 tests/ 文件）。 | pass | 0/2 | - |
| full-suite-green-run-1 | 验收主门·第 1 次（tasks 8.1；specs/legacy-test-baseline-green/spec.md「全量测试基线全绿」Scenario）：按验收命令原样 python3 -m pytest tests/ -q（安静模式只带 -q 不并列 -v，断言用 exit_code +「 passed」汇总行——pytest 9 中 -v/-q 并列会使 -q 覆盖 -v 退化输出）。预期 0 failed（passed/skipped/xfail 均可接受）；基线量级 ~10k 用例 / ~700s，timeout 1700s（<引擎单步上限 1800s，约 2.4 倍余量）。验收环境注记：若出现 tasks 所列 11 项之外的新失败，按 tasks 8.1 同款归因纪律处置（[WIP]/[隔离]/环境类按 engine 结果附 parallel_context 出具豁免上下文），不删除不放宽测试。同 resource_group=pytest-serial 串行执行，消除并发套件 CPU 争抢伪失败面。出处：tasks.md §8.1；specs/legacy-test-baseline-green/spec.md；design.md Risks。 | pass | 0/2 | - |
| full-suite-green-run-2 | 验收主门·第 2 次（tasks 8.1「间隔执行跑两次」）：同验收命令 python3 -m pytest tests/ -q 再跑一轮、断言 exit 0 +「 passed」——depends_on 串在 run-1 之后即两轮间隔先后执行（design.md Risks：flaky 失败偶发复现失败 → 两次全量确认稳定）。同 resource_group=pytest-serial；timeout 1700s 同 run-1；新失败按 tasks 8.1 归因纪律处置。出处：tasks.md §8.1；design.md Risks / Open Questions。 | pass | 0/2 | - |
