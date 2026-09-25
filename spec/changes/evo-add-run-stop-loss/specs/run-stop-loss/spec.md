# spec-run-stop-loss

## ADDED Requirements

### Requirement: 取消旗标跨 attempt 生效

core/agent_runner/runner.py 的 cancel_run 在未命中活跃 attempt（not_running）时 MUST 仍按基础 run_id 登记取消旗标（含 reason 与 by 元数据，幂等）后再返回，使随后由 in-place retry 或复活机制重派的 attempt 在启动守卫处命中旗标并以 cancelled 终态有序收尾；返回值 MUST 保留 not_running 语义并可附旗标登记标记，调用方语义兼容；run 收尾的旗标清理沿用既有幂等清理路径，MUST NOT 产生跨 run 旗标泄漏。

#### Scenario: attempt 间隙取消拦截复活 attempt

- **WHEN** 仲裁或管理面在某 attempt 刚退出、下一 attempt 未启动的间隙调用 cancel_run
- **THEN** 取消旗标被登记，随后重派的 attempt 启动守卫命中旗标即终止，run 以 cancelled 收尾，MUST NOT 再执行任何 provider 轮次

#### Scenario: 活跃 attempt 取消行为不变

- **WHEN** cancel_run 命中正在运行的 attempt
- **THEN** 沿用现行旗标登记与属主线程终止路径，行为与语义不变

### Requirement: in-place retry 让位隔离标记

attempt 重派（产物硬门 add-judge-artifact-gate 与瞬态重试共用的 in-place retry 路径）执行让位判据时，对 planner-plan 类 run MUST 增查并行出题标记 status 为 discarded；命中时 MUST 放弃重派并让 run 以 cancelled 或 failure 收尾。（评审核正：标记实际枚举为 dispatched/failed/discarded/completed，并无 quarantined 值——产物隔离经 _quarantine_parallel_product 重命名为 .parallel-discarded 体现，与 discarded 标记写入在同一收尾路径伴生发生，故让位判据锚定 discarded 单值即可覆盖隔离与转串行两类终态。）标记读取经 runner 既有注入约定完成，MUST NOT 引入 agent_runner 对 pm_engine 的模块依赖；标记缺失或读取失败时 MUST 按无标记处理、不阻断正常重试。

#### Scenario: 已隔离的并行出题 run 不再重派

- **WHEN** 并行出题标记已被消费侧置为 discarded 后，产物硬门触发 in-place retry
- **THEN** 让位判据命中，不重派，run 以 cancelled 或 failure 收尾，串行转道不受影响

#### Scenario: 正常重试不受影响

- **WHEN** 并行出题标记处于在途状态或不存在
- **THEN** 让位判据不命中，in-place retry 照常执行

### Requirement: 停滞预算复合判停（缺省关闭）

run 内停滞判停 MUST 使用复合判据且 MUST NOT 以绝对停滞次数为单一阈值（慢 provider 下正常成功 run 可含 10 次以上超过 60 秒的往返）：判据为「run 内连续 N 次以上达到 120 秒的往返」或「stall 占比达到一半且超过 M 分钟无产物 mtime 进展」，N 与 M 经 agents.run_stall_budget_* 配置且整个预算缺省关闭。判停读取复用流式循环既有 latency 采样点，触发时走既有 attempt 终止与清理路径并在终态日志记录命中判据，MUST NOT 新增 admin 告警。统计口径为 run 级累积：跨 attempt 与 in-place retry 重派的新 attempt 不重置预算（现状 latency_state 为单次 _run_claude 作用域，run 级累积须把样本或判停状态提升到 run 级聚合）；命中判停 MUST 终止整个重试链（对齐 frozen 早退模式），MUST NOT 再触发瞬态重试或 in-place retry 重派，否则止损会被自动重派放大。

#### Scenario: 缺省关闭不判停

- **WHEN** 未启用 agents.run_stall_budget_* 且 run 含多次超过 60 秒的停滞
- **THEN** 不判停，run 行为与现状一致

#### Scenario: 复合判据命中有序止损

- **WHEN** run 内连续 N 次以上达到 120 秒的往返，或 stall 占比达到一半且 M 分钟无产物进展
- **THEN** 走既有 attempt 终止与清理路径有序收尾，终态日志记录命中判据，无新增 admin 告警

#### Scenario: 慢而健康的 run 不误杀

- **WHEN** run 停滞次数较多但单次均未达 120 秒且产物 mtime 持续推进
- **THEN** 复合判据不命中，run 继续执行
