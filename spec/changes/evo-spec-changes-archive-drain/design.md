# design.md

## 现状与根因（已核实）

- 调用链：fenixd.py:1122-1124 每 300 秒调 core/dashboard/data/spec_archive.py:630 auto_archive_check（先 backfill_archived_entries :569 后阈值归档）。
- 归档条件：「终态+目录在 changes/ 计数 > archive.auto_threshold（默认 50）」；当前 50 条终态目录全在 changes/，50 ≤ 50 恒不触发——阈值饱和冻结。
- backfill 只管「STATE 有记录但目录状态反向漂移」，不管「目录在 changes/ 而 STATE 无条目」的孤儿（现存 2 例）。
- 引擎按 STATE 派发、不触及无条目目录（模块注释 :314），故归档终态/孤儿目录无派发风险。
- verification-report.md 由 core/verify_report.py:1067 写盘（闸门 core/pm_engine/verification/report_gate.py），可作「已验证」物证；归档动作复用 archive_spec（:407，原子移动+归档台账）。

## 设计决策

1. **排水而非单条归档**：只把 > 改成 >= 会在恰好阈值处反复单条腾挪；改为 >= 触发并循环归档至阈值之下，一次把 50 条积压排掉，之后稳态在阈值附近小幅波动。
2. **时效归档独立于阈值**：阈值是「活跃区期望水位」，防批量误归档；时效规则（终态+报告+3 天）是确定性收尾，两者并行，即使阈值被配成极大值时效归档仍能兜底（0 仍为禁用一切自动归档）。
3. **「实现 commit 已进 main」的核对方式**：不逐目录跑 git——STATE 终态（pushed）即框架对「已合回」的记账终态，与 todo 建议等价且免 git 依赖；verification-report.md 由 report_gate 把关，作「已验证」判据。
4. **孤儿保守接管**：无 STATE 条目=引擎永不派发，含报告+超 3 天才归档，其余只盘点不动作，避免误收编手工暂存目录。
5. **盘点 INFO 24h 去重**：复用模块内 _archive_log 出口（:564），防 300 秒周期刷屏。