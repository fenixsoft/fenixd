# 验证报告：evo-spec-changes-archive-drain

> ⚠️ 本报告由框架于 2026-10-30T13:03:54Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-10-30T13:03:52.865271+00:00+run-result@mtime1793365432923728569

## 结论：✅ 通过（verified）

**状态：verified — 10/10 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 10/10 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 10 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 0.17M |
| 本链增量 Token（输出） | 0.05M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| drain-pytest-new-suite | 运行本 SPEC 交付的新增测试套件 tests/test_spec_archive_drain.py（tasks.md 交付物 kind:new），期望退出码 0 且全部用例通过（-v 输出摘要行含 passed；不并列 -q 以免 PASSED 行被静默）。出处：spec/changes/evo-spec-changes-archive-drain/tasks.md Deliverables、core/verify_engine/cli_assertions.py（output_match 为子串包含语义） | pass | 0/3 | - |
| r1-saturation-drain-50-50 | R1 阈值饱和排水：夹具 50 个终态目录 + auto_threshold=50（计数恰等于阈值，旧逻辑「>阈值」恒不触发），调用 auto_archive_check 后应改为「>=即触发」并单轮排水至阈值下——恰好归档 updated 最旧的 1 条（50→49，spec.md 4.1 的 50→49 形态），updated 次旧/最新的目录保留；STATE 条目迁出清单 archived_by=auto；24h 内二次调用无新增归档、也无重复盘点信号（无新增含目录名的日志行）。出处：specs/spec-archive-drain/spec.md R1、core/dashboard/data/spec_archive.py:651、core/config.py:3572（effective_auto_archive_threshold） | pass | 0/11 | - |
| r1-drain-below-threshold-order | R1 排水收敛与排序：5 个终态目录 + 阈值 2，应按 updated 升序持续归档至终态计数**低于阈值**（5→1：归档最旧 4 条，仅保留最新 1 条——注意不是旧语义的「降至 ≤阈值」5→2），target_count=4；被归档条目自 STATE.md 迁出至归档清单且 archived_by=auto。出处：specs/spec-archive-drain/spec.md R1、tasks.md 1.1、core/dashboard/data/spec_archive.py:718（updated 升序哨兵排序） | pass | 0/11 | - |
| r1-threshold-zero-disables-actions-keeps-backfill-inventory | auto_threshold=0 禁用全部自动归档动作：终态目录一律保留——含「done+报告+滞留 4 天」（若未禁用本应被 R2 时效归档）与「done 无报告」两个目录；但存量回填 backfill（STATE 终态条目 gone-already 的目录已缺失）与 R4 每日盘点 INFO 不受该开关约束——回填迁出 archived_by=backfill，两个保留目录的名字均出现在盘点日志。出处：specs/spec-archive-drain/spec.md R1（auto_threshold=0 括注）、core/dashboard/data/spec_archive.py:590（backfill_archived_entries）、:585（_archive_log） | pass | 0/10 | - |
| r2-age-archive-independent-of-threshold | R2 时效归档独立于阈值：阈值 50 远高于终态目录数（3），阈值归档不触发；「终态+verification-report.md+目录 mtime 滞留 ≥72h（夹具 4 天）」的 aged-rep 仍被自动归档（目录移入 spec/archive/，STATE 条目迁出清单 archived_by=auto）；同规格但滞留 <72h（1 小时）的 fresh-rep 与无报告的 done-fresh-norep 均不归档。出处：specs/spec-archive-drain/spec.md R2、core/verify_report.py:1208（verification-report.md 写盘方，作「已验证」物证） | pass | 0/6 | - |
| r3-orphan-archive-unregistered | R3 孤儿目录接管：STATE.md 无条目的孤儿目录 orphan-aged-rep 含 verification-report.md 且 mtime 滞留 ≥72h（4 天），经 archive_spec 孤儿形态入参（allow_unregistered：跳过 STATE 成员查找与终态防御校验，保留防穿越/TOCTOU 回滚/台账/runs 清理/自动提交）自动归档——目录移入 spec/archive/，但不写 STATE/清单条目（归档清单不含孤儿名、活跃 STATE.md 字节级不变）；既有注册终态目录 done-fresh 不受扰动（仍在 changes/ 且条目仍在 STATE）。出处：specs/spec-archive-drain/spec.md R3、design.md 决策 6、core/dashboard/data/spec_archive.py:428（archive_spec）、:474-482（现行 STATE 成员校验） | pass | 0/7 | - |
| r3-orphan-unqualified-inventory-only | R3 不满足条件的孤儿仅盘点不动作：无报告孤儿（orphan-norep，滞留 4 天）与含报告但滞留 <72h 的孤儿（orphan-fresh-rep，1 小时）均不被归档、仍留在 spec/changes/，但两者目录名均出现在 R4 每日盘点 INFO 清单（孤儿无条件列示）。出处：specs/spec-archive-drain/spec.md R3（「不满足条件的孤儿 → 仅入每日盘点清单」）与 R4② | pass | 0/6 | - |
| r4-inventory-categories-and-24h-dedup | R4 每日滞留盘点三类并列 + 24h 去重：非终态+报告+超期（act-aging，R4①）、孤儿无报告（orphan-x，R4② 无条件列示）、终态无报告（done-norep，R4③）三个目录名均出现在首轮盘点 INFO 日志，且三者一律不被归档（仍留在 spec/changes/，活跃 STATE.md 字节级不变）；同进程 24h 内二次调用不再重复发盘点信号（无新增含目录名的日志行）。出处：specs/spec-archive-drain/spec.md R4、core/dashboard/data/spec_archive.py:585（_archive_log 出口） | pass | 0/6 | - |
| r5-nonterminal-never-archived-drain-mix | R5 安全边界（排水混合场景）：阈值 2 + 终态目录 3 条触发排水，implementing 非终态目录（即使含 verification-report.md 且 mtime 滞留 4 天）永不归档——仅按 updated 升序归档最旧 2 条终态（t-old-1/t-old-2 移入 spec/archive/，archived_by=auto），非终态 act-aged-rep 与最新终态 t-new 保留；total_terminal_unarchived 只统计终态（=3，非终态不计入）。出处：specs/spec-archive-drain/spec.md R5、core/dashboard/data/spec_archive.py:33（_TERMINAL_STATUSES）、:694（终态过滤） | pass | 0/8 | - |
| drain-regression-existing-suites | 回归既有归档/迁出测试（tests/test_spec_archive.py + tests/test_archive_state_migration.py）。R1 排水目标由「降至 ≤阈值」改为「降至 <阈值」，既有断言（tests/test_spec_archive.py:347 的 archived==2、tests/test_archive_state_migration.py:233 的 archived==2）须随新语义同步更新后全绿——旧断言若原样留存即与本 SPEC R1 冲突，回归红。出处：core/dashboard/data/spec_archive.py:651（auto_archive_check）、上述两测试文件断言行 | pass | 0/2 | - |
