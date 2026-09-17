# 验证报告：fix-preserve-chain-first-round-gap

> ⚠️ 本报告由框架于 2026-09-12T05:55:36Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。

## 结论：✅ 通过（verified）

**状态：verified — 16/16 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 16/16 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 16 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 2.20M |
| 本链增量 Token（输出） | 0.03M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| preserve-first-round-sidecar-resolves-branch-worktree | 终止前保全·首轮在飞 run 保全条目非空：STATE branch 未写（run 未到终态即被排水强杀）时，_preserve_interrupted_runs 回落 find_worktree_by_spec 事实查询（git worktree list --porcelain 为真相、不信任重启即失的内存表）解析出 branch 与 worktree，sidecar（.fenix/interrupted_runs.json）条目 MUST 含非空分支与路径并先于 terminate 落盘（spec 终止前保全 Req1『终止前 sidecar 已落盘』『首轮在飞 run 的保全条目含 branch 与 worktree』；fenixd.py:1156-1165 回落解析、:1201 落盘；state_machine 无 STATE 中间态 | pass | 0/3 | - |
| preserve-sidecar-failure-degrades-nonblocking | 终止前保全·异常路径：sidecar 写入失败（_write_preserve_sidecar 返回 False）降级 WARNING 日志、不阻塞停机（spec 终止前保全『写入失败降级为 WARNING 日志，不阻塞停机』；fenixd.py:1201-1207）；cleanup_orphans 收到保全解析出的保护集（fenixd.py:1334 调用侧、:1314 保护集组装），停机链路不因保全异常中断 | pass | 0/3 | - |
| preserve-protected-set-fallback-fact-query | 清理协调·保护集回落事实查询：首轮在飞 run 保全部把回落解析出的 worktree 补入 seen_wt 保护集（spec Req3『保护集的构造 MUST 同样回落事实查询』；fenixd.py:1165）；sidecar 条目 worktree 为空串但该 spec 在册 worktree 仍在时，MUST 经事实查询补入保护集、MUST NOT 放行清理（spec Req3 Scenario『保护集从事实查询回落』；tests TestFirstRoundPreserve 保护集两用例），守护『多保不删』决策 | pass | 0/3 | - |
| recovery-preserve-branch-with-commits | 恢复保留·有提交分支保留续做：interrupted 的 implementing spec 分支在册且相对 main 有未合并提交（git rev-parse main..branch 非空）→ 保留 branch/implementer_run 引用、写 _recovery_resume 标记恢复续做、tester_run 清空（spec 恢复保留 Req2 Scenario『有提交分支保留并续做』；core/state_machine.py:868-944） | pass | 0/2 | - |
| recovery-zero-commit-still-clears | 恢复保留·零提交走现行清空（回归红线）：分支不存在或相对 main 零提交 → 按现行行为清空implementer_run/branch 并新建重派、无 _recovery_resume 标记（spec Req2 Scenario『零提交分支走现行清空』『行为逐字节兼容』；state_machine.py:894-913 判定、:855-864 清空）；首轮端到端零提交分支同样走清空重建（无提交则无工作可丢，design Risk 末条） | pass | 0/4 | - |
| recovery-worktree-rebuilt-when-missing | 恢复保留·worktree 缺失时从分支重建：保留分支存在但其 worktree 目录已被清理（rebuildable 态）→ 在既有分支上创建新 worktree 载体续做、检出的仍是保留分支而非新分支、保留 _recovery_resume 标记（spec Req2 Scenario『worktree 缺失时从分支重建』；state_machine.py:914-922 resolve_resume_site 三态、worktree_manager.py resolve_resume_site:3233-3259） | pass | 0/2 | - |
| recovery-state-branch-empty-fallback | 恢复保留·STATE branch 空回落事实查询：interrupted spec 的 STATE branch 为 None 但其在册 worktree归属分支相对 main 有未合并提交 → 判定保留续做、MUST NOT 清空 branch/worktree 后从零重派（spec Req2 Scenario『STATE branch 为空但在册 worktree 有提交』；state_machine.py:882-893 回落）；STATE branch 空且在册分支零提交 → 仍走现行清空（tests TestRecoveryStateBranchFallback 两用例） | pass | 0/3 | - |
| recovery-legacy-signature-regress | 恢复保留·回归红线：旧签名（无 project_root/worktree_manager 参数的 _recovery_preserve_spec/recover_interrupted）行为逐字节兼容——走清空路径不引入新异常；testing 状态中断恢复语义不变（→implemented 重验、branch 保留）；resume 继承注记仅在标记重用时注入 prompt、未标记不注入（spec Impact 回归红线；state_machine.py 旧调用路径；prompt_builder 恢复续做注记不回归） | pass | 0/5 | - |
| cleanup-orphans-protected-kept | 清理协调·保全 worktree 不被误删：cleanup_orphans 收到保护集时跳过保全在册 worktree（目录保留、可 resume 原地续做），未保护 worktree 照常清理；boot recovery 保留判定先于 stale 清理执行、保护目录经历 shutdown+boot 双清理仍存活（spec Req3 Scenario『保全 worktree 不被误删』；worktree_manager.py:724-767 cleanup_orphans 保护集跳过、tests TestCleanupCoordination 三用例） | pass | 0/4 | - |
| cleanup-snapshot-before-delete | 清理协调·硬删前留档：cleanup_orphans 对未保护 dirty worktree 执行强制删除前 MUST 先调用 _snapshot_dirty_worktree（快照发生在目录尚存在的删除前时刻）并日志留痕；cleanup 的 `git worktree remove --force` 成功路径（returncode 0、未走 rmtree 兜底）MUST 同样在删除前完成留档；同一次清理对同一 worktree MUST 只产生一次快照（幂等/前置短路）（spec Req3 Scenarios『orphan 清理硬删前留档』『强制删除成功路径同样留档』、tasks 3.3；worktree_manager.py:755 cleanup_orphans 留档、:614 cleanup 前置留档升级、tests TestSnapshotBeforeDelete 三用例） | pass | 0/4 | - |
| find-worktree-by-spec-exact-match | D1 事实查询·正向：find_worktree_by_spec 按 worktree 命名约定（impl-/verify-<spec>-<ts>）以完整 spec 名+分隔符边界匹配返回 (wt_path, branch)；spec 名互为前缀（fix-x 与 fix-x-y）不误匹配；目录被外部删除但分支在（rebuildable）仍命中（供恢复重建依据）（spec design D1；worktree_manager.py:3116-3217 find_worktree_by_spec/_wt_name_matches_spec） | pass | 0/5 | - |
| find-worktree-by-spec-ambiguity-degrade | D1 事实查询·异常路径：同一 spec 存在多个在册 worktree → 歧义返回 None 并 WARNING（MUST NOT 静默取首个）；候选分支不可解析（update-ref -d 删分支 ref、三态非 available/rebuildable）不作保全/保留依据返回 None；无在册 worktree/空输入（'' / None）→ None（spec design D1 歧义与降级、tasks 1.1-1.3；worktree_manager.py:3179-3198 三态校验与歧义 WARNING） | pass | 0/4 | - |
| regression-non-planned-sigterm-fast-path | 回归红线·停机路径零变化：restart_request 不在册（非计划 SIGTERM）→ 不排水、不写 sidecar 的快速停机路径逐字节不变；计划重启（restart 在册）走排水等待窗口；shutdown_drain_seconds=0（快速停机）语义不变（spec design D4 非目标『非计划 SIGTERM 快速停机』、Impact 回归红线；tests TestShutdownDrain test_non_planned_restart_fast_path/test_planned_restart_drains/test_drain_zero_fast_path） | pass | 0/4 | - |
| e2e-drain-kill-preserve-recovery-resume | 端到端·排水强杀保全→重启恢复续做：真实 git 仓库 + 真实 WorktreeManager + daemon shutdown 排水路径——首轮在飞 run（STATE 无 branch 字段、在册 worktree 分支已有提交）排水超时强杀 → sidecar 条目含分支与worktree 路径、保全 worktree 不被 cleanup_orphans 删除；重启后 recovery 判定保留续做（保留原分支/implementer_run、_recovery_resume 标记、载体原地在场），MUST NOT 从零重派新分支（tasks 5.1/5.2；tests TestFirstRoundEndToEnd::test_e2e_preserve_and_recovery_resume） | pass | 0/2 | - |
| direct-codepath-verify | 直接行为级验证：独立于 pytest 夹具驱动真实框架代码路径——内联 Python 脚本自建临时 git 仓库，直接调用真实 WorktreeManager：find_worktree_by_spec 精确匹配（impl-/verify- 前缀命中、spec 名前缀不误配、歧义/空输入返回 None、目录被删但分支在 rebuildable 仍命中）；_snapshot_dirty_worktree 对含已提交跟踪文件修改的 dirty worktree 生成可取证 stash 快照 SHA（git cat-file -t 可解析为 commit 对象）；cleanup_orphans 保护集跳过+非保护 dirty worktree 删除前快照留档时序；stdout 按行输出 PASS:<tag> 标记供 contains 断言匹配（脚本自包含、不触碰真实项目状态，cwd 相对验证树根即 repo 根；对应 spec 3.x 留档可取证承诺：快照 SHA 必须可解析） | pass | 0/10 | - |
| worktree-availability-three-state | 回归·is_available 三态单源：available（在册+分支可解析）/ rebuildable（目录缺失但分支在，含未注册worktree）/ unavailable（分支消失/空输入）三态判定与三链路（保全、恢复保留、重建）判断一致——本 SPEC 新查询 find_worktree_by_spec 以该三态为单源校验，回归该基座不漂移（spec design D1『经 is_available 三态单源校验』；worktree_manager.py is_available；tests TestIsAvailable 全部用例） | pass | 0/7 | - |

## 本轮场景集变更

当前稳定场景集共 16 个（第 1 轮）。

- 首轮写入 16 个场景

