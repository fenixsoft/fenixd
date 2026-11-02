# 验证报告：evo-instant-fail-storm-alert-closeout

> ⚠️ 本报告由框架于 2026-10-30T13:25:44Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-10-30T13:25:42.518525+00:00+run-result@mtime1793366742573759123

## 结论：✅ 通过（verified）

**状态：verified — 8/8 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 8/8 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 8 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 0.40M |
| 本链增量 Token（输出） | 0.06M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| storm-registry-terminal-closeout-probe | 正向路径·instant_fail_storm 条件登记与 terminal-only 终态收口（R1.1/R2）：_SIGNAL_CONDITIONS 登记 instant_fail_storm→spec_delivered_adjudicated，DELIVERED_ADJUDICATED_TERMINAL_STATUSES=（done, pushed, archived）；build_trigger 产出该终态收口条件；pushed/done/archived 三终态均产出含「已到达终态 <status>」与「裁决完成（终态收口）」的 resolve_note，注记按 signal_type 中性泛化（storm 注记携带自身类型、不残留 legacy spec_delivered_no_content 硬编码文案，同条件族 no_content 注记仍携带自身类型；带 updated 的 spec 注记附状态变更时刻）；负例回归锚：ready（秒挂冷却期在途）与 blocked 不提前收口（防误挂 spec_terminal_or_unblocked 的结构性锚）、spec 不在状态表保持原状、handled 人工记录不被覆盖；BACKFILL_SIGNAL_TYPES 不含 instant_fail_storm——无 trigger 存量条目即使 backfill=True 也不经「非 blocked 即解除」路径收口（tasks 1.3 禁令），而回填注册表内 verify_fail_escalation 仍正常走存量回填注记；find_resolvable 混合批次只收终态 storm、不误伤冷却在途与未登记条目（存量收口守护路径不误伤在途合理待处理 escalation）。出处 core/alert_lifecycle.py:112-135（登记）、:52（终态口径）、:63（条件常量）、:66（BACKFILL_SIGNAL_TYPES）、:138-164（build_trigger/attach_trigger）、:403-424（终态收口与中性注记）、:411（非终态保持原状）、:396-397（回填注册表门）、:430-448（find_resolvable）、specs/alert-escalation-auto-resolve/spec.md R1.1/R2 | pass | 0/20 | - |
| storm-writepoint-inventory-probe | 正向路径·写入点 attach_trigger 埋点与自动收口消费闭环（R1.2）：_alert_instant_fail_storm（core/agent_runner/runner.py）在临时项目台账上触发一次风暴告警写入——落地恰好 1 条 kind=escalation/signal_type=instant_fail_storm/severity=major/handled=False 记录，entry 经写入点 attach_trigger 埋点携带 condition=spec_delivered_adjudicated 且 spec 绑定触发 spec，evidence 字段并入秒挂取证快照（stderr_tail=…; worktree[…]）；同 spec 15 分钟窗口内二次写入被 latest_signal 节流抑制（台账仍 1 条，重复冷却不刷屏）；交互闭环第二段：把落地告警交给 evaluate_alert 对已 pushed 的 spec 判定——携带写入点 trigger 的存量条目可被自动收口盘点消费，产出终态收口 resolve_note。出处 core/agent_runner/runner.py:8813-8869（写入点）、:8863（attach_trigger 埋点）、:8831（15 分钟节流）、:8837-8842（evidence 并入取证）、core/admin_store.py:953（latest_signal）、core/alert_lifecycle.py:403-424（收口判定）、specs/alert-escalation-auto-resolve/spec.md R1.2 | pass | 0/11 | - |
| storm-aging-full-ledger-probe | 正向路径·未处理 escalation 龄期盘点全量台账口径（R3.1）：创建窗口 [W0,W1] 外的超龄（30.0 小时）instant_fail_storm 未处理告警在空窗口下仍产出「超 24 小时未处理提醒: 1 条（全量台账口径）」注记——盘点对象集为全量未 handled 台账而非创建窗口过滤集（调度窗口 [last_run_at, now] 增量内明细按构造不可能含超 24 小时条目，复用窗口集会让提醒永不触发），明细行携带 [超24h] 未处理升级 [instant_fail_storm] spec=storm-spec 与已登记时长，置于「（窗口内无 admin 记录）」行之后；龄期盘点为纯报告文本：收集前后台账记录数不变（不写新告警、与 admin_monitor 节流闸零交互），同窗重复收集输出逐字一致（同日幂等）；交互流程第二阶段：窗口内新增 fresh 未处理条目后，窗口统计行「- 升级告警: 1 条（未处理 1 条）」口径不变（窗口明细不回归），龄期注记仍只计全量台账超龄条目、fresh（<24h）条目不进 [超24h] 明细。出处 core/self_review.py:248-249（阈值 24h/明细上限 5）、:252-281（全量台账盘点）、:291-310（注记渲染）、:2577-2585（全量 records 计算）、:2610-2627（窗口统计行与龄期注记独立追加）、:2623-2626（空窗口仍提醒）、design.md 目标 2、specs/alert-escalation-auto-resolve/spec.md R3.1 | pass | 0/11 | - |
| storm-aging-edge-boundary-probe | 异常路径与边界·龄期盘点跳过规则、24 小时阈值边界与空状态（R3.1）：已 handled 条目不再提醒（人工收口记录不重复提醒）；created 非法（not-a-ts）条目跳过不虚报；非 escalation kind 条目跳过；8 条超龄条目计数行「超 24 小时未处理提醒: 8 条（全量台账口径）」正确、明细按龄期降序排列（最老在前、最新殿后）且超 5 条截断为「…另有 3 条超龄条目未逐条展开」；≥48 小时条目龄期展示「N 天 M 小时」格式（216h→9 天 0 小时、50h→2 天 2 小时），<48h 保持一位小数小时（47.9h）；阈值边界：距 now 23h59m 不标注、24h 整点标注（≥24h 口径）；空状态：空台账仅产出「（窗口内无 admin 记录）」单行、无龄期段（零噪音）。出处 core/self_review.py:248-249、:268-281（handled/非 escalation/解析失败跳过、龄期降序）、:284-288（龄期人性化展示）、:302-310（逐条展开与截断）、specs/alert-escalation-auto-resolve/spec.md R3.1 | pass | 0/14 | - |
| storm-forensics-bounded-probe | 异常路径·秒挂死亡取证快照有界与全程容错（R3.2）：_instant_fail_forensics 对 5000 字符启动 stderr 尾部截断至 200 字符（stderr_tail= 前缀、总长受 _INSTANT_FAIL_FORENSICS_MAX_CHARS=600 上界约束）；worktree 快照对缺失路径降级「(worktree missing)」占位、对非 git 目录降级「(not a git worktree)」占位、拼接段带 worktree[ 包裹；空素材（空 stderr＋无 worktree）返回空串不写占位噪音；空 stderr 仍保留 worktree 快照段；500 字符 stderr＋快照的混合拼接仍受 600 上界约束；全路径容错不抛出——取证在秒挂计数临界区之外计算，失败不得阻断计数与冷却判定。出处 core/agent_runner/runner.py:8649-8652（上限 600）、:8654-8691（_worktree_state_snapshot 容错降级）、:8693-8710（_instant_fail_forensics 有界拼接）、:8747-8750（临界区外计算）、design.md 目标 3「取证快照有界，不落大对象」、specs/alert-escalation-auto-resolve/spec.md R3.2 | pass | 0/12 | - |
| storm-lifecycle-suite-regression | 回归点·交付物测试套件 tests/test_alert_lifecycle.py 全量通过（当前实现实测 46 passed）：TestInstantFailStormClosure 回归锚组（tests/test_alert_lifecycle.py:468，9 条用例）覆盖——注册表 terminal-only 登记（test_signal_condition_registered_terminal_only）、BACKFILL 排除（test_not_in_backfill_registry）、pushed 终态自动 resolved 留痕不删（test_terminal_spec_auto_resolves_with_note）、冷却中非终态不提前收口（test_cooldown_non_terminal_not_resolved_early，防误挂 unblocked 条件的负例回归锚）、存量无 trigger 条目不经回填收口且不误伤在途条目（test_legacy_triggerless_entry_not_backfilled / test_closeout_spares_inflight_escalations）、终态注记中性泛化（test_delivered_no_content_note_neutralized_for_storm_only）。出处 tests/test_alert_lifecycle.py:468、tasks.md 3.1 | pass | 0/9 | - |
| storm-writepoint-forensics-suite-regression | 正向路径·写入点埋点与取证落账测试套件 tests/test_instant_fail_cooldown_gate.py 全量通过（当前实现实测 28 passed）：TestInstantFailForensics 组（tests/test_instant_fail_cooldown_gate.py:543，5 条用例）覆盖——写入点 _alert_instant_fail_storm 对 entry 调 attach_trigger 埋点，新告警携带 spec_delivered_adjudicated 终态收口 trigger 可被自动收口盘点消费（R1.2，test_write_point_attaches_terminal_trigger）；风暴告警 evidence 字段并入取证快照（test_alert_evidence_carries_forensics）；取证有界（test_forensics_bounded）；取证失败不阻断计数（test_forensics_failure_does_not_block_counting）；last_forensics 随秒挂状态留存、末次死亡覆盖写（test_forensics_kept_on_state_entry）。出处 core/agent_runner/runner.py:8863（写入点 attach_trigger）、:8774-8777（last_forensics 状态留存）、tasks.md 1.2/2.2 | pass | 0/7 | - |
| storm-aging-suite-regression | 回归点·龄期盘点测试套件 tests/test_daily_self_review.py 全量通过（当前实现实测 76 passed）：TestUnhandledEscalationAging 组（tests/test_daily_self_review.py:1618，6 条用例）覆盖——窗口外超龄条目仍被标注（test_aged_entry_outside_window_still_annotated，空窗口场景）、未超 24h 不产龄期段（test_under_24h_no_aging_section）、窗口统计行口径不变且未处理明细不回归（test_window_stats_unchanged_and_detail_not_regressed）、handled/畸形 created 跳过（test_handled_and_malformed_created_skipped）、收集不写新记录（test_collection_writes_no_new_records）、fixture 项目龄期条目 [fixture] 标注且不计待办（test_fixture_aged_entries_annotated_not_counted，alert-noise-governance 4.1 口径兼容）。出处 tests/test_daily_self_review.py:1618、tasks.md 2.1/3.2 | pass | 0/8 | - |

## 本轮场景集变更

当前稳定场景集共 8 个（第 1 轮）。

- 首轮写入 8 个场景

