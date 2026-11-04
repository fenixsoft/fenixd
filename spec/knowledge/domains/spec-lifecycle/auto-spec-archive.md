# SPEC 自动归档
<!-- knowledge: capability=auto-spec-archive rev=4
     sources=spec/archive/2026-09-09-add-spec-archive,spec/archive/2026-10-06-fix-run-cleanup-attach-spec-archive,spec/archive/2026-10-06-add-archive-state-migration,spec/changes/remove-aged-spec-archive -->

终态 SPEC 的自动归档由阈值水位统一驱动：活跃区积压达到阈值即排水至低于阈值；`spec/changes/` 下 STATE 无条目的孤儿目录由独立的时效判据通道接管；每日盘点以纯信号提供水位可见性。

## 规则

- 归档触发为纯水位驱动：daemon 主循环以独立低频计时（分钟级）周期检查每个项目，终态（done/pushed）未归档计数 >= `archive.auto_threshold`（缺省 50）时触发，按 `STATE.md` 条目 `updated` 升序持续归档可归档条目，直至终态目录计数低于阈值（target = total - threshold + 1）。
- 「可归档条目」= STATE 终态且 `spec/changes/<name>/` 活跃目录仍存在的条目，不以 verification-report.md 为前置。低于阈值时终态积压滞留活跃区属预期形态，终态 SPEC 没有任何时效性自动归档通道。
- 完成时间取 `STATE.md` 条目的 `updated` 字段（终态 SPEC 的 entry 恒定不变，`updated` 即完成时间）。
- 阈值归档成功后同步迁出该 SPEC 的 STATE.md 条目至归档清单 `.fenix/STATE.archive.md`（`archived_by=auto`）；迁出失败降级为告警，条目留待存量回填下一轮迁出；已迁出条目在后续轮次不再计入阈值统计。
- 孤儿目录接管：`spec/changes/` 下 STATE 无对应条目的目录，含 verification-report.md 且目录 mtime 滞留 >= 72 小时，经 `archive_spec` 孤儿形态入参自动归档（跳过 STATE 成员查找与终态防御校验，保留防穿越/TOCTOU 回滚/台账/runs 清理/自动提交），归档台账标 `archived_by=auto-orphan`，不写 STATE/清单条目。孤儿不计入阈值水位，本通道是孤儿脏目录的唯一自动清理路径。
- 孤儿接管只针对 STATE 无条目的目录：终态条目对应目录无论滞留多久、是否含报告，都不被孤儿通道归档。
- 每日盘点（纯信号零动作，24 小时去重）：① 终态水位观测——终态未归档目录计数非零时，一条 INFO 列示计数与最老终态目录滞留天数，不按单目录列示、不区分含/不含 verification-report.md；② STATE 无条目的孤儿目录无条件列示，满足孤儿接管判据者归档后自然移出下一轮清单。
- `archive.auto_threshold=0` 表示禁用全部自动归档动作（阈值排水与孤儿接管）；每日盘点与存量回填（先回填后阈值归档）不受该开关约束。
- 非终态（如 implementing）与已归档条目不计入阈值统计。
- 单个 SPEC 归档失败（如目标目录已存在）时跳过该条并记录日志，继续处理其余，不中断检查循环。
- 配置键用户级与项目级均可设置（项目级优先，参与配置热更新）；设置页「其他」面板提供阈值输入控件（非负整数，0 = 禁用说明），保存后（含直接编辑配置文件）经热更新生效，无需重启 daemon。

## 溯源

- 2026-09-09 add-spec-archive（spec/archive/2026-09-09-add-spec-archive） — 新增自动归档：阈值配置与设置页控件、daemon 周期检查与最久优先归档、单条失败不阻塞
- 2026-10-06 fix-run-cleanup-attach-spec-archive（spec/archive/2026-10-06-fix-run-cleanup-attach-spec-archive） — 设置页 `runs.keep` 字段已随该归档移除，并列表述摘除（auto_threshold 语义不变）
- 2026-10-06 add-archive-state-migration（spec/archive/2026-10-06-add-archive-state-migration） — 归档成功后同步迁出 STATE.md 条目至归档清单（archived_by=auto，迁出失败降级告警）；存量回填与阈值开关解耦（先回填后阈值归档）
- 2026-11-04 remove-aged-spec-archive（spec/changes/remove-aged-spec-archive/） — 已随本 SPEC 废除：时效归档通道（终态+verification-report.md+mtime 滞留 72h 自动归档）。终态归档收敛为纯阈值水位驱动；登记孤儿目录接管与每日盘点（水位观测化）；threshold=0 语义收敛为禁用阈值排水与孤儿接管
