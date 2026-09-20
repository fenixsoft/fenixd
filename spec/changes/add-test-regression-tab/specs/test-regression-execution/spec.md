# test-regression-execution

## ADDED Requirements

### Requirement: 手动触发全量回归（文件信号）

Dashboard MUST 提供 `POST /api/regression/run`（body `{project}`），原子写入 `.fenix/regression_request.json`（含 `requested_at`），由 daemon 主循环消费——MUST NOT 在 HTTP 线程内同步执行回归。

消费方（daemon 主循环）MUST：

- 读取信号 → 校验项目 `verify.yaml` 的 `regression` 段存在且有效（无效/缺失 → 丢弃信号并记 WARNING）；
- 消费方守卫与 `code-review`/`approve_push` 同判据：daemon `hosting_state` 为 `stopped`/`unmanaged` 时信号无人消费，POST 端点 MUST 前置拒绝（400/409），消费侧二次校验并丢弃；
- 单飞：已有回归在跑时忽略请求并记日志（不排队、不并发）。

#### Scenario: 手动触发受理

- **WHEN** 用户点击分面「立即执行全量回归」，POST /api/regression/run 成功受理
- **THEN** `.fenix/regression_request.json` 被写入，daemon 下一轮主循环将其消费并派发后台回归 worker，端点返回 200 + `{ok, requested_at}`

#### Scenario: daemon 未托管时拒绝

- **WHEN** daemon `hosting_state` 为 `unmanaged`
- **THEN** POST /api/regression/run 返回 409 明确拒绝，MUST NOT 写入会永久滞留的信号

#### Scenario: 已有回归在跑时单飞

- **WHEN** 已有一次全量回归正在进行
- **THEN** 新的触发请求被忽略（返回 409「已有回归在进行中」），MUST NOT 并发启动第二次

#### Scenario: 项目未配置 regression 段时触发

- **WHEN** 项目 `verify.yaml` 无有效 `regression` 段，用户触发回归
- **THEN** 返回 400 并附「该项目未配置全量回归（verify.yaml regression 段）」，MUST NOT 派发空跑

### Requirement: 全量回归执行与 JUnit XML 解析

回归 worker MUST 在项目根执行 `regression.cmd`（cwd=项目根，硬超时= `regression.timeout_seconds`），执行完成后读取 `regression.output` 指向的 JUnit XML 并解析为结构化结果：

- 总用例数、通过数、失败数、错误数、跳过数；
- 每个失败/错误用例：名称、文件:行（若 XML 提供）、耗时、失败类型（failure/error）、错误摘要；
- 超时判定：命令被硬超时中止 → 整体 `status: "timeout"`，并在结果中标出「未完成」；
- 长耗时用例：单用例 `time` 属性 > `long_test_threshold_seconds` 的用例，单独归入 `long_tests` 列表；
- 执行时间（started_at/finished_at，UTC）与总耗时（秒）。

命令非零退出但 XML 可解析时，MUST 以解析结果为准（失败用例已反映在 XML 中），`status: "failed"`；命令零退出且无失败/超时 → `status: "passed"`；XML 不可解析 → `status: "parse_error"`（附原因）。

#### Scenario: 全绿结果

- **WHEN** 回归命令执行完成、退出码 0、JUnit XML 显示 0 失败 0 错误 0 超时
- **THEN** 结果快照 `status: "passed"`，含总数、执行时间、耗时，`failures`/`long_tests` 为空

#### Scenario: 硬超时中止

- **WHEN** 回归命令超过 `timeout_seconds` 仍不结束
- **THEN** 进程被中止，结果快照 `status: "timeout"`，`long_tests`/`failures` 尽量保留已解析部分，并标记本次回归未完成

#### Scenario: 长耗时用例抽取

- **WHEN** JUnit XML 中某 `testcase` 的 `time` 属性为 12.5，阈值为 10
- **THEN** 该用例出现在结果快照的 `long_tests` 列表中（名称、文件:行、耗时 12.5）

#### Scenario: JUnit XML 不可解析

- **WHEN** 命令执行完毕但 `output` 文件不存在或非合法 JUnit XML
- **THEN** 结果快照 `status: "parse_error"` 并附非空原因，MUST NOT 静默当作全绿

### Requirement: 回归结果快照落盘

回归执行结果 MUST 写入 `.fenix/regression/last-run.json`（单文件，覆盖式快照；含 `status`、`started_at`、`finished_at`、`duration_seconds`、`total`/`passed`/`failed`/`errors`/`skipped`、`failures`、`long_tests`、`long_test_threshold_seconds`、`cmd`、`output`、错误/解析原因）。该目录为 gitignored 运行时产物，MUST NOT 作为 SPEC 交付物提交。

读侧（`GET /api/regression/result`）MUST 在快照缺失、损坏或非法 JSON 时返回明确状态（`status: "never_run"` / `"parse_error"`），MUST NOT 报 500。

#### Scenario: 快照写入

- **WHEN** 一次回归执行完成
- **THEN** `.fenix/regression/last-run.json` 含完整结构（状态、计数、耗时、failures、long_tests 等）

#### Scenario: 从未执行过

- **WHEN** `.fenix/regression/last-run.json` 不存在
- **THEN** `GET /api/regression/result` 返回 `{status: "never_run"}`（200），分面展示「尚未执行过全量回归」引导态

### Requirement: 周期性全量回归调度

框架 MUST 支持经 `admin.regression.enabled`（缺省 false）开启周期性全量回归：开启后与每日自省同周期（`admin.self_review.run_at` 时点）触发一次执行，守卫与 `code-review` 同源——开关关闭时全链路零动作；同一自然日防重（独立状态文件 `.fenix/regression/state.json` 的 `last_run_date`，MUST NOT 复用自省/code-review 的防重状态）；已有回归在跑时单飞跳过；项目无有效 `regression` 段时跳过并记日志。

调度检查点 MUST 挂在既有 admin 巡检循环（不新增线程/定时器），异常只记日志不阻断巡检。

回归执行 MUST 与主机级全量套件互斥：起跑前抢占 `bin/run_full_suite.py` 的同一把主机级锁（`.fenix/full-suite.lock`，等待上限同其 600s）；拿不到即放弃本次执行并记日志（MUST NOT 与之并发跑第二套全量测试）。

#### Scenario: 开启后每日触发一次

- **WHEN** `admin.regression.enabled` 为 true，`run_at` 时点已到，且当日尚未执行
- **THEN** 巡检检查点派发一次全量回归，完成后写 `state.json` 的 `last_run_date` 为当日

#### Scenario: 同自然日防重

- **WHEN** 当日已执行过周期性回归
- **THEN** 后续巡检检查点跳过（`reason: already_ran_today`），不重复执行

#### Scenario: 开关关闭零动作

- **WHEN** `admin.regression.enabled` 为 false
- **THEN** 巡检检查点不做任何事（不派发、不写状态、不写产物）

#### Scenario: 无 regression 段时跳过

- **WHEN** 开关开启但项目 `verify.yaml` 无有效 `regression` 段
- **THEN** 检查点跳过并记日志（`reason: not_configured`），不派发空跑
