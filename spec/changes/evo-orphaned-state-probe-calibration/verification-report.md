# 验证报告：evo-orphaned-state-probe-calibration

> ⚠️ 本报告由框架于 2026-09-17T21:31:19Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-09-17T21:31:18.984728+00:00

## 结论：✅ 通过（verified）

**状态：verified — 9/9 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 9/9 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 9 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 1.94M |
| 本链增量 Token（输出） | 0.03M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| repair-active-run-suppresses-undriven | 功能点1.3 正向：repair- 前缀 run 文件 mtime 在宽限窗（ORPHANED_RUN_GRACE_SECONDS=120s）内时，_has_recent_spec_run（经 _spec_from_run_id 用真源全量前缀归一）识别活跃，spec_is_undriven 条件①不再对 repair 通道恒假；端到端 _detect_orphaned_state 在活跃 repair run 期不产生 orphaned_state 信号（2026-09-15 活跃 repair run 被判无驱动误报回归）。断言来源：tests/test_admin.py TestOrphanedRepairProbe（本 SPEC 新增用例 test_active_repair_run_suppresses_undriven / test_orphaned_detection_skips_active_repair）；实现落点 core/admin_monitor.py _spec_from_run_id（:2443）与 _has_recent_spec_run。 | pass | 0/3 | - |
| repair-inactive-run-still-undriven | 功能点1.3 反向/异常路径：repair- run 文件 mtime 超宽限窗且无存活进程、无待派发时仍判孤儿（spec_is_undriven 返回 True）——修复失明的同时不引入漏报（覆盖规则：陈旧 repair run 必须仍被孤儿判定捕获，三条件结构不变）。断言来源：tests/test_admin.py TestOrphanedRepairProbe::test_inactive_repair_run_still_undriven；实现落点 core/admin_monitor.py spec_is_undriven 与 _has_recent_spec_run。 | pass | 0/2 | - |
| spec-from-run-id-all-prefixes | 功能点1.1：_spec_from_run_id 归一改用真源全量前缀 core/agent_runner/run_files.py:RUN_ID_AGENT_PREFIXES（顺序与真源一致、长前缀在前、含 repair-），repair-/impl-/verify-/planner-plan-/planner-judge-/spec-review-/admin-/dispute-judge- 全部 run 前缀连同 attempt(-a<n>) 与瞬态重试(-r<n>) 后缀均能还原 spec 名；活跃度归属视角下裸 planner-/test- 前缀亦可还原（失败计数口径不受影响，见 failure-prefix-subset-locked）。断言来源：tests/test_admin.py TestSpecFromRunIdAllPrefixes（新增 test_all_agent_prefixes_resolve / test_full_truth_table_includes_bare_planner_and_test）。 | pass | 0/3 | - |
| pgrep-repair-worktree-probe | 功能点1.4：_pgrep_live_worktree（core/admin_monitor.py:345）模式集补入 repair（匹配 repair-<spec>-，worktree 目录名 core/worktree_manager.py:3479），条件②对 repair worktree 下 claude 进程不再失明——修复 2026-09-15 误报根因②；repair-<spec>-<ts> worktree 存在活跃进程时判定存活。断言来源：tests/test_admin.py TestPgrepRepairProbe（test_pattern_set_includes_repair / test_repair_process_judged_live，pgrep 调用打桩）；孪生同步见 event-bus-pgrep-single-source。 | pass | 0/3 | - |
| admin-failure-evidence-four-piece | 功能点1.5：run_administrator（core/agent_runner/maintenance_runs.py:52）非零退出补可定位失败证据四件套进 AdminDisposition.failure_evidence 独立字段——原始 stderr 末 N 行截断 4KB（含被 error-attribution-denoise 丢弃的 [claude-code: 行）/ exit_code / run 产物 provider_marker 事件的 provider·model / run 末 3 条带 timestamp 事件时间线（跳过无 timestamp 的 error/stderr/result/provider_marker/system 终态旁路事件）；error 归因文本仍为降噪后形态（原始 stderr 不回填，error-attribution-denoise D5 语义不变）；成功路径 failure_evidence 为空 dict。断言来源：tests/test_agent_runner.py TestRunAdministratorFailureEvidence（test_failure_evidence_assembled_error_denoised / test_failure_evidence_absent_on_success）；实现落点 core/agent_runner/maintenance_runs.py _admin_failure_evidence。 | pass | 0/3 | - |
| sentinel-prefix-tests-stay-green | 功能点1.2/2.6 兼容回归：保留 _RUN_PREFIXES 常量名并补入 repair- 后，既有同源哨测试无需改动保持绿（实跑确认，不得凭推断）——tests/test_dashboard_data.py:585 TestRunIdPrefixSingleSource::test_admin_monitor_prefixes_subset_of_canonical（失败计数前缀必须仍是真源子集，防删名/ImportError 裂口）、tests/test_deliverable_declaration_triage.py:422 test_admin_monitor_prefix_includes_dispute_judge、:449 test_prefixes_same_source_sync（两处前缀表同源互指）。 | pass | 0/4 | - |
| event-bus-pgrep-single-source | 功能点1.4 孪生同步：core/event_bus.py:448 EventBus._pgrep_live_worktree 由「同语义孪生」改为复用 core/admin_monitor._pgrep_live_worktree 同一函数（:464 惰性 from-import），恢复链与检测链同一口径——修掉 admin_monitor 曾补 repair- 而孪生遗漏造成的两链漂移隐患；对不存在 spec 的探测返回 False（不误报活跃）。运行侧断言 EventBus 探测对未知 spec 返回 False，源码侧 lock 复用同一函数（file_content）。实现落点 core/event_bus.py:448-467。 | pass | 0/3 | - |
| alert-lifecycle-stage-semantics-doc | 功能点1.6：告警生命周期阶段语义文档化——orphaned_state 的 signal / disposition pending / disposition failed / escalated 属同一信号不同阶段，阶段差异由 description 与处置记录 status/result 区分，不得声称同一信号仅一条记录（冷却 _throttled 过期后同信号重新成条属既有节流语义）；SIGNAL_RECOMMENDATION['orphaned_state'] 建议文案与 _detect_orphaned_state 告警 description 均已落该语义。运行侧断言建议文案含 signal 阶段与 pending/failed/escalated 阶段，源码侧 file_content lock 两处文案。实现落点 core/admin_monitor.py:273 与 :1115。 | pass | 0/4 | - |
| failure-prefix-subset-locked | 功能点1.2（design 1 拆分）：失败计数前缀子集保留独立常量且保留名 _RUN_PREFIXES（tests/test_dashboard_data.py:586、tests/test_deliverable_declaration_triage.py:423,450 直接 import，改名/删除即 ImportError），子集补入 repair-、裸 planner-/test- 不计；_detect_repeated_failures 显式按子集还原 spec，不随归一默认全量前缀扩大 3 次/30 分钟计数口径——planner-/test- 失败 run 不得纳入、repair- 失败 run 必须纳入。断言来源：tests/test_admin.py TestFailurePrefixSubset（test_subset_boundary / test_repeated_failures_excludes_bare_planner_and_test / test_repeated_failures_counts_repair）；实现落点 core/admin_monitor.py:284 _RUN_PREFIXES 与 :825 _detect_repeated_failures。 | pass | 0/4 | - |

## 本轮场景集变更

当前稳定场景集共 9 个（第 1 轮）。

- 首轮写入 9 个场景

