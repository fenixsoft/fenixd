# 验证报告：evo-inflight-spec-amendment-watch

> ⚠️ 本报告由框架于 2026-10-02T21:20:27Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-10-02T21:20:26.976193+00:00+run-result@mtime1790976027014460229

## 结论：✅ 通过（verified）

**状态：verified — 17/17 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 17/17 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 17 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 4.03M |
| 本链增量 Token（输出） | 0.04M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| probe-detect-single-source-logic | 独立探针（不经实现方测试文件，直测两入口共用的单源逻辑）：自建夹具仓库（merge-base 后主树提交 spec 目录修订 / 无修订 / 分支消失三变体），直调 core/worktree_manager/mergeback.py 的模块级 detect_spec_amended_inflight 与 spec_amendment_fingerprint——命中返回短哈希列表、无修订与分支不存在返回空列表（静默跳过）、指纹对提交集合顺序不敏感且集合变化即变、MergeConflictInfo.amended_inflight 默认空列表（旧构造点兼容）。出处：core/worktree_manager/mergeback.py:86,138；core/worktree_manager/types.py:145,174 | pass | 0/8 | - |
| mb-amended-conflict-alerts-and-attaches | merge-back 主链相撞场景（spec 场景 2 的 merge-back 半边，任务 1.1）：复演 2026-10-02 cimbar 事故形态——夹具仓库在 merge-base 之后主树提交 spec 目录修订、分支勾选更新与主树改动语义冲突，merge_back_from_branch 仍由预演检出 rehearsed=True/has_semantic_conflict=True（冲突结局不变），merge_info.amended_inflight 携带修订提交短哈希列表，admin store 落恰好一条 spec_amendment_inflight 告警（severity=major、evidence 含修订短哈希与指纹）。出处：core/worktree_manager/mergeback.py:86,213-215,410；core/worktree_manager/types.py:174；tests/test_merge_back_spec_dir_guard.py:673（实测 28 例全绿） | pass | 0/2 | - |
| mb-amendment-hit-keeps-merge-semantics-and-no-fuse | 检测命中不改变 merge-back 结局与熔断记账（任务 1.2）：主树修订只落 spec 目录、分支未触该目录（不相撞变体）时照常合并成功（rehearsed/spec_dir_inflight/wip_gate_blocked 均否）——命中仅附情报，不改布尔返回、不入 _merge_fp/_merge_streak 熔断（对照 rehearsed=True 豁免先例）。出处：core/worktree_manager/mergeback.py:213-215；core/pm_engine/dispatch/queue.py:1853-1863；tests/test_merge_back_spec_dir_guard.py:705 | pass | 0/2 | - |
| mb-amendment-fingerprint-dedup-and-commit-set | 告警指纹语义（1.1/2.1 同源指纹单源）：同一修订集合的重复 merge-back 尝试不逐轮重复告警（指纹在途去重）；指纹按 spec+修订提交集合计算、提交集变化产生新指纹。出处：core/worktree_manager/mergeback.py:138；tests/test_merge_back_spec_dir_guard.py:695,752 | pass | 0/3 | - |
| mb-no-amendment-zero-disturbance | 无修订零扰动（spec 场景 3 的 merge-back 半边）：merge-base 之后主树 spec 目录无新提交时不发 spec_amendment_inflight 告警、merge_info.amended_inflight 保持空默认值（兼容旧 MergeConflictInfo 构造点），merge-back 行为与告警面完全不变。出处：core/worktree_manager/types.py:145,174；tests/test_merge_back_spec_dir_guard.py:722 | pass | 0/2 | - |
| mb-missing-branch-silent-skip | 实现分支不存在时检测静默跳过（merge-base 依赖实现分支存活的硬约束）：分支已合回清理/merge-base 失败 → 不报错、不告警、主链照常。出处：core/worktree_manager/mergeback.py:86,394-408；tests/test_merge_back_spec_dir_guard.py:741 | pass | 0/2 | - |
| repair-passthrough-carries-amendment | rehearsed 直通 repair 透传（任务 1.3，spec 场景 2）：merge 预演检出 spec 目录语义冲突且存在在飞修订时，_direct_rehearsed_to_repair 把 merge_info.amended_inflight 透传进 repair 派发上下文（conflict_summary.amended_inflight 携带修订提交列表）——repair 无须自行考古根因。出处：core/pm_engine/dispatch/repair_lane.py:86-88；tests/test_merge_back_spec_dir_guard.py:778 | pass | 0/2 | - |
| repair-prompt-carries-root-cause-section | repair prompt 根因段（任务 1.3）：conflict_summary 携带 amended_inflight 时 prompt_builder 增补「主树在飞修订根因（spec_amendment_inflight）」段（含修订提交列表），repair 派发 prompt 直接带根因。出处：core/agent_runner/prompt_builder.py:1489-1508；tests/test_merge_back_spec_dir_guard.py:793 | pass | 0/2 | - |
| repair-prompt-byte-identical-without-amendment | 回归点：无在飞修订时 repair prompt 逐字节不变——根因段注入仅在 amended_inflight 非空时发生，旧冲突路径的派发产物零漂移。出处：core/agent_runner/prompt_builder.py:1505；tests/test_merge_back_spec_dir_guard.py:811 | pass | 0/2 | - |
| admin-periodic-amendment-alert-one-cycle | 周期扫描入口（spec 场景 1，任务 2.1）：实现 run 在飞（implementing+分支锚点在案+run 活动）且主树 spec 目录有已提交修订时，_detect_spec_amendment_inflight 本轮扫描即产 spec_amendment_inflight 信号（severity=major、evidence 含修订短哈希与指纹、description 含相撞预警）；经 _detect 主扫描入口（周期巡检同路）同样成条——修订落地后一个扫描周期内告警，不必等 merge 时刻。出处：core/admin_monitor.py:2058,2887；tests/test_admin_monitor_spec_amendment.py:104,124 | pass | 0/3 | - |
| admin-amendment-fingerprint-dedup-and-refire | 周期入口指纹去重与再触发：同 spec+修订提交集合在下一扫描周期不重复成条（不逐轮轰炸）；主树又落新修订（提交集变化→新指纹）时允许再次成条，作相撞风险升级提醒。出处：core/admin_monitor.py:2887；core/worktree_manager/mergeback.py:138；tests/test_admin_monitor_spec_amendment.py:136,149 | pass | 0/3 | - |
| admin-silent-skip-without-inflight-run | 周期入口静默跳过四变体（spec 场景 3 的扫描半边）：无活跃 run、非 implementing 状态、分支锚点缺失、分支 git 消失四类情形均不检测不告警（run/分支不在飞静默跳过的硬约束）。出处：core/admin_monitor.py:2887；tests/test_admin_monitor_spec_amendment.py:169-209 | pass | 0/5 | - |
| admin-kind-registration-major-with-prescription | 告警 kind 注册与可消费性：spec_amendment_inflight 注册进周期扫描 kind 级别表（severity=major，对照 orphaned_state 同级）、处方文案指向「等实现收尾后在分支上补修订或经 repair 合并」，且属入库信号类型（admin store 可落库消费）。出处：core/admin_monitor.py:355,434,497；tests/test_admin_monitor_spec_amendment.py:211-243 | pass | 0/4 | - |
| regression-worktree-merge-guard | 回归（任务 3.3）：tests/test_worktree_merge_guard.py 全绿（实测 31 例，含 _wip_overlap_gate 用例）——本 SPEC 闸门序列头部的新检测不破坏既有 WIP/未提交守卫语义。出处：core/worktree_manager/mergeback.py:213-215；tests/test_worktree_merge_guard.py | pass | 0/2 | - |
| regression-merge-tree-rehearsal | 回归（任务 3.3）：tests/test_merge_tree_rehearsal.py 全绿（实测 15 例）——merge 预演语义未被在飞修订检测改动（proposal 非目标：不改 _rehearse_merge_from_branch 预演语义）。出处：tests/test_merge_tree_rehearsal.py；spec/changes/evo-inflight-spec-amendment-watch/proposal.md:15 | pass | 0/2 | - |
| regression-mergeback-repair-lane | 回归（任务 3.3）：tests/test_mergeback_repair_lane.py 全绿（实测 26 例）——repair 车道既有解决策略与 conflict_summary 透传零漂移。出处：core/pm_engine/dispatch/repair_lane.py:86-88；tests/test_mergeback_repair_lane.py | pass | 0/2 | - |
| spec-two-test-files-full-green | 本 SPEC 两测试文件合跑全绿收口（实测 28+11=39 例）：merge-back 侧扩展守卫与周期扫描新文件无相互干扰、无收集错误——任务 3.1/3.2 交付面整体可用。出处：tests/test_merge_back_spec_dir_guard.py:624-827；tests/test_admin_monitor_spec_amendment.py | pass | 0/2 | - |

## 本轮场景集变更

当前稳定场景集共 17 个（第 1 轮）。

- 首轮写入 17 个场景

