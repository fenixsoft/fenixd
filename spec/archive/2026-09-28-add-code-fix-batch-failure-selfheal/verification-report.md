# 验证报告：add-code-fix-batch-failure-selfheal

> ⚠️ 本报告由框架于 2026-09-22T19:05:55Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-09-22T19:05:55.188162+00:00

## 结论：✅ 通过（verified）

**状态：verified — 15/15 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 15/15 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 15 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 7.10M |
| 本链增量 Token（输出） | 0.12M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| selfheal-test-suite-green | 交付物测试套件全绿：pytest tests/test_code_fix.py -v（91 用例，含本 SPEC 新增的 TestFailureLockRelease/TestRetryBudget/TestChainSkippedLifecycle 与按新语义改写的存量断言——原「保留 worktree MUST NOT cleanup」「失败批终止链」类已改写为现场即弃/链继续）。命令只带 -v 不带 -q（pytest 9 中 -q 吞掉 PASSED 行），断言子串照抄实测输出。出处：tests/test_code_fix.py:1954（锁释放）、:2032（重试预算）、:2135（chain_skipped 生命周期）；spec specs/code-fix-batch-selfheal/spec.md 全部 4 Requirement。 | pass | 0/7 | - |
| selfheal-contract-surface | 模块契约面探针：FAIL_RETRY_MAX==3 为模块 int 常量（不新增配置键，design.md D3）；FIX_PROGRESS_DEFAULT 含 chain_skipped 键且缺省空列表（core/code_fix.py:85）；select_batch 签名含可选 exclude_ids（core/code_fix.py:391，缺省 None 向后兼容）；record_failed_batch 兼容既有三位置参调用（project_root/item_ids/worktree）且新增 reason/branch/tip_sha 关键字缺省空串（core/code_fix.py:264，design.md D7 零破坏）；release_retryable_failed_batches 可调用（core/code_fix.py:309）。 | pass | 0/2 | - |
| selfheal-record-failcount-dedupe | 失败档案数据层探针：首记 fail_count=1 且 reason/branch/tip_sha/failed_at 齐全；旧式三位置参调用（不带新关键字）落档 fail_count=1、reason 空串（向后兼容）；同条目集乱序（b,a vs a,b）再入档复用记录 fail_count 1→2 并刷新 reason/branch/tip_sha、不追加重复记录（core/code_fix.py:280-301；spec Scenario 同条目集再失败递增 fail_count 而不重复入档）；不同条目集另起新记录。 | pass | 0/2 | - |
| selfheal-budget-release-alert-once | 重试预算生命周期探针（数据层）：混合预算档案（fail_count 1/2/3）经 release_retryable_failed_batches 仅释放 <3 的两条、达上限记录保持（spec Scenario 混合预算档案的选择性释放）；fail_count 递增至 3 的那次入档恰好发一条 code_fix_retry_budget_exhausted warning 告警（点名录条目）并在 .fenix/todo.md 追加待人工项（含 branch/tip_sha 追溯线索、不引用已清理的 worktree 路径、不含「保留 worktree」「车道不再自动重派」旧表述）；此后重复入档与新链释放均不再追加告警（一次性，D4）；预算内入档不产生告警与 todo 项；达上限记录条目仍被 select_batch 排除。 | pass | 0/2 | - |
| selfheal-select-batch-exclude-ids | select_batch 双重排除口径探针（数据层）：缺省调用（exclude_ids 缺省 None）只排除失败档案条目——向后兼容、既有调用点零改动（design.md D5）；exclude_ids 并集进排除集（失败档案 ∪ chain_skipped）；排除集补齐后返回空列表（consumed 链正常收敛出口）；first_seen_at 升序选批与 batch_size 截断语义保持不变（core/code_fix.py:391-421）。 | pass | 0/2 | - |
| selfheal-progress-merge-keeps-chain-skipped | 进度快照合并语义探针（数据层）：read_progress 对缺失文件返回含 chain_skipped=[] 的缺省态（core/code_fix.py:85,127）；write_progress 合并式原子写（core/code_fix.py:142-158）——写入 chain_skipped=[a] 后再写无关字段（done），chain_skipped 保留不被剥落（新键 MUST 进缺省集的合并契约）；显式传 chain_skipped=[] 可覆盖（新链启动重置路径 core/code_fix.py:814-815 的数据层前提）。 | pass | 0/2 | - |
| selfheal-regression-twice-discard-continues | 编排器行为探针：第 1 批两次全量回归均失败（regression_failed_twice）→ 现场即弃：cleanup 前把 branch/tip_sha 入失败档案（reason=regression_failed_twice、failed_at 齐全）、worktree 目录被清理、code-review-fix:code-fix 锁释放（enforce_lock 假 WM 下第 2 批 create 不被拒）；warning 告警措辞「已跳过，下轮自动重试」且不含「待人工处置」（可见性去人工化）；进度 current 含「第 1 批失败已跳过（两次回归未通过）— 继续后续批次」（D6）；链自驱动推进第 2 批并正常消费（core/code_fix.py:1175-1201、1029-1038；tests/test_code_fix.py:1970）。 | pass | 0/2 | - |
| selfheal-merge-conflict-discard-continues | 编排器行为探针：第 1 批 merge_back 返回冲突（merge_back_conflict）→ 现场即弃（cleanup success=False、worktree 目录删除、锁释放、档案记录含 branch/tip_sha/reason=merge_back_conflict）、链自驱动第 2 批建树不被残留锁拒绝并成功合回核销（b 置 resolved）、进度 current 含「第 1 批失败已跳过（合回冲突）— 继续后续批次」（core/code_fix.py:1241-1258；tests/test_code_fix.py:1998；spec Scenario 合回冲突批失败后 worktree 被清理且锁释放/链继续推进下一批）。 | pass | 0/2 | - |
| selfheal-agent-run-failed-chain-skip | 编排器行为探针：第 1 批首次修复 run 失败（agent_run_failed，瞬态）→ 条目写入进度快照 chain_skipped、worktree 清理释放锁、MUST NOT 写 fix-failed.json 永久档案（不烧跨轮预算）；链自驱动推进，可选池按 chain_skipped 排除后收敛终态（phase=blocked、reason=failed_batch_retained、current 含「下轮自动重试」）；条目保持 open；新链启动重置 chain_skipped 为空并重新组批消费同一条目（core/code_fix.py:1108-1120、826-858、814-821；tests/test_code_fix.py:2138）。 | pass | 0/2 | - |
| selfheal-retry-run-failed-chain-skip | 编排器行为探针：第 1 批首次回归失败后重试 run 又失败（regression_retry_run_failed）→ 与「两次回归均失败」区别对待：run 失败≠回归失败，MUST NOT 入失败档案（不烧跨轮预算），条目入 chain_skipped、worktree 清理释放锁、进度 current 含「第 1 批失败已跳过（重试 run 失败）— 继续后续批次」、reason 前缀 regression_retry_run_failed、链自驱动收敛（core/code_fix.py:1154-1170；tests/test_code_fix.py:948）。 | pass | 0/2 | - |
| selfheal-zero-effective-fix-chain-skip | 编排器行为探针：批内产物行全部 skipped（零有效修复）且回归 passed → MUST NOT 合回（merge_back 零调用）、MUST NOT 置 resolved、worktree 清理、条目入 chain_skipped、链继续推进（consumed，MUST NOT 终止链——零产物批按 halt 会永久堵住队列头）；进度 reason=no_effective_fix、current 含「第 1 批失败已跳过（无有效修复）— 继续后续批次」；fix-failed.json 保持空（core/code_fix.py:1217-1232；tests/test_code_fix.py:2195；spec Scenario 零有效修复拒合回）。 | pass | 0/2 | - |
| selfheal-halt-paths-keep-chain-stop | halt 语义保持探针（环境性失败链终止，与 consumed 对照）：(a) worktree_manager.create 返回 None → 进度 phase=failed、reason=worktree_create_failed、不派 run 不合回、条目保持 open、不自驱动（executor 无再投递）；(b) worktree_manager 缺失 → reason=worktree_manager_missing；(c) 批 worker 内异常（run_code_fix 抛错）→ reason 前缀 batch_worker_error 且单飞复位。三条 halt 路径均 MUST NOT _resubmit（core/code_fix.py:1052-1062、1020-1038；spec Scenario 环境性失败保持链终止；tests/test_code_fix.py:784）。 | pass | 0/2 | - |
| selfheal-consumed-batches-converge | 收敛性探针：3 条 open、batch_size=1、每批两次回归均失败（连续 consumed）→ 链在投递守卫上限内恰好推进 3 批后正常收敛（不发生无限空转/递归，design.md D1 收敛论证：可选池严格单调缩小）；终态 phase=blocked、reason=failed_batch_retained；失败档案恰 3 条记录、各 fail_count=1（预算内，下轮自动重试）；chain_skipped 保持空（回归失败入档案不入链内跳过）；全部条目保持 open（core/code_fix.py:826-858、1029-1038；spec Scenario consumed 循环必然收敛）。 | pass | 0/2 | - |
| selfheal-new-chain-reset-and-release | 新链启动语义探针：预置死链进度（running=false、chain_skipped=[q]）与混合预算失败档案（q: fail_count=1、r: fail_count=3）→ 新 checkpoint 判定非同一链身份：先自动释放预算内档案（q 记录移除，等效人工 release_failed_batch——spec Scenario 失败条目下轮自动重试/预算内失败批下轮自动重试）、达上限的 r 记录保持且其条目仍被排除、chain_skipped 重置为空、被释放条目 q 重新入批（select_batch 选中）并派发；链身份判定前移到选批之前——上一链全跳过收敛后下一 checkpoint 不会恒走选批为空早退（core/code_fix.py:795-824；tests/test_code_fix.py:2076）。 | pass | 0/2 | - |
| selfheal-regression-retry-then-pass | 正向路径探针（回归门）：第 1 批首次回归 failed → 同一 worktree 内重试一次（第二次 run_code_fix 带 failure_summary 注入上一轮失败用例摘要）→ 第二次回归 passed → merge_back 合回、fixed 条目按 item_id 精确置 resolved、进度 current 含「第 1 批完成（已核销 2 条，累计 2/2）」、cleanup success=True（spec code-fix-lane Scenario 首次失败重试一次后成功/回归通过则合回并核销；core/code_fix.py:1132-1201、1234-1278；tests/test_code_fix.py:903）。 | pass | 0/2 | - |

## 本轮场景集变更

当前稳定场景集共 15 个（第 1 轮）。

- 首轮写入 15 个场景

