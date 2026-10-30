# specs/spec-archive-drain/spec.md

## R1 阈值排水

auto_archive_check 的触发条件由「计数 > archive.auto_threshold」改为「计数 >= archive.auto_threshold 即触发，且单轮内按 updated 升序持续归档可归档条目，直至 changes/ 中终态目录计数低于阈值」。auto_threshold=0 仍表示禁用（语义不变）。

## R2 时效归档

满足以下全部条件的 spec/changes/ 目录，在 auto_archive_check 周期内自动归档，不受 auto_threshold 约束：

- 对应 STATE.md 条目为终态（pushed 等终态集合，复用模块内既有终态校验）；
- 目录含 verification-report.md；
- 目录滞留超过 3 天（按目录 mtime 或归档判定时刻与最后更新时刻之差）。

## R3 孤儿目录接管

STATE.md 无对应条目的孤儿目录：含 verification-report.md 且滞留超 3 天 → 同规则自动归档（归档台账标 archived_by=auto-orphan）；不满足条件的孤儿 → 仅入每日盘点清单，不做动作。

## R4 每日滞留盘点

auto_archive_check 周期内加 24 小时去重的每日盘点：changes/ 中仍有含 verification-report.md 且滞留超 3 天的目录时，列清单发一条 INFO 信号（兜底可观测，防新形态滞留无声积压）。

## R5 安全边界

STATE 非终态的活跃在途目录永不归档；归档动作复用既有 archive_spec（原子移动+归档台账），不新写移动逻辑。