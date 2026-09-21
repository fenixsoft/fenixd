## MODIFIED Requirements

### Requirement: 空闲判定语义

「空闲」MUST 定义为**同时**满足：①`agent_runner` 无活跃 run（覆盖 planner / implementer / verifier / judge 全部 run 形态）；②**不存在任何未收口的在飞评审 run**——含转录因 API 重试/停滞而暂不增长的 run，以「`reviewer_run` 锚点存在且该 run 尚在飞」判定（复用既有 `PMEngine.is_review_in_flight` + `LivenessSupervisor.reviewer_in_flight` 双判据合取，与派发守卫同口径）；③ admin 处置 worker 池无在途任务。任一来源非空即 MUST 判定为非空闲。

在飞评审判定 MUST 以**进程存活**（daemon 进程内 run 注册表）为主判据、run 流文件为兜底，MUST NOT 以「转录是否仍在增长」作在飞依据（停滞 run 的转录本就不增长，以此为依据即本 Requirement 要消除的缺陷）。判定 MUST 复用既有内部状态，MUST NOT 通过扫描外部进程列表（`ps` / `/proc` 遍历）反推。

对确已收口或已死亡的 run（进程表无记录且流文件末行已终态），MUST NOT 使其永久占据「非空闲」——此类陈旧锚点 MUST 判为无在飞评审，自愈在真正空闲时 MUST 仍能触发。

#### Scenario: 评审 run 在飞时判定为非空闲

- **WHEN** 一个 spec-review run 已派发且未收口，此时实现车道 `_active_runs` 为 0（评审 run 不占用实现车道槽位）、admin 池亦无在途
- **THEN** 空闲判定 MUST 为假（评审车道在飞独立构成非空闲），连续空闲计时 MUST NOT 累计

#### Scenario: 停滞的评审 run 不因转录不增长而判空闲

- **WHEN** 上述评审 run 因 API 长重试（如 520）而流文件暂不增长，进程仍存活
- **THEN** 空闲判定 MUST 仍为假，MUST NOT 因流新鲜度不足而落入「陈旧锚点」分支

#### Scenario: 陈旧锚点不永久占据非空闲

- **WHEN** 某 spec 的 `reviewer_run` 锚点残留（历史写入）但该 run 进程已退出、流文件末行已终态
- **THEN** 该 spec MUST NOT 计入「非空闲」，空闲判定可返回真，自愈在满足其余条件时 MUST 可触发

#### Scenario: 活跃 run 期间判定为非空闲

- **WHEN** 存在任一进行中的 agent run（含 planner 出题、verifier 验证）
- **THEN** 空闲判定为假，不计入连续空闲时长

#### Scenario: admin 处置在途判定为非空闲

- **WHEN** 无 agent run 活跃，但 admin 处置 worker 池有在途任务
- **THEN** 空闲判定为假，不计入连续空闲时长

#### Scenario: 双源皆空判定为空闲

- **WHEN** 无 agent run 活跃、无在飞评审 run、且 admin 处置池无在途任务
- **THEN** 空闲判定为真，开始累计连续空闲时长

### Requirement: 空闲感知的陈旧自愈触发

daemon 主循环 MUST 在陈旧状态为真、配置 `stale_code_selfheal.enabled` 为真、且项目存在活跃 supervisor 托管时，判定「空闲」。**「空闲」的定义以同能力「空闲判定语义」Requirement 为准（含在飞评审 run 维度，见该条的完整定义与判据），本条 MUST NOT 另行给出与之不一致的定义。** 当空闲连续保持达 `stale_code_selfheal.idle_confirm_seconds`（默认 120 秒）后，MUST 写入 `.fenix/restart_request`（复用既有 supervisor 优雅重启协议，MUST NOT 引入新信号或改变该协议语义），并在日志中记录触发原因与等待时长。空闲计时 MUST 在任一非空闲信号出现时立即清零。`.fenix/restart_request` 已存在时 MUST NOT 重复写入。对确已收口或死亡的 run，MUST NOT 使其永久占据「非空闲」（自愈须最终可触发）。

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