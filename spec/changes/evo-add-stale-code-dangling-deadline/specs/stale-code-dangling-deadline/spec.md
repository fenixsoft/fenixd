## ADDED Requirements

### Requirement: 代码基线悬空时长计量

daemon SHALL 在代码基线进入陈旧态（_code_stale 由假变真的边沿，含进程启动时即为陈旧态的情形）时记录悬空起点 _code_stale_since，并在基线恢复新鲜时清零。

#### Scenario: 进入陈旧态记录起点

- **WHEN** 主循环周期检测 _update_stale_code_state 判定 _code_stale 由假变真
- **THEN** 记录 _code_stale_since 为当前 UTC 时刻，且既有边沿告警行为不变
- **AND** 若进程启动时基线即已陈旧，_code_stale_since 取进程启动时刻

#### Scenario: 基线恢复新鲜清零

- **WHEN** _code_stale 由真变假
- **THEN** 清除 _code_stale_since

### Requirement: 悬空超时不等空闲的安全重启

daemon SHALL 在 _code_stale 持续超过 stale_code_selfheal.max_dangling_seconds（缺省 14400，0 = 关闭）后，不再以 _is_idle 为前置，直接写入 .fenix/restart_request 触发既有规划性重启排水（supervisor SIGTERM → planned_restart 在飞宽限收尾 / checkpoint 保全 / 断点续做）；该分支 SHALL 仍受既有 cooldown 与 self-triggered 闸门约束，且 SHALL 防止主循环每周期重复写入 restart_request。

#### Scenario: 悬空超时且系统繁忙

- **WHEN** _code_stale 为真且 now - _code_stale_since > max_dangling_seconds，同时存在在飞 run（_is_idle 为假）
- **THEN** 不等待空闲，写入 .fenix/restart_request 并按既有自愈路径记录 self_triggered
- **AND** 在飞 run 由 shutdown 的 planned_restart 排水路径宽限收尾或保全后断点续做

#### Scenario: 悬空未超时不触发

- **WHEN** _code_stale 为真但悬空时长 ≤ max_dangling_seconds
- **THEN** 行为与现状一致：仅空闲时自愈，忙时只清零空闲计时

#### Scenario: 升级开关关闭

- **WHEN** max_dangling_seconds = 0
- **THEN** 不执行悬空超时分支，行为与现状完全一致

### Requirement: 悬空超时升级告警需人工知悉

悬空超时分支首次触发时，daemon SHALL 写入一条 signal_type=stale_code_dangling_timeout、severity=warning 的告警，且不得写入即 mark_handled（与 stale_code 的降噪处理不同，须进入人工待处理视图），写入前 SHALL 复用 60 分钟写入去重（latest_signal）。

#### Scenario: 超时触发产生未处理告警

- **WHEN** 悬空超时分支首次触发
- **THEN** admin_alerts 出现 stale_code_dangling_timeout 告警且处于未处理状态，进入人工待处理视图

#### Scenario: 60 分钟内不重复写

- **WHEN** 60 分钟内已有同 signal_type 告警
- **THEN** 跳过写入，仅记 INFO 日志