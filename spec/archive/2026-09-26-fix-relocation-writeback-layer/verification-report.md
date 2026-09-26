# 验证报告：fix-relocation-writeback-layer

> ⚠️ 本报告由框架于 2026-09-22T06:46:05Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-09-22T06:46:05.029975+00:00

## 结论：✅ 通过（verified）

**状态：verified — 15/15 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 15/15 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 15 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 1.57M |
| 本链增量 Token（输出） | 0.03M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| writeback-target-verdict-by-source | 写回层判定四态：resolve_writeback_target 按生效声明命中层 source 返回 writable/spec_dir/commit_root——worktree 命中可写（提交根=该 worktree）、main 命中可写（提交根=主树，就地写入同源不得禁止）、branch 唯一命中不可写（事故态：写主树守卫读分支）、两处均不可用不可写；对应 deliverable-declaration-resolution「来源标注可判定写回层」。出处 tests/test_relocation_writeback_layer.py:202 TestResolveWritebackTarget（4 用例） | pass | 0/6 | - |
| judge-typo-worktree-writeback-commit | 有 worktree 时修正写进工作树：judge 裁决 typo 后改写作用于实现 worktree 内 spec/changes/<spec>/tasks.md，并经该 worktree 分支提交（非主树）——写回层与守卫读取基准同源。出处 tests/test_relocation_writeback_layer.py:258 test_worktree_hit_writes_worktree_and_commits_branch | pass | 0/3 | - |
| judge-typo-main-hit-inplace-writeback | 主树为命中层时就地主树写入（不得禁止）：无 worktree 且分支对象库无声明段（source=main）时，judge typo 改写主树 tasks.md 并提交主树，守卫复读（同为 main）可见修正——锁定 2026-09-15 merge-back 死锁修复的既有就地软化+立即提交语义不回归。出处 tests/test_relocation_writeback_layer.py:294 test_main_hit_writes_main_tree_and_commits | pass | 0/3 | - |
| judge-typo-branch-hit-no-main-fake-fix | 分支为唯一命中层时不写主树假装修正（add-code-review-auto-fix 事故态）：worktree 已清理、source=branch（spec_dir=None，声明只存在于分支对象库）时 MUST NOT 调 replace_declared_path 写主树，转打回/凭据通道，且该条 typo 裁决（element+actual_path）落 dispute 审计流供跨轮核销。出处 tests/test_relocation_writeback_layer.py:314 test_branch_hit_never_writes_main_tree | pass | 0/3 | - |
| judge-typo-worktree-conflict-degrades | worktree 写入冲突降级（fail-safe）：写回层为 worktree 但写入/提交失败（worktree 被实现 run 占用、git add/commit 冲突或异常）时降级为打回/凭据通道，MUST NOT 改落主树兜底、MUST NOT 静默判修正成功。出处 tests/test_relocation_writeback_layer.py:341 test_worktree_commit_conflict_degrades | pass | 0/3 | - |
| correction-readback-consistency | 修正后读取一致性复检：verify_correction_readback 以守卫读取基准（worktree>branch>main）复读被修正旧路径不再以原 kind 出现；修正只落非读取基准层（分支仍含旧路径）时返回 False 且裁决侧记 error 明细+WARNING 告警（不静默销账）；修正真实生效后复检通过放行。出处 tests/test_relocation_writeback_layer.py:377 TestReadbackMismatch（3 用例）、core/deliverables.py:718 | pass | 0/5 | - |
| guard-credential-redemption-suite | 缺件凭据核销收敛四态：凭据在册且替代路径在实现分支 HEAD 存在→核销（不计入违规清单、不重派不 blocked）；凭据在册但替代路径未落地→不核销（防空洞，走既有缺件处置）；kind:delete 的 undeleted 条目即使有凭据也不被核销（作用域限于 missing）；relocation_credential_target 返回替代路径（布尔判定不足以免责）。出处 tests/test_relocation_writeback_layer.py:422 TestGuardCredentialRedemption（4 用例）、core/pm_engine/verification/branch_guard.py:287 | pass | 0/6 | - |
| credential-target-direct-query-behavior | 直连真实实例代码的凭据查询行为验证（非交付测试自证）：在临时目录伪造 .fenix/dispute_audits.jsonl 的两种在册凭据形态（judge typo 裁决 verdicts[element].actual_path 与 relocation 记录 old_path/new_path），调 core.deliverables.relocation_credential_target 断言返回替代路径；无凭据路径返回 None（fail-safe 不误核销）。出处 core/deliverables.py:865、core/admin_store.py:620 DisputeAuditStore（jsonl 逐行审计流） | pass | 0/5 | - |
| writeback-recur-fuse-independent-counter | 复发熔断独立持久字段：_writeback_recur_streak 在 blocked→ready 复位/恢复续做时不被清零（MUST NOT 复用会被 state_machine 清零的 _retry_count——事故态 31 小时在飞期间恒为 0）；同 spec 换路径时 streak 归零重计；typo 修正复检通过清零；同路径连续复发达上限置 blocked 且 error 文案区分「修正未生效于读取基准」。出处 tests/test_relocation_writeback_layer.py:507 TestWritebackRecurFuse（4 用例） | pass | 0/6 | - |
| unfreeze-anchor-durability-suite | 解冻续做锚点耐久：裸 unfreeze_spec（未传 project_root/worktree_manager）由 spec 名自解析项目根后完成保留判定，保留分支锚点不被静默丢弃（branch 保留+_recovery_resume 置位）；worktree 载体已清理经分支命名空间枚举仍记录续做分支；显式传参路径采用续做分支；无可续分支时降级 MUST 落 Unfreeze resume degrade WARNING（绝无静默）。出处 tests/test_relocation_writeback_layer.py:581 TestUnfreezeAnchorDurability（4 用例）、core/state_machine.py:969 unfreeze_spec | pass | 0/6 | - |
| unfreeze-existing-behavior-regression | 解冻/冻结既有行为回归：无 _frozen_hold 的解冻与改动前逐位一致（不触发续做接线）、解冻命中保留分支续做、载体缺失保锚点、保留判定不通过降级——freeze-stop-inflight-agents 既有 Scenario（含 Dashboard 显式传参形态）不回归。出处 tests/test_freeze_stop_inflight_agents.py:397-464（全套 16 用例） | pass | 0/6 | - |
| softened-main-commit-regression | main 来源就地软化+立即提交语义回归（2026-09-15 merge-back 死锁修复被锁定断言）：fixture 无真实 worktree/分支时解析为 source=main，reference 软化改写主树 tasks.md 后 MUST 立即提交，提交失败不得中断裁决；写回层判定不得把 main 一刀切为不可写。出处 tests/test_deliverable_declaration_triage.py:926 TestSoftenedDeclarationIsCommitted（2 用例） | pass | 0/4 | - |
| declaration-resolution-priority-regression | 分层解析优先序回归：worktree>branch>main 固定优先序、分支版本优先于主树（在测的那份）、分支读取失败回退主树、两处均不可用返回空（守卫按无声明段跳过）——deliverable-declaration-resolution 既有解析契约不被写回层改动破坏。出处 tests/test_declaration_resolution.py:109 TestResolveEffectiveDeclaration（9 用例） | pass | 0/6 | - |
| declaration-relocation-audit-regression | 重定位机械执行与审计回归：三要素齐备时旧路径确定性替换为替代路径（同名去重）、替代路径不在分支时拒绝自动重定位（凭据三要素校验）、陈日声明按 basename 重定位、审计落册含前后 diff（人工可回滚依据）——declaration-relocation-protocol 既有机械执行契约不回归。出处 tests/test_declaration_relocation.py:174 TestRelocationRewrite、:131 TestRelocateCredentialTriad（全套 18 用例） | pass | 0/5 | - |
| preclassify-writepoints-regression | 声明段全部写入点回归：_preclassify_missing 确定性软化与 _preclassify_orphan 孤儿条目删除（tasks 2.5 全量清点清单中的既有写入点）在接线写回层判定后行为不回归（fixture 同为 source=main 落点不变）。出处 tests/test_deliverable_declaration_premechanize.py（36 用例）、tests/test_deliverable_orphan_preclassify.py（33 用例） | pass | 0/2 | - |

## 本轮场景集变更

当前稳定场景集共 15 个（第 1 轮）。

- 首轮写入 15 个场景

