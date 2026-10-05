# 验证报告：evo-mergeback-archive-residue-selfheal

> ⚠️ 本报告由框架于 2026-10-05T19:21:08Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-10-05T19:21:08.080689+00:00+run-result@mtime1791228068106761138

## 结论：✅ 通过（verified）

**状态：verified — 11/11 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 11/11 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 11 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 5.36M |
| 本链增量 Token（输出） | 0.10M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| selfheal-pytest-suite-green | 交付测试套件全量绿（tasks 2.1 全部 9 项覆盖的套件级验证）：tests/test_mergeback_archive_residue_selfheal.py 存在且 pytest -v 全过。断言先 file_exists（交付物锚），再跑套件断 exit_code=0 与 pytest 通过汇总行。出处：spec/changes/evo-mergeback-archive-residue-selfheal/tasks.md Deliverables。 | pass | 0/3 | - |
| selfheal-residue-criteria-probe | 残留判据层三变体（spec 需求 1 只读判据；tasks 1.1 共享辅助抽取落点）：临时 git 夹具驱动 PMEngine._archive_move_residue（core/pm_engine/engine.py:2941，实现后按 design 委托 core/archive_commit.py 共享辅助）——(1) 同 spec 两侧成对残留 found=True 且 spec_names/residue_paths 精确等于删除侧+archive 侧两路径；(2) 混合脏文件时 spec 外路径不进清单；(3) 干净仓库 found=False。另断言共享辅助已落 core/archive_commit.py（tasks 1.1 交付锚）。 | pass | 0/9 | - |
| selfheal-hit-commit-replay-success | 自愈命中主路径（spec 验收 1；spec 需求 2）：归档半程主树（spec/changes/myfeat 删除态 + spec/archive/2026-10-06-myfeat 未跟踪成对）+ 熔断出口命中（Dispatcher stub 驱动 _defer_merge_back，core/pm_engine/dispatch/queue.py:2559，窗口超限经 first_at=1h 前触发）→ 框架代为补提交归档收尾（[fenix] archive: 消息含 spec 名）→ 立即重放 merge-back（stub 成功）→ 清理 _merge_retry_* 记账 → 零 admin 告警零 Timer 排程。出处：spec/changes/evo-mergeback-archive-residue-selfheal/design.md「自愈评估挂点/周期消费者」；装置锚 core/pm_engine/dispatch/queue.py:2559 _defer_merge_back、core/pm_engine/dispatch/rollback.py:553、core/pm_engine/engine.py:2941 | pass | 0/9 | - |
| selfheal-single-side-changes-only-no-selfheal | 仅 changes 删除态的单侧半提交形态不授权自愈（spec 需求 1：仅单侧半提交不授权自动收尾，落回既有熔断）：夹具只有 spec/changes/solo 删除态（archive 侧已提交形态），驱动 _defer_merge_back 熔断出口 → 无补提交、走 _report_mergeback_spec_dir_inflight_stuck（core/pm_engine/dispatch/rollback.py:553）且告警 evidence 增补自愈评估摘要（tasks 1.2：判据命中与否留痕）、重放未被触发、残留保持原状等人工。 | pass | 0/7 | - |
| selfheal-single-side-archive-only-no-selfheal | 仅 archive 新增侧的单侧形态不授权自愈（spec 需求 1 对称变体）：夹具只有 spec/archive/2026-10-06-solo2 未跟踪文件（changes 删除侧不存在），驱动 _defer_merge_back 熔断出口 → 无补提交、熔断告警 + evidence 自愈评估摘要、重放未触发、archive 侧残留保持未跟踪等人工。 | pass | 0/7 | - |
| selfheal-mixed-source-wip-veto | 混合源码 WIP 否决自愈（spec 需求 1：任一脏文件不落在 spec/changes 与 spec/archive 两类路径即判非归档残留；spec 验收 2：源码 WIP 行为与现状一致顺延→熔断，绝不自动提交源码路径）：夹具=成对归档残留 + spec 外未跟踪 core/wip_scratch.py → 不补提交、WIP 文件保持未跟踪、熔断告警发出且 evidence 载明评估结果。出处：spec/changes/evo-mergeback-archive-residue-selfheal/design.md「自愈评估挂点/周期消费者」；装置锚 core/pm_engine/dispatch/queue.py:2559 _defer_merge_back、core/pm_engine/dispatch/rollback.py:553、core/pm_engine/engine.py:2941 | pass | 0/8 | - |
| selfheal-add-precise-paths-other-spec-draft-untouched | 补提交 add 仅含精确残留路径（spec 需求 2：MUST NOT 退回 git add -- spec 或双前缀通配，防卷入其它 spec 在途草案——code-review 88209fa06ce0 回归点）：夹具=成对归档残留（narrowspec）+ 其它 spec 在途草案（spec/changes/otherdraft/note.md 未提交修改）→ 自愈补提交后 git show 文件清单只含 narrowspec 残留路径，otherdraft 草案仍以未提交修改态留在工作区。（judge 修复：夹具草案提交改精确 add 并后置残留制造，防 add -A 吞掉成对残留毁场景前提；status_lines 去整体 strip 保留 porcelain 前导格式） | pass | 0/7 | - |
| selfheal-consumer-picks-up-overdue-pending | 周期消费者接手与守卫（spec 需求 4；tasks 1.3；spec 验收 3 Timer 链缺失接手）：驱动 _recheck_inflight_deferred_merges（design.md 锁名，仿 _recheck_wip_deferred_merges core/pm_engine/dispatch/queue.py:2870 范式，120 秒节拍）——已超熔断阈值（count≥max_rounds 或窗口超限，与 queue.py:2610 同判式）且仍 _merge_retry_pending 且无 _wip_gate_deferred 的条目 A 被接手 merge-only 重试；未超阈值条目 B（Timer 链存活车道，防双驱动）、带 _wip_gate_deferred 条目 C（WIP 消费者车道）、非 pending 条目 D 三类均被跳过。 | pass | 0/3 | - |
| selfheal-consumer-once-cap-and-stuck-alert | 消费者接手重试至多一次 + 失败维持熔断告警去重幂等（spec 需求 4：每条目接手重试至多一次、失败维持既有熔断告警与人工通道，去重对齐 _spec_dir_inflight_stuck_notified core/pm_engine/dispatch/queue.py:2617 范式）：两条超阈值 pending 条目接手重试均失败（recorder 返回 False）→ 各得一条 mergeback_spec_dir_inflight_stuck 告警；第二拍扫描不再二次接手（replay 计数不增长）、告警零增长（去重幂等）。 | pass | 0/5 | - |
| selfheal-attempt-once-cap | 单条 merge-back 自动收尾至多尝试一次（spec 需求 5：进程内集合记账对齐 queue.py:2617 范式，避免与归档自身重试互相踩踏）：夹具 pre-commit hook 恒败并计数——第一次驱动熔断出口：判据命中 → git add → git commit 触发 hook（计数 1）失败 → 走熔断告警 + evidence 载明失败原因；第二次驱动同 spec：不再发起第二次提交尝试（hook 计数仍 1）→ 告警去重不刷屏、无提交落库、残留保持原状。 | pass | 0/6 | - |
| selfheal-existing-lanes-regression | 既有顺延/WIP 车道零回归（spec 非目标：不改真内容冲突车道与既有顺延语义；需求 4 明确未超阈值条目仍由 60 秒 Timer 链驱动）：既有顺延守卫套件（tests/test_merge_back_spec_dir_guard.py，28 例）与 WIP 协调套件（tests/test_mergeback_wip_coordination.py，22 例）全绿——新自愈评估与周期消费者不得改变既有 _defer_merge_back 顺延记账、熔断降级、WIP 双层守卫行为。 | pass | 0/2 | - |
