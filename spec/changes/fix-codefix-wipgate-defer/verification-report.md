# 验证报告：fix-codefix-wipgate-defer

> ⚠️ 本报告由框架于 2026-09-23T04:46:33Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-09-23T04:46:33.516149+00:00

## 结论：✅ 通过（verified）

**状态：verified — 10/10 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 10/10 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 10 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 6.01M |
| 本链增量 Token（输出） | 0.12M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| wipgate-defer-classify-no-budget | 分类语义·defer 路径不烧失败预算（spec code-fix-wipgate-defer Scenario「wip_gate_blocked 不烧失败预算」+「首次 defer 即提示」）：FakeWM.merge_back 返回 success=False 且 wip_gate_blocked=True（wip_overlap=['core/a.py']）→ 批 a 收尾走 defer 路径：fix-failed.json 零记录（不烧 fail_count）、worktree 目录保留（零 cleanup 调用）、进度 reason=wip_gate_blocked 且 current 含「主树未提交改动」与交集文件名、批 worker 放行链继续（自驱动再投递在场）、条目保持 open；同时恰发 1 条含交集文件清单的 info 级提示告警。出处：core/code_fix.py:1291-1310（既有合回失败分支，defer 分派点）、core/worktree_manager/types.py:52-58（wip_overlap/wip_gate_blocked 字段）、core/admin_store.py:237（AdminStore.append 告警通道）。 | pass | 0/2 | - |
| wipgate-defer-record-seven-fields | defer 台账七字段完整可恢复（spec Scenario「defer 记录完整可恢复」，design D2）：一批进入 defer 后 .fenix/code-review/fix-deferred.json 新增恰好一条记录，worktree/branch/tip_sha/item_ids/defer_count/first_deferred_at/last_overlap 七字段齐全；first_deferred_at 为 UTC ISO8601；worktree 路径在磁盘真实存在，git rev-parse HEAD 等于记录 tip_sha 且可在分支解析为 commit，分支名等于记录 branch；分支含 agent 修复提交（rev-list 计数=2：init+fix）；台账原子写无 .tmp 残留文件。出处：tasks.md 1.2、design.md D2。 | pass | 0/2 | - |
| wipgate-defer-retry-clean-auto-merge | 延迟批自动重试·主树清理后自动合回（spec Scenario「主树清理后自动合回」，design D4/D7）：批 a defer 后主树变干净，链边界 checkpoint 在选批前对保留 worktree 直接重跑 merge_back（不重跑 agent：fix run 全程恰 2 次=a、b 各一次，create 恰 2 次）→ 合回成功：a 核销 resolved、worktree 以 success=True 清理并删目录、台账条目移除、进度 current 含「延迟批合回成功」且 done 累加；链继续批 b 正常合回核销，收敛后台账与失败档案均为空。出处：core/code_fix.py:747（checkpoint 单一入口=两重试时机宿主）、:855（选批点=重试时机①锚位）。 | pass | 0/2 | - |
| wipgate-defer-retry-still-blocked | 延迟批重试·主树仍脏时无害（spec Scenario「主树仍脏时重试无害」）：链边界重试对保留 worktree 实际尝试 merge_back 仍返回 wip_gate_blocked=True → 台账条目原样保留（worktree 路径与 first_deferred_at 不变）、defer_count 按实际尝试恰 +1、worktree 保留、不降级入失败档案、不发 warning 告警、条目保持 open。注：spec 场景正文「defer_count 不变」与预算门「递增达 6 次」自相矛盾，本场景按 tasks.md 2.3/design D4 口径断言「实际尝试仍阻断才 +1」。出处：tasks.md 2.3、design.md D4。 | pass | 0/2 | - |
| wipgate-defer-budget-expired-degrade | 延迟预算双门耗尽降级与一次性告警（spec Scenario「预算耗尽降级并告警」，design D6）：①时间门：预置 first_deferred_at 超 90 分钟的台账条目（worktree 为真实 git 仓库存活）→ 链重试判定预算耗尽：以 reason=wip_gate_blocked_expired 入 fix-failed.json（fail_count 递增、item_ids 含批条目）、worktree 以 success=False 清理、台账条目移除、恰发 1 条含交集文件清单与 stash 处置提示的 warning 告警；②同条目集再次过期降级 → 告警仍恰 1 条（按 item_ids 指纹一次性，指纹不得混入 worktree/tip 等每次不同的字段）；③次数门：first_deferred_at 新鲜但 defer_count=6 → 同样降级（档案+清理+台账移除）且不新增告警。出处：tasks.md 3.1/3.2、design.md D6。 | pass | 0/2 | - |
| wipgate-defer-restart-survivor | 换链/重启再认领·存活条目续试（spec Scenario「重启后台账存活条目续试」，design D5）：预置台账条目（worktree 为真实 git 仓库、分支 tip 可解析、defer_count=2、first_deferred_at 为当轮时刻）后以全新链身份启动（进度无 running 链，等效 daemon 重启后的新链）→ 再认领保留条目：重试合回时刻在 merge_back 包装器内快照台账，defer_count/first_deferred_at 与预置值一致（不重置）；随后合回成功：条目核销 resolved、worktree 以 success=True 清理、台账清空；agent 零重跑（fix run 0 次）、不误入失败档案。出处：tasks.md 4.1、core/code_fix.py:845-854（新链启动分支=再认领接线锚位，release_retryable_failed_batches 旁）。 | pass | 0/2 | - |
| wipgate-defer-lost-worktree-reclaim | 换链/重启再认领·worktree 丢失条目回收（spec Scenario「worktree 丢失条目回收」，design D5）：预置台账条目指向已不存在的 worktree 路径 → 新链启动再认领判定：条目移出台账并记 warning 日志（含丢失 worktree 路径）；条目从未核销，仍在 open 池（状态 open、不写失败档案），select_batch 可重新选中（可重选批实证）；不发 admin 告警（丢失回收只记日志）。出处：tasks.md 4.1、core/code_fix.py:315（release_retryable_failed_batches 旁接线锚位）、:397（select_batch 排除口径=失败档案，回池条目可再选）。 | pass | 0/2 | - |
| wipgate-true-conflict-unchanged | 回归锁定·真冲突维持现状（spec Scenario「真冲突维持现状」，design D1 不解析错误文案只读标志）：批合回返回 success=False 且 wip_gate_blocked=False → 行为与改动前一致：条目入 fix-failed.json（reason=merge_back_conflict、fail_count 递增、branch/tip_sha 留痕）、worktree 以 success=False 清理、进度 current 含「合回冲突」、不写延迟台账、链继续；第 2 批以不带 wip_gate_blocked 属性的朴素冲突对象验证 getattr 缺省 False 容错——同样走既有冲突路径、不误入 defer。出处：design.md D1、core/code_fix.py:1292-1310（既有现场即弃分支）。 | pass | 0/2 | - |
| wipgate-defer-retry-convergence-exit | 重试时机②·收敛出口重试（design D4②/tasks 2.2）：整批（a,b）defer 后链边界重试①仍被阻断（条目保留）；人工把 a、b 置 resolved 模拟 defer 期间条目离开 open 池，主树变干净 → count_open_items==0 收敛早退之前应对延迟批重试 merge_back：合回成功（台账清空、worktree 以 success=True 清理）、全程 agent 零重跑（fix run 恰 1 次）、终态 phase=idle。出处：tasks.md 2.2、core/code_fix.py:809-826（count_open_items==0 收敛早退分支=重试时机②锚位）。 | pass | 0/2 | - |
| wipgate-test-suite-green | 交付物测试套件全绿（tasks.md 5.1-5.5：分类单测/defer 端到端/预算降级/再认领/回归锁定 + 存量回归）：pytest tests/test_code_fix.py -v --tb=short 全部通过（exit_code=0；-v 下每个通过用例行含 PASSED）。命令只带 -v 不带 -q（pytest 9 中 -q 覆盖 -v 会吞掉 PASSED 行导致 output_match 伪失败）；不锁定用例数与新测试命名（由实现者按任务清单自行组织，行为覆盖由本组其余探针场景承担）。 | pass | 0/2 | - |

## 本轮场景集变更

当前稳定场景集共 10 个（第 1 轮）。

- 首轮写入 10 个场景

