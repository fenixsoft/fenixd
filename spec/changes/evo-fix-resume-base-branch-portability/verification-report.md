# 验证报告：evo-fix-resume-base-branch-portability

> ⚠️ 本报告由框架于 2026-10-02T21:24:30Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-10-02T21:24:30.065197+00:00+run-result@mtime1790976270117512731

## 结论：✅ 通过（verified）

**状态：verified — 11/11 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 11/11 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 11 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 1.77M |
| 本链增量 Token（输出） | 0.03M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| base-branch-resolver-unit-tests | tasks 1.1/1.2：共享基线解析器 resolve_base_branch 解析顺序与契约单测——tests/test_git_base_branch.py::TestResolveBaseBranch 8 例（仅 master 主干无 remote→master 本事故形态、main 主干→main 零漂移、双主干并存→main、origin/HEAD 指向非 main 分支→返回该分支名、origin/HEAD 指向 main→main、非 git 目录回退 "main" 不抛异常、按 project_root 缓存命中不再起子进程且 reset_cache 后重探、git 子进程超时回退常量不抛异常）。-v 形态逐条断言 PASSED 行（无 -q 覆盖；本文件无 parametrize，用例名无后缀）。出处：core/git_base_branch.py:66 resolve_base_branch、:45 reset_cache、tests/test_git_base_branch.py:104。 | pass | 0/10 | - |
| base-branch-resolver-runtime-probe | spec「基线分支可移植解析」三条 Requirement Scenario 的运行时独立探针（不依赖交付测试代码，现场建真实 tmp git 仓驱动 core.git_base_branch.resolve_base_branch）：master 主干无 remote→master、origin/HEAD 指向 origin/main→main、origin/HEAD 指向非 main 分支→该分支名、非 git 目录→回退 "main" 不抛异常、双主干并存→main、同 root 二次调用（缓存命中）同值。stdout 为纯 JSON（git 子进程输出全被捕获），以 json_output 断言各键。出处：core/git_base_branch.py:66-110、specs/resume-base-branch-portability/spec.md Requirement 1。 | pass | 0/7 | - |
| recovery-resume-master-trunk | tasks 2.1/2.2：本事故核心回归——master 主干无 remote 仓中被排水中断的 spec 走保留续做而非清空重建。tests/test_recovery_branch_anchor.py::TestMasterTrunkRecoveryResume 2 例：①test_wip_branch_preserved_for_resume——分支含 1 个未合并 WIP 提交、STATE.branch 缺失、在册 worktree 可解析出该分支时，_resolve_preserved_branch 返回该分支（rev-list 闸门以解析基线 master 计数 >0），_recovery_preserve_spec 写入 _recovery_resume: True 与 branch，不触发「三处锚点均不可得」清空重建；②test_zero_commit_branch_still_cleared——分支相对 master 真零提交时仍走清空重建并留 WARNING，不误保留。出处：core/state_machine.py:2709 rev-list 闸门基线接入、tests/test_recovery_branch_anchor.py:479。 | pass | 0/4 | - |
| branch-queries-master-trunk | tasks 3.1/3.2：worktree_manager 查询层跨基线。tests/test_recovery_branch_anchor.py::TestMasterTrunkBranchQueries 3 例：①test_branch_enumeration_hits_candidate——master 基线仓中 spec 的 worktree 已清理、仅剩含未合并提交的实现分支时，find_branches_by_spec 第三层锚点枚举命中该候选（rev-list 计数基于 master >0）；②test_pending_merge_since_returns_commit_date——pending_merge_since 返回该分支最新提交 committer date 而非 None（修复前 `git log -1 --format=%ct main..<branch>` 恒失败）；③test_main_trunk_results_unchanged——main 主干仓枚举/排序/pending_merge_since 结果与替换前逐项一致（零漂移）。出处：core/worktree_manager/queries.py:502 find_branches_by_spec、:729 has_pending_merge/pending_merge_since。 | pass | 0/5 | - |
| terminal-no-commit-gate-master | tasks 4.1/4.3：终态零提交门跨基线。tests/test_git_base_branch.py::TestTerminalNoCommitGateMaster 2 例：①test_zero_commit_dirty_raises_gate_error——master 主干仓 implementer run 终态分支相对 master 零新提交且 dirty 取证非空时，抛出携带 [terminal-no-commit] 前缀的 AgentArtifactGateError 进入既有退避重试通道（修复前该门因 rev-list 失败 fail-open 恒放行）；②test_branch_with_commit_does_not_raise——有未合并提交时门放行不抛。出处：core/agent_runner/runner.py:1987 基线接入、tests/test_git_base_branch.py:172。 | pass | 0/4 | - |
| legacy-snapshot-master | tasks 4.2/4.3：recovery legacy 现场快照跨基线。tests/test_git_base_branch.py::TestLegacySnapshotMaster 2 例：①test_snapshot_lists_commits_on_master_trunk——master 主干仓触发 legacy 快照采集时，_legacy_branch_snapshot 的 `git log --oneline <基线>..branch` 基于解析基线执行、返回含 [fenix] impl 0 的提交清单且不以「（快照采集失败」开头（修复前 unknown revision 恒空）；②test_main_trunk_snapshot_unchanged——main 主干快照结果不变（零漂移）。出处：core/agent_runner/prompt_builder.py:1980 基线接入、tests/test_git_base_branch.py:210。 | pass | 0/4 | - |
| fenixd-ahead-count-delegation | tasks 5.1/5.2：fenixd 侧收敛单源。tests/test_git_base_branch.py::TestAheadCommitCountFenixd 2 例（经 fenixd 公开路径，patch PROJECT_ROOT 到 tmp 仓）：①test_one_commit_branch_counts_one——master 主干无 remote 仓中含 1 提交分支 _preserve_base_branch 返回 master、_ahead_commit_count 计数为 1（该值为 _preserve_interrupted_runs/_preserve_implementing_specs 保全条目 ahead_commits 字段来源，修复前 `git rev-list --count main..<branch>` 恒非零退出、ahead 恒按 0 口径、保留续做判定不命中）；②test_zero_commit_branch_counts_zero——零提交分支计数为 0。出处：fenixd.py:123 _preserve_base_branch 委托 resolve_base_branch、fenixd.py:267/4703/4868 调用点零改动、tests/test_git_base_branch.py:235。 | pass | 0/4 | - |
| branch-guard-commit-count | tasks 6.1/6.2：零变更哨与验证分支守卫共用单一来源 _branch_commit_count 跨基线。tests/test_git_base_branch.py::TestBranchGuardCommitCount 4 例：①test_master_trunk_one_commit_returns_one——master 主干无 remote 仓 1 提交分支返回 1 非 None（修复前 baselines=["main"] 候选恒失败且 origin/HEAD 回落失效→恒 None→哨漏报空转）；②test_master_trunk_zero_commit_returns_zero——真零提交分支返回 0（零变更哨可判零变更，非 None 漏报）；③test_main_trunk_unchanged——main 主干结果不变（零漂移）；④test_missing_branch_returns_none——分支不存在→rev-list 非零退出→None（fail-open 语义保留）。出处：core/pm_engine/verification/branch_guard.py:116 先解析后 rev-list 一次、tests/test_git_base_branch.py:263。 | pass | 0/6 | - |
| callsite-runtime-probe | 四个调用点的运行时独立探针（不依赖交付测试代码，现场建真实 tmp master 主干仓驱动生产代码路径）：①终态零提交门——零提交+dirty 抛 [terminal-no-commit]、1 提交放行（core/agent_runner/runner.py:1987）；②branch_guard._branch_commit_count——1 提交→1、零提交→0、缺分支→None（core/pm_engine/verification/branch_guard.py:116）；③legacy 快照含提交清单（core/agent_runner/prompt_builder.py:1980）；④fenixd._preserve_base_branch 返回 master、_ahead_commit_count 1 提交分支计数 1（fenixd.py:123）。stdout 可能含被导入模块的附加打印，故以 PROBE-RESULT 标记行 + output_match 子串断言 JSON 键值形态（json.dumps 缺省分隔符 ": "）。 | pass | 0/10 | - |
| deliverable-files-and-contract | 交付物存在性与模块契约源码检查：9 个交付物路径 file_exists（tasks.md Deliverables 全量）；core/git_base_branch.py MUST NOT import fenixd（防成环，锚定行首 import 语句形态，docstring 决策来源叙述不误伤）；resolve_base_branch/reset_cache 定义与 DEFAULT_TIMEOUT_SECONDS 超时常量在场；六处调用点（state_machine/queries/runner/prompt_builder/branch_guard/fenixd）均含 `from core.git_base_branch import resolve_base_branch` 接入行。出处：tasks.md Deliverables 段、core/git_base_branch.py:1-39 模块契约、各调用点 import 行（core/state_machine.py:20、core/worktree_manager/queries.py:24、core/agent_runner/runner.py:25、core/agent_runner/prompt_builder.py:15、core/pm_engine/verification/branch_guard.py:16、fenixd.py:47）。 | pass | 0/11 | - |
| main-trunk-regression-guard | spec Impact 回归护栏：既有 main 主干测试集全量保留且全绿——一次运行覆盖被改模块全部相关既有测试面（test_terminal_nocommit_gate / test_recovery_legacy / test_cancelled_spec_resume / test_deliverable_gate / test_freeze_stop_inflight_agents / test_recovery_watch_transition_guard / test_relocation_writeback_layer / test_facade_delegation_contract / test_impl_selfcheck_model_probe / test_git_base_branch / test_recovery_branch_anchor 共 11 文件，本工作树实测 250 passed + 549 subtests passed）。-q 安静形态 + 「N passed」断言（无 -v 并列）。出处：specs/resume-base-branch-portability/spec.md「既有测试全绿」、proposal.md Impact 回归护栏、tests/test_recovery_branch_anchor.py:85-587 既有 main 主干用例保留。 | pass | 0/3 | - |

## 本轮场景集变更

当前稳定场景集共 11 个（第 1 轮）。

- 首轮写入 11 个场景

