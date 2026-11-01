# 验证报告：fix-legacy-ghost-spec-entry-reclaim

> ⚠️ 本报告由框架于 2026-11-01T02:15:13Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-11-01T02:15:11.980000+00:00+run-result@mtime1793499312020522118

## 结论：✅ 通过（verified）

**状态：verified — 10/10 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 10/10 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 10 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 0.12M |
| 本链增量 Token（输出） | 0.05M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| ghost-unit-suite-targeted | 定向单测验收（tasks 3.1-3.4/4.1）：运行 tests/test_spec_content_integrity.py 全量幽灵清退单测——指纹三条件 AND 真值表（含各自翻转不命中）、新鲜度 30 分钟窗常量、blocked+frozen 冻结不豁免、物化 proposal 不命中、非法名跳过、清退 remove_spec/台账 kind=ghost-entry-reclaimed/聚合告警单条含全清单、幂等重放零重复告警、开关 off 全跳过；断言 61 passed 与 18 条关键用例 PASSED 行（输出形态已实测取证，无 parametrize 后缀）。出处：core/pm_engine/spec_integrity.py:386 detect_ghost_entries / :464 reclaim_ghost_entries / :70-73 常量、tests/test_spec_content_integrity.py:743-999 | pass | 0/20 | - |
| ghost-constants-contract | 常量契约直读（tasks 1.2）：从生产模块 core.pm_engine.spec_integrity 直读幽灵清退四常量——新鲜度豁免窗 GHOST_ENTRY_FRESHNESS_MINUTES=30、台账 kind=ghost-entry-reclaimed、聚合告警 signal_type=ghost_entry_reclaimed、台账文件名 ghost_reclaim_ledger.jsonl，写侧与测试断言同源防字面量漂移（输出形态已实测取证）。出处：core/pm_engine/spec_integrity.py:70-73（对齐 IMPL_RUN_BUDGET_USED_FIELD 家族模块级大写常量惯例） | pass | 0/5 | - |
| twin-dryrun-fingerprint-hit | 孪生幽灵条目判定 dry-run（tasks 4.2 验收偏差注解替代场景链——按注解替代方式出题，不按字面实盘清退出题）：沙箱以孪生 recorded 指纹形态重建条目 fix-planner-scenario-entry-schema-selfcheck（blocked+frozen、created=2026-10-31T16:41:13.457749+00:00、spec/changes/<twin>/ 目录缺失、git 全历史零提交——recorded 形态锚定主树升级记录考古），另注册本条目 fix-legacy-ghost-spec-entry-reclaim（已物化 proposal.md 的最小成文形态）作对照；跑生产判定函数 detect_ghost_entries 断言命中恰含孪生、本条目不命中、命中项含 created/age_minutes/dir_evidence/git_evidence 证据、dry-run 只读零副作用（STATE 双条目原样保留、无台账、无告警）。出处：core/pm_engine/spec_integrity.py:386-462 detect_ghost_entries、:147 git_path_has_commits、:91 spec_has_content | pass | 0/12 | - |
| ghost-reclaim-end-to-end | 幽灵条目清退端到端留痕（spec Requirement 1 场景「孪生幽灵条目被清退」+ tasks 1.3）：真实 git 沙箱注册两条过新鲜度窗的幽灵条目（目录缺失+git 零提交），跑生产 reclaim_ghost_entries——断言 STATE 两条目原子移除、逐条台账 .fenix/ghost_reclaim_ledger.jsonl 落 kind=ghost-entry-reclaimed 且每条含 created/age_minutes/dir_probe/git_log 证据（git_log 含「零提交」）、聚合告警恰一条（severity=major）且 description 同时含两条目、evidence 含「零提交」与台账文件名；另以 file_exists/file_content 直证台账落盘。出处：core/pm_engine/spec_integrity.py:464-545 reclaim_ghost_entries/_append_ghost_reclaim_ledger、:547-613 _send_ghost_reclaim_alert、core/state_machine.py:2777 remove_spec | pass | 0/20 | - |
| ghost-check-blockers-hook | check_blockers 挂点接入（tasks 2.1，启动回填期首轮 full_scan 与周期扫描共经此咽喉）：沙箱注册一条幽灵条目+一条物化 tasks.md 的正常条目，调生产 check_blockers——断言先清退后扫描（幽灵条目被 remove_spec 移除且台账落 1 条含该条目，而非走 spec_content_missing 冻结路径）、正常条目原样保留且 status 保持 drafted、聚合告警恰一条含幽灵条目名。出处：core/pm_engine/engine.py:4114-4122（check_blockers 先于本轮 blocker 扫描调用对账）、:4757-4765 门面 | pass | 0/8 | - |
| ghost-reclaim-idempotent-replay | 幂等重放（spec Requirement 2 场景「幂等重放」+ tasks 3.4）：沙箱注册一条幽灵条目后连续两轮生产 reclaim_ghost_entries——第一轮清退 1 条且 alerted=true；第二轮零清退、alerted=false、聚合告警数仍为 1（同指纹未处理告警在场不重复）、台账仍 1 条、STATE 条目保持已移除。出处：core/pm_engine/spec_integrity.py:547-567 防重（对齐 check_spec_content_missing 的 full_scan 未处理告警先例 :253）、:489-496 零命中空转分支 | pass | 0/8 | - |
| ghost-gate-config-off | 配置开关零副作用（spec Requirement 2 场景「开关关闭时零副作用」+ tasks 2.2）：同一沙箱两阶段对比——off 阶段 PMEngine 配置 gates.ghost_entry_reclaim=false，reclaim_ghost_entries 返回 enabled=false 且零清退、STATE 条目原样保留、无台账文件、无聚合告警，check_blockers 挂点同样被短路（条目仍在场）；on 阶段（缺省配置无 gates 键=默认 on，另验默认开启语义）同一幽灵条目被清退——注 off 态 check_blockers 的 spec_content_missing 闸门可能已把无目录条目冻结为 blocked+frozen，on 轮仍命中即同时实证「冻结不豁免」（design D3）。off 态快照先于 on 轮采样，防交叉污染。出处：core/pm_engine/spec_integrity.py:477-484 开关短路、core/pm_engine/engine.py:4757-4765 门面（ConfigLoader 点号键读取） | pass | 0/12 | - |
| ghost-normal-entries-zero-impact | 正常条目零影响回归防线（spec Requirement 1 场景「有实质内容的条目不命中」「有 git 历史的条目不命中」「新注册条目豁免」+ design 回归防线）：沙箱一次注册五种不命中形态——物化 proposal.md（arbiter 7f7ee45e2 范式）、曾立项提交后目录被误删（git 历史仍在）、新注册不足 30 分钟（created=now）、终态 pushed 豁免、blocked+frozen 但有实质内容——跑生产 reclaim_ghost_entries 断言命中/跳过/告警/台账全零，五条目操作前后 STATE 键集合与各 status 完全不变（操作前 vs 操作后回归对比）。出处：core/pm_engine/spec_integrity.py:386-462 判定序（终态豁免/条件 1/条件 3/条件 2 逐条短路）、design.md 回归防线节 | pass | 0/13 | - |
| ghost-unsafe-name-skip-alert | 非法路径成分名保守跳过并告警（spec Requirement 2「spec 名含非法路径成分的条目 SHALL 保守跳过并告警、SHALL NOT 清退」+ tasks 1.1/3.2）：沙箱以 STATE 读侧注入「../evil」形态条目（STATE.md 人工可编辑数据源防越界语义，与单测 patch read_all 同构），跑生产 detect/reclaim——断言不进命中清单、另入跳过清单、绝不清退（无台账文件）、仍产出恰一条聚合告警且 description 含该非法名待人工处置。出处：core/pm_engine/spec_integrity.py:83-88 _is_safe_spec_name、:427-431 跳过分支、:583-586 告警跳过条目行 | pass | 0/9 | - |
| ghost-regression-recovery-lifecycle | 定向回归：正常流转条目零影响（tasks 4.3）：运行 tests/test_pm_recovery.py + tests/test_run_lifecycle_governance.py 全量回归（check_blockers 正常恢复链、run 生命周期治理），断言 96 passed 与两文件各自关键用例 PASSED 行（输出形态已实测取证，无 parametrize 后缀），证明清退通道接入未改变任何正常流转语义。出处：core/pm_engine/engine.py:4107-4122 check_blockers 挂点接入点、tasks.md 4.3 | pass | 0/5 | - |

## 本轮场景集变更

当前稳定场景集共 10 个（第 1 轮）。

- 首轮写入 10 个场景

