# design.md

## 现状与根因（已核实）

- 调用链：fenixd.py:1154-1159 每 300 秒调 core/dashboard/data/spec_archive.py:651 auto_archive_check（先 backfill_archived_entries :590 后阈值归档）。
- 归档条件：「终态+目录在 changes/ 计数 > archive.auto_threshold（默认 50）」；当前 50 条终态目录全在 changes/，50 ≤ 50 恒不触发——阈值饱和冻结。
- backfill 只管「STATE 有记录但目录状态反向漂移」，不管「目录在 changes/ 而 STATE 无条目」的孤儿（现存 2 例）。
- 引擎按 STATE 派发、不触及无条目目录（模块注释 :321-322），故归档终态/孤儿目录无派发风险。
- verification-report.md 由 core/verify_report.py:1208 写盘（闸门 core/pm_engine/verification/report_gate.py），可作「已验证」物证；归档动作复用 archive_spec（:428，原子移动+归档台账）。

## 设计决策

1. **排水而非单条归档**：触发由 > 改为 >=，循环归档至「终态目录计数低于阈值」为止。注意饱和点（计数恰等于阈值 50）单轮只腾挪 1 条——积压主体的清空靠决策 2 的时效归档在首轮同周期完成（评审实测：50 条终态目录中 47 条含验证报告、滞留中位 17.2 天、仅 10 条 ≤3 天，约 40 条首轮即满足时效），R1 排水循环兜住无报告残留与新到终态的稳态水位（到阈值即触发、归档至低于阈值），此后稳态在阈值附近小幅波动。
2. **时效归档独立于阈值**：阈值是「活跃区期望水位」，防批量误归档；时效规则（终态+报告+3 天）是确定性收尾，两者并行，即使阈值被配成极大值时效归档仍能兜底（auto_threshold=0 禁用 R1/R2/R3 全部自动归档动作；纯信号的每日盘点 R4 与存量回填 backfill 不受该开关约束）。
3. **「实现 commit 已进 main」的核对方式**：不逐目录跑 git——STATE 终态（pushed）即框架对「已合回」的记账终态，与 todo 建议等价且免 git 依赖；verification-report.md 由 report_gate 把关，作「已验证」判据。
4. **孤儿保守接管**：无 STATE 条目=引擎永不派发，含报告+超 3 天才归档，其余只盘点不动作，避免误收编手工暂存目录。
5. **盘点 INFO 24h 去重**：复用模块内 _archive_log 出口（:585），防 300 秒周期刷屏。
6. **孤儿归档经 archive_spec 孤儿形态入参**：archive_spec 现契约要求 spec 在 STATE.md 中（:474-482 非成员返回 found=False），孤儿目录不能按现状直接复用。约定新增孤儿形态入参（如 allow_unregistered=True）：跳过 STATE 成员查找与终态防御校验，其余机制全部保留——防穿越白名单、TOCTOU 回滚、归档台账（archived_by=auto-orphan）、runs 产物清理、commit_archive_move 自动提交；孤儿无条目可迁出，跳过 evict 环节，不写 STATE/清单条目，不改 STATE 语义。