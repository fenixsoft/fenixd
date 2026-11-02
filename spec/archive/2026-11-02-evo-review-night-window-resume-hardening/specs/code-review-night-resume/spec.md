## ADDED Requirements

### Requirement: 保守跨窗时长估计
周期审查派发守卫的预计时长 SHALL 取近 N 轮（N=3，沿用 NIGHT_QUIET_DURATION_SAMPLE_LIMIT）归档 run_metrics duration_s 的最大值；可用样本不足 N 时取已有样本最大值。预计结束区间与任一静默窗相交即本轮顺延的既有判定逻辑不变。

#### Scenario: 上行趋势下拦截穿窗派发
- **WHEN** 近 3 轮归档时长为 10893/12500/5338 秒、派发时刻 01:00
- **THEN** 估计取 12500 秒、预计结束 04:29 落入 04:15-04:45 静默窗，本轮顺延（reason=night_quiet_window_deferred），不再以均值 9577 秒放行

### Requirement: 待核销锚驱动剃余续审
writeoff-pending 锚存在时，周期审查派发 SHALL 以「全量清单 − 抢救已落账分片覆盖文件」的剩余清单派发（复用 429 限流重派的 remaining_manifest 机制），SHALL NOT 整轮全量重烧；续审收尾后由既有累计覆盖守卫判定，覆盖完整时解锁全仓核销并清除锚，部分覆盖时维持抢救红线不核销。

#### Scenario: 断连死 run 后只补未落分片
- **WHEN** 上一轮审查死于夜间断连、抢救落账 49/52 分片并写入 writeoff-pending 锚
- **THEN** 下一轮周期审查仅审查缺失分片对应文件并在 run 标注续审来源，收尾累计覆盖完整即核销清锚，已落分片不重烧

### Requirement: 续审路径可观测
锚驱动续审 SHALL 写一行结构化日志（reason=writeoff_resume、剩余分片/文件数、来源 run id），与既有 night_quiet_window_deferred 顺延日志共同支撑夜间死亡复盘对账。

#### Scenario: 复盘可对账
- **WHEN** 锚驱动续审派发发生
- **THEN** daemon 日志可按 reason=writeoff_resume 检索到该次派发及其剩余清单规模