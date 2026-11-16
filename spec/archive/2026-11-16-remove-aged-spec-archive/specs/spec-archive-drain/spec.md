# specs/spec-archive-drain/spec.md

## MODIFIED Requirements

### Requirement: R1 阈值排水

auto_archive_check 的触发条件为「终态未归档计数 >= archive.auto_threshold 即触发，且单轮内按 updated 升序持续归档可归档条目，直至 changes/ 中终态目录计数低于阈值」。「可归档条目」= STATE 终态且活跃目录仍存在的条目（沿用现行阈值归档口径，不以 verification-report.md 为前置——否则无报告终态残留会让「归档至低于阈值」的循环无法收敛）。auto_threshold=0 表示禁用（R1/R3 的自动归档动作全部禁用；存量回填 backfill 与纯信号的 R4 每日盘点不受该开关约束）。终态 SPEC 的归档仅由本通道水位驱动：活跃区水位维持在阈值左右（低于阈值时终态积压滞留属预期形态，无任何时效性归档）。

#### Scenario: 终态积压达到阈值触发排水

- **WHEN** 终态未归档计数 >= archive.auto_threshold（默认 50）
- **THEN** 按 updated 升序归档可归档条目直至终态目录计数低于阈值（target = total - threshold + 1）

#### Scenario: 终态目录满足时效判据仍不被归档

- **WHEN** 终态未归档计数 < archive.auto_threshold 且某终态目录含 verification-report.md 且目录 mtime 滞留 >= 72h
- **THEN** 该目录不被自动归档（时效驱动归档已移除，终态归档仅由 R1 阈值水位触发）

### Requirement: R3 孤儿目录接管

STATE.md 无对应条目的孤儿目录：含 verification-report.md 且滞留 >= 3 天（目录 mtime）→ 经 archive_spec 孤儿形态入参（跳过 STATE 成员查找与终态防御校验，保留防穿越/TOCTOU 回滚/台账/runs 清理/自动提交）自动归档，归档台账标 archived_by=auto-orphan，不写 STATE/清单条目；不满足条件的孤儿 → 仅入每日盘点清单（R4②），不做动作。孤儿目录不计入 R1 阈值水位统计，本通道是孤儿脏目录的唯一自动清理路径（用户已确认保留）。

#### Scenario: 孤儿目录满足判据被接管

- **WHEN** STATE 无条目的孤儿目录含 verification-report.md 且目录 mtime 滞留 >= 72h
- **THEN** 经孤儿形态自动归档，archived_by=auto-orphan，不写 STATE/清单条目

#### Scenario: 终态目录不被 R3 误伤

- **WHEN** STATE 终态条目对应目录含 verification-report.md 且滞留 >= 72h 且终态未归档计数 < 阈值
- **THEN** 该目录不被 R3 归档（R3 仅接管 STATE 无条目的孤儿目录）

### Requirement: R4 每日滞留盘点

auto_archive_check 周期内加 24 小时去重的每日盘点（复用 _archive_log 出口，纯信号零动作，防滞留无声积压）：① 终态水位观测——STATE 终态未归档目录计数非零时，列示计数与最老终态目录滞留天数（一条 INFO，水位逼近阈值时的可预见性；终态积压属预期形态，等待 R1 排水，不再按单目录列示、不区分含/不含 verification-report.md）；② STATE 无条目的孤儿目录无条件列示（满足 R3 条件者归档后自然移出清单）。原③项（终态无报告目录单列）随 R2 移除并入①——R1 排水不以 verification-report.md 为前置，无报告终态与有报告终态在阈值模型下地位等同，区分列示失去异常语义。

#### Scenario: 终态水位一日一报

- **WHEN** 存在终态未归档目录且该项目 24 小时内未发过盘点信号
- **THEN** 发一条 INFO 列示终态未归档计数与最老终态目录滞留天数，不按单目录列示

#### Scenario: 孤儿目录列示

- **WHEN** spec/changes/ 存在 STATE 无条目的孤儿目录
- **THEN** 进入每日盘点清单列示；满足 R3 判据的孤儿归档后不再出现在下一轮清单

## REMOVED Requirements

### Requirement: R2 时效归档

**Reason**: 时效归档（终态 + verification-report.md + 目录 mtime 滞留 >= 72h 自动归档，archived_by=auto）原为「归档后触发知识蒸馏」设计的确定性收尾通道；蒸馏触发已迁至 approve_push 推送成功转移（distill-push-trigger，蒸馏输入双态解析 changes/ 优先、archive/ 兜底），终态 SPEC 不再需要为喂蒸馏而定期归档。该通道持续把活跃区水位压至远低于 archive.auto_threshold，使阈值失去「活跃区水位管理」语义。用户裁决（2026-11-04）：未归档 SPEC 维持在阈值（默认 50 条）左右，不由时效性驱动归档。

**Migration**: 终态 SPEC 滞留活跃区属预期形态，由 R1 阈值排水（计数 >= threshold 触发，排水至低于阈值）覆盖；水位可见性由 R4① 终态水位观测承接；孤儿目录仍由 R3 接管（不受本移除影响）；threshold=0 语义收敛为禁用 R1/R3 全部自动归档动作。已终态未归档的存量 SPEC 不迁移，等待水位自然达到阈值。
