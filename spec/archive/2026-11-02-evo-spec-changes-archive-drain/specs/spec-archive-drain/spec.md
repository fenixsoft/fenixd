# specs/spec-archive-drain/spec.md

## R1 阈值排水

auto_archive_check 的触发条件由「计数 > archive.auto_threshold」改为「计数 >= archive.auto_threshold 即触发，且单轮内按 updated 升序持续归档可归档条目，直至 changes/ 中终态目录计数低于阈值」。「可归档条目」= STATE 终态且活跃目录仍存在的条目（沿用现行阈值归档口径，不以 verification-report.md 为前置——否则无报告终态残留会让「归档至低于阈值」的循环无法收敛；无报告终态的可观测兜底见 R4③）。auto_threshold=0 仍表示禁用（语义不变：R1/R2/R3 的自动归档动作全部禁用；存量回填 backfill 与纯信号的 R4 每日盘点不受该开关约束）。

## R2 时效归档

满足以下全部条件的 spec/changes/ 目录，在 auto_archive_check 周期内自动归档（archived_by=auto），不受 auto_threshold 约束：

- 对应 STATE.md 条目为终态（pushed 等终态集合，复用模块内既有终态校验）；
- 目录含 verification-report.md；
- 目录滞留 ≥ 3 天（72 小时；时间基准统一为目录 mtime——目录 mtime 即内容最后变更时刻；STATE `updated` 仅用于 R1 排序，不作时效判定基准，孤儿目录无 STATE 字段可查）。

## R3 孤儿目录接管

STATE.md 无对应条目的孤儿目录：含 verification-report.md 且滞留 ≥ 3 天（目录 mtime，同 R2 口径）→ 经 archive_spec 孤儿形态入参（design 决策 6：跳过 STATE 成员查找与终态防御校验，保留防穿越/TOCTOU 回滚/台账/runs 清理/自动提交）自动归档，归档台账标 archived_by=auto-orphan，不写 STATE/清单条目；不满足条件的孤儿 → 仅入每日盘点清单（R4②），不做动作。

## R4 每日滞留盘点

auto_archive_check 周期内加 24 小时去重的每日盘点：changes/ 中存在以下任一类目录时，列清单发一条 INFO 信号（复用 _archive_log 出口；兜底可观测，防新形态滞留无声积压）——① 含 verification-report.md 且滞留 ≥ 3 天的目录；② STATE 无条目的孤儿目录（无条件列示，满足 R3 条件者归档后自然移出清单）；③ STATE 终态但无 verification-report.md 的目录（实测 3 例：fix-codefix-mapping-dotted-file-poison、fix-frozen-scenario-dict-salvage、fix-unfreeze-judge-counter-reset——R1 阈值低于阈值时与 R2 时效均不接管，需盘点暴露）。

## R5 安全边界

STATE 非终态的活跃在途目录永不归档；归档动作复用既有 archive_spec（原子移动+归档台账）——STATE 终态条目走既有路径，孤儿目录走其孤儿形态入参（design 决策 6），除此之外不新写移动逻辑。