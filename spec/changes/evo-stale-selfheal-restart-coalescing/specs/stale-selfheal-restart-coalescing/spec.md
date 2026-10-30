# specs/stale-selfheal-restart-coalescing/spec.md

## ADDED Requirements

### Requirement: 陈旧自愈跨批次合流

陈旧自愈在同一合流期内只执行一次按基础闸（stale_code_selfheal.idle_confirm_seconds，缺省 600s）确认的重启；此后每再检出一次陈旧边沿，空闲确认闸递增为合流闸（stale_code_selfheal.coalesce_idle_seconds，缺省 1800s）。合流期跨越自愈重启存续——按闸重启导致的悬置消化不复位合流态；仅当悬置消化且合流静止期届满（距最近一次陈旧边沿或最近一次按闸自愈重启达 coalesce_idle_seconds 无新边沿），合流状态才复位，下一次陈旧重新按基础闸。

#### Scenario: 首启陈旧按基础闸重启

- **WHEN** 进程基线后首次检出磁盘代码陈旧，且连续空闲达 idle_confirm_seconds

- **THEN** 按既有流程写 restart_request 并经 drain 重启，同时开启合流期（记录最近边沿/重启时刻，供合流静止期判定）

#### Scenario: 合流期内后续边沿按合流闸等待

- **WHEN** 按基础闸重启后，新陈旧边沿在合流静止期届满前再检出（距最近一次陈旧边沿或最近一次按闸自愈重启不足 coalesce_idle_seconds），且连续空闲达 coalesce_idle_seconds

- **THEN** 才执行下一次重启；每次被合流闸延迟的边沿在日志留痕（第 N 次边沿、当前生效闸值）

#### Scenario: 边沿消化后合流复位

- **WHEN** 磁盘代码不再超进程基线（悬置消化），且此后连续 coalesce_idle_seconds 无新陈旧边沿（合流静止期届满）

- **THEN** 合流状态复位，之后的首次陈旧重新按基础闸确认

#### Scenario: 重启后合流态幂等延续

- **WHEN** 按闸重启触发 daemon 进程更替、内存合流态丢失，且 restart_history 最近一次自愈重启记录距今不足 coalesce_idle_seconds，该窗口内再检出新陈旧边沿

- **THEN** 新进程依据重启记录把该边沿按合流闸处理（不回退基础闸）；记录超窗或无记录时按新周期基础闸确认

#### Scenario: preflight 请求通道不经合流闸

- **WHEN** 关键路径 preflight 显式请求重启（core/code_stale_flag.py request_restart）

- **THEN** 该请求按其既有语义立即执行，不受合流闸延迟

#### Scenario: 悬空强转兜底不失效

- **WHEN** 合流等待期间陈旧悬置时长达 max_dangling_seconds（4h）

- **THEN** 按既有强转逻辑立即重启，合流闸不得拦截

#### Scenario: 防循环冷却语义不变

- **WHEN** 任一来源的自愈重启发生

- **THEN** 冷却滑窗（1800s 内 ≥3 次）仍按实际重启次数计数，合流等待不视为豁免