# 验证报告：evo-add-codefix-mergeback-conflict-salvage

> ⚠️ 本报告由框架于 2026-10-03T19:58:30Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-10-03T19:58:29.772665+00:00+run-result@mtime1791057509803259303

## 结论：✅ 通过（verified）

**状态：verified — 9/9 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 9/9 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 9 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 6.12M |
| 本链增量 Token（输出） | 0.10M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| probe-salvage-rebase-success-full-batch-merged | 合回冲突定向救回主路径（spec Requirement「合回冲突定向救回/Scenario rebase 后回归通过」；tasks 1.1/1.3）：验证树内以真实 CodeFixOrchestrator 驱动 checkpoint——真实 git 主树（branch main，resolve_base_branch 可解析）+ _FakeRunner（tests/test_code_fix.py:736）夹具，合回注入真实 MergeConflictInfo 形态的预演语义真冲突（conflict_paths/has_semantic_conflict，core/worktree_manager/types.py:106；分派点 core/code_fix.py:4424-4440）。救回应：解析基线（resolve_base_branch）rebase 批分支（夹具使 rebase up-to-date 成功）→ 重跑批回归（reg_calls=2）→ 重走合回（merge_attempts=2，救回至多 1 次）→ 整批 resolved、零入失败档案；重走合回时刻批分支引用仍可用（branch_alive_at_remerge，救回在 _safe_cleanup 前：cleanup_after_last_merge）；救回全程留「救回」日志留痕。契约锚：logger 留痕以「救回」关键词出现为断言（文案不锁死）。 | pass | 0/11 | - |
| probe-salvage-cherry-pick-partial-recovery | 冲突组粒度回收（spec Requirement「冲突组粒度回收」两 Scenario；tasks 1.2/2.1/2.2）：验证树内真实 git 驱动——主树 main 在批回归窗口前移并对 core/feat.py 同区改写（批分支看不见、合回预演才暴露的隔离根因形态，core/code_fix.py:4140），批分支两个 commit 组（docs/notes.md 非冲突组归属条目 a、core/feat.py 冲突组归属条目 b），commit body 以「items: <id>」前缀清单标注归属（agents/code-fix.md 2.2 契约）；合回注入 conflict_paths=[core/feat.py] 的真实 MergeConflictInfo。救回应：rebase 至 C2 仍冲突 → 组粒度 cherry-pick 回收 C1（条目 a 按 resolved 出账、改动真落主树：git log -p main 含 note-from-fix-c1）；仍冲突的 C2 对应条目 b 入失败档案计 fail_count=1（reason=merge_back_conflict）且保持 open 走既有预算重试；救回至多 1 次（merge_attempts<=2、reg_calls<=2）；「救回」留痕在场。 | pass | 0/11 | - |
| probe-salvage-fallback-archive-nothing-recoverable | 救回失败兜底整批入档案、行为与现状兼容（spec 验收 2 + Requirement「合回冲突定向救回/Scenario rebase 失败或回归仍不过」；tasks 1.3/2.3）：主树前移后批分支唯一提交触碰冲突文件（组粒度回收零可回收）、救回二次回归仍不过（任一失败形态）：应降级走既有现场即弃兜底——条目 a/b 全批入失败档案（fail_count=1、reason=merge_back_conflict、branch/tip_sha 追溯线索在场，与 core/code_fix.py:4436-4460 现状一致）、条目保持 open 走 FAIL_RETRY_MAX 预算、progress reason=merge_back_conflict；救回尝试至多 1 次（merge_attempts<=2、reg_calls<=2）且失败降级有「救回」WARNING/终局单行留痕。 | pass | 0/11 | - |
| probe-salvage-not-triggered-on-wip-defer | defer 路径不受影响（spec Requirement「defer 路径不受影响」；tasks 1.3）：合回注入 wip_gate_blocked=True 形态（core/code_fix.py:4431-4435 → _defer_merge_back :3796）：应照旧走 defer 零预算路径——批记入 fix-deferred.json（item_ids=a,b）、失败档案零记录（failed_n=0）、条目保持 open、回归仅 1 次（救回未触发、无二次回归）、merge 至多 2 次（defer 后链内 deferred 即时消费重试属既有语义，evo-add-wip-defer-merge-retry-consumer）、日志无「救回」字样（salvage_log=false）、progress reason=wip_gate_blocked。 | pass | 0/9 | - |
| probe-failed-archive-budget-release-semantics | 失败档案预算语义回归（spec 非目标「不改 FAIL_RETRY_MAX 预算与 release_retryable_failed_batches 释放语义」；core/code_fix.py:583 record_failed_batch 首记 fail_count=1、:904 release 打墓碑 released=true）：以真实 API 直驱 record_failed_batch(reason=merge_back_conflict, branch, tip_sha) → 字段落盘形状（branch/tip_sha 追溯线索）→ release_retryable_failed_batches 释放计数 1 且记录带 released 墓碑标——救回入档必须复用同 schema 同预算通道。 | pass | 0/7 | - |
| pytest-mergeback-conflict-salvage-suite-green | 新救回套件全绿 + 交付物实现锚点（tasks 3.1：tests/test_code_fix_mergeback_conflict_salvage.py 新建，覆盖真冲突 rebase 救回/组粒度回收/冲突组入档/cleanup 前分支可用/defer 不触发）：pytest -v 全部通过；同场景校验交付物源码锚——core/code_fix.py 出现 rebase 与 cherry-pick 救回实现（tasks 1.1/2.1 指定落在该文件），core/worktree_manager/mergeback.py 暴露冲突文件集查询方法（tasks 1.2：复用 _rehearse_merge_from_branch 的 merge-tree 预演与 MergeConflictInfo.conflict_paths，core/worktree_manager/mergeback.py:1074；tasks 1.2 未钉方法名，验收锚 def rehearsal_conflict_paths，参数形态不锁死）。 | pass | 0/5 | - |
| pytest-code-fix-existing-suite-regression | 既有 code-fix 车道套件回归（tasks 3.2：tests/test_code_fix.py 补 defer 路径不变/兜底入档现状一致/日志留痕断言后全绿；本 SPEC 改写 _run_batch_created 真冲突分支 core/code_fix.py:4424-4460，既有合回冲突/现场即弃/defer 语义锁必须全过）：python3 -m pytest tests/test_code_fix.py -q 全部通过（-q 汇总行含 passed）。 | pass | 0/2 | - |
| pytest-code-fix-related-lanes-regression | 相关 code-fix 车道套件回归：wip 预检（test_code_fix_wip_precheck.py，defer/预检路径）、条级进度（test_code_fix_item_level_progress.py）、手动触发（test_code_fix_manual_trigger.py）、既有 salvage 机制（test_code_fix_salvage.py：api_timeout/stranded 救回与本 SPEC 救回同函数邻域）、亲和性聚批（test_code_fix_affinity_batching.py，本场景批构造依赖其同目录聚批语义）、启动阶段可见性（test_code_fix_startup_stage_visibility.py）全部通过——救回插入不得外溢扰动相邻车道。 | pass | 0/2 | - |
| contract-codefix-agent-items-body-annotation | commit 契约增强落盘（tasks 2.2）：agents/code-fix.md 的 commit 契约补 body 的 item_id 结构化标注约定（items: 前缀清单——该锚今天不在文件中，落地后才出现；probe-salvage-cherry-pick-partial-recovery 的组归属解析即消费此约定）；既有「逐组提交或收尾一次提交」弹性表述保留（item_id 引用仍在场）。 | pass | 0/3 | - |

## 本轮场景集变更

当前稳定场景集共 9 个（第 1 轮）。

- 首轮写入 9 个场景

