# 验证报告：evo-stray-first-sight-prevention

> ⚠️ 本报告由框架于 2026-10-12T19:10:13Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-10-12T19:10:12.367633+00:00+run-result@mtime1791832212399059803

## 结论：✅ 通过（verified）

**状态：verified — 12/12 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 12/12 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 12 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 3.07M |
| 本链增量 Token（输出） | 0.05M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| fsight-first-sight-new-dir-hint | 主树出现新的未跟踪产物目录集合（登记表无指纹、无 ignore 覆盖）时，盘点发出一次 info 级首现提示信号 kind=maintree_untracked_stray_first_sight，evidence 含目录清单、总体积与预防性 .gitignore 条目草案；盘点零触碰（git status 前后逐字节一致）。探针以进程内真实 git 仓夹具驱动 MainTreeStrayWipSweeper.sweep（装配先例 tests/test_maintree_stray_wip_sweep.py:115），断言读 AdminStore(.fenix/admin_alerts.json, core/admin_store.py:199)。出处：core/worktree_manager/stray_wip.py:738（_untracked_signal，首现判定须插在 :796 below_threshold 早退之前）、:1344（同族 AdminStore.append 告警写入先例） | pass | 0/9 | - |
| fsight-below-threshold-still-hints | 低于 entry 阈值（5）的首现目录集合同样发出首现提示（below_threshold 早退不适用于首现判定），且不启动升级时钟——登记表条目 escalated_signal_at 保持空、无 escalated 告警落盘，盘点返回 status=below-threshold 形态不变。出处：core/worktree_manager/stray_wip.py:769/796 | pass | 0/7 | - |
| fsight-same-dir-no-rehint | 同一目录集合连续两轮盘点只发一次首现提示——首现即写登记表（first_seen/指纹），同目录不重复提示。出处：core/worktree_manager/stray_wip.py:794（按当前指纹集复位/去重） | pass | 0/4 | - |
| fsight-reset-then-reappear-rehints | 目录消失触发登记表复位后再现，视为新首现再次提示：第一轮盘点发提示→删除目录再盘点（不提示）→同内容重建目录再盘点→第二次提示（复发场景正是提示价值所在）。出处：core/worktree_manager/stray_wip.py:1001（_reset_untracked_registry_absent） | pass | 0/4 | - |
| fsight-gitignore-covered-no-hint | 产物路径已被 .gitignore 规则覆盖的目录不计首现、不发提示（check-ignore 豁免，porcelain 亦不列 ignored，untracked 计数应为 0）。出处：core/worktree_manager/stray_wip.py:686-696（_untracked_stray_entries 豁免①②）、design.md check-ignore 批量判定条款 | pass | 0/5 | - |
| fsight-escalation-path-nonregression | 升级路径不回归：超 entry 阈值（6 文件）且体积超阈值（配置调小 maintree_untracked_stray_size_threshold_bytes=1）的目录集合首轮盘点同时发出首现提示与 maintree_untracked_stray_escalated 升级告警——首现提示的存在不改变升级判定（体积路径独立于滞留时长，双路径每轮独立评估）。出处：core/worktree_manager/stray_wip.py:832-843（双档升级判定）、core/admin_monitor.py:570（escalated 收录 STORED） | pass | 0/5 | - |
| fsight-not-auto-stored-signal | 首现提示 kind=maintree_untracked_stray_first_sight MUST NOT 收录 STORED_SIGNAL_TYPES（不自动唤起 admin 处置 run）；sanity 双锚：escalated 在收录内（证明导入的是真实常量）、untracked stale 不在收录内（既有 info 不收录语义未回归）。出处：core/admin_monitor.py:507（STORED_SIGNAL_TYPES）、core/worktree_manager/stray_wip.py:1349（info 不收录禁令） | pass | 0/4 | - |
| fsight-restart-no-rehint | 首现登记持久化跨 daemon 重启不重复提示：实例 A 盘点发出提示后，新建实例 B（模拟重启、盘点开始时从 .fenix/stray_untracked_registry.json 载入注册表）再盘点，仍只一条提示；持久化文件在首轮盘点后已落盘。出处：core/worktree_manager/stray_wip.py:98（UNTRACKED_REGISTRY_RELPATH）/1014（_load_untracked_registry） | pass | 0/6 | - |
| fsight-implementer-checklist-disk-coverage | 交付契约（agents/implementer.md）收尾检查清单含 MUST 级落盘覆盖检查点：交付引入运行时落盘路径（日志/dump/产物目录）且落在仓库树内时，同提交追加对应 .gitignore 覆盖或将默认落盘路径移出仓库树，提交前以 git status 自查零 untracked 产物。出处：specs/stray-first-sight-prevention/spec.md「交付落盘覆盖检查点」Requirement、tasks.md 2.1、agents/implementer.md | pass | 0/5 | - |
| fsight-new-test-file-passes | 交付测试文件 tests/test_stray_first_sight_prevention.py 全量通过（覆盖任务 3.1：首现触发、低于阈值也提示、gitignore 已覆盖不提示、同目录仅一次、复位后再现重提示、跨重启不重复提示）。出处：tasks.md 3.1 | pass | 0/2 | - |
| fsight-existing-stray-tests-nonregression | 非回归（任务 3.2）：既有散件盘点测试全量通过——test_maintree_stray_wip_sweep.py 钉住 tracked/untracked 双流宽限/升级/复位语义，test_stray_untracked_session_attribution.py 钉住越阈归因与低于阈值早退，test_stray_whitelist_untracked.py 钉住排除集名单；首现插入不破坏既有 stale/escalated 语义与登记表复位行为。出处：tasks.md 3.2、tests/test_maintree_stray_wip_sweep.py | pass | 0/2 | - |
| fsight-loose-file-no-dir-hint | 边界：根目录散落单文件（非目录型产物集合）不触发首现提示，但仍按既有散件口径被盘点计数与建档（不被首现逻辑吞掉）。出处：proposal.md「目录型产物集合」触发定义、core/worktree_manager/stray_wip.py:640（_untracked_stray_entries entry 级清单） | pass | 0/5 | - |
