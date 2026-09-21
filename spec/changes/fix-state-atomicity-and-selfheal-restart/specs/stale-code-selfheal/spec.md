## MODIFIED Requirements

### Requirement: 空闲感知的陈旧自愈触发

daemon 主循环 MUST 在陈旧状态为真、配置 `stale_code_selfheal.enabled` 为真、且项目存在活跃 supervisor 托管时，判定「空闲」。**「空闲」MUST 定义为：不存在任何未收口的在飞 run——含转录因 API 重试/停滞而暂不增长的 run——且 admin 处置池无在途任务。** 当空闲连续保持达 `stale_code_selfheal.idle_confirm_seconds`（默认 120 秒）后，MUST 写入 `.fenix/restart_request`（复用既有 supervisor 优雅重启协议，MUST NOT 引入新信号或改变该协议语义），并在日志中记录触发原因与等待时长。空闲计时 MUST 在任一非空闲信号出现时立即清零。`.fenix/restart_request` 已存在时 MUST NOT 重复写入。对确已收口或死亡的 run，MUST NOT 使其永久占据「非空闲」（自愈须最终可触发）。

#### Scenario: 连续空闲达标触发重启

- **WHEN** daemon 处于陈旧状态且配置启用，项目受 supervisor 托管，连续 120 秒无活跃 run 与在途处置
- **THEN** `.fenix/restart_request` 被写入，日志记录「陈旧自愈触发」及等待时长，supervisor 随后执行优雅重启

#### Scenario: 出现活跃任务则空闲计时清零

- **WHEN** 陈旧状态为真且已连续空闲 90 秒，此时一个新 run 被派发
- **THEN** 空闲计时清零，MUST NOT 写入 `restart_request`；该 run 收口后须重新累计满 120 秒才触发

#### Scenario: 停滞中的在飞 run 视为非空闲

- **WHEN** 一个评审/实现 run 已派发且未收口，其转录因 API 重试（如 520 长重试）而暂不增长，此时陈旧状态为真且已接近 120 秒
- **THEN** 空闲判定 MUST 为假，连续空闲计时 MUST NOT 累计，`.fenix/restart_request` MUST NOT 被写入，该 run MUST NOT 被自愈重启打断

#### Scenario: 重启已在途时不重复写入

- **WHEN** `.fenix/restart_request` 已存在（重启在途或因其他原因被写入）
- **THEN** 自愈 MUST NOT 再次写入该文件，也不产生重复日志