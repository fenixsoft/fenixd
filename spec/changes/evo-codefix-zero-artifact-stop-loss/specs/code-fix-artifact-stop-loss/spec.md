# 能力：code-fix-artifact-stop-loss

## ADDED Requirements

### Requirement: 结构化失败类别透出

产物硬门（core/agent_runner/maintenance_runs.py `run_code_fix` 收尾「产物硬门」块，`_check_code_fix_artifact` 调用点）判定零产物失败时，CodeFixResult 信封（类定义 core/agent_runner/result_gate.py）SHALL 携带 failure_category="artifact_missing"；既有 conn_error 字段语义不变（硬门失败路径 conn_error 恒 False 的现状逐位保持），其余失败类别（api_error/conn_error/api_timeout 等）MUST NOT 新增类别标注，未走硬门的信封构造点 failure_category MUST 为缺省空值。

#### Scenario: 硬门零产物失败信封携带类别

- **WHEN** code-fix run 正常退出但 out 文件缺失或零有效行，产物硬门判失败
- **THEN** 返回的 CodeFixResult 信封 success=False 且 failure_category="artifact_missing"、conn_error=False，error 文案沿用硬门既有 fail-closed 文案

#### Scenario: 非硬门失败不携带类别

- **WHEN** run 因 api_error/异常等既有路径失败（未触发产物硬门）
- **THEN** 信封 failure_category 为缺省空值，api_timeout/exit_code/conn_error 既有语义逐位不变

### Requirement: 同指纹零产物止损

code-fix 链（core/code_fix.py）首轮 run 失败收尾块在收到 failure_category="artifact_missing" 的 run 失败时：

- 按批次指纹累计连败次数（daemon 进程内跨链累计）；
- 连败 ≥2 即停止该指纹的继续重派：指纹加入**进程内止损跳过集**（MUST NOT 复用新链启动即重置的 chain_skipped 承载），选批排除并集（失败档案 ∪ chain_skipped）纳入该集合，并经既有告警/日志通道留痕（含指纹、连败次数、最后失败 run id），链内其余指纹不受影响；
- 单次失败仍走既有 chain_skipped 瞬态重试，行为不变；
- 非 artifact_missing 失败不计入该计数；定向重试轮 run 失败（regression_retry_run_failed）沿用既有语义不计数，与 add-codefix-parse-error-breaker 的回归异常熔断（anomaly_streak，位于回归失败后的定向重试循环内）计数域互不干扰——二者处于互斥执行阶段（前者回归未执行，后者回归已发生）。

#### Scenario: 同指纹连败 2 次止损

- **WHEN** 同一批次指纹连续 2 次 run 以 artifact_missing 失败（跨链：第 1 链失败瞬态跳过后，下一链重选同指纹再次失败）
- **THEN** 框架 MUST 停止该指纹重派：指纹入止损跳过集、下一链选批 MUST NOT 再选中该指纹，且 MUST 恰发一条 WARNING/告警留痕（含指纹、连败次数 2、最后失败 run id）

#### Scenario: 单次失败仍瞬态重试

- **WHEN** 某指纹首次收到 artifact_missing 失败
- **THEN** 行为与现状逐位一致：条目入 chain_skipped 瞬态跳过、链 consumed 推进，MUST NOT 标记止损

#### Scenario: 其他失败类别不计数

- **WHEN** 同指纹先后发生 api_timeout、artifact_missing、api_error 失败
- **THEN** 仅 artifact_missing 计 1、止损 MUST NOT 触发；api_timeout/conn_error 既有冷却与 salvage 语义不变

#### Scenario: 止损不影响其余指纹

- **WHEN** 指纹 A 触发止损，同调度周期内指纹 B 未触发
- **THEN** 指纹 B 的选批与派发行为 MUST 不受指纹 A 止损影响

### Requirement: 派发契约测试

- 契约测试 SHALL 按字面子串断言 agents/code-fix.md 含同步派发契约条款：「回合结束 = run 终止」「run_in_background: false」「MUST NOT 以「等待完成通知」」（三者为当前模板实文，参照 tests/test_prompt_lane_efficiency_sections.py「长任务前台等待」段先例），防模板漂移。
- 契约测试 SHALL 断言止损状态机：1 次 artifact_missing 不触发、2 次触发、其他类别不计数、触发后该指纹跳过且留痕。

#### Scenario: 契约条款在位

- **WHEN** 运行 agents/code-fix.md 契约断言测试且模板未被改动
- **THEN** 三个字面子串断言全部通过；任一子串被模板漂移删除或改写时测试 MUST 失败
