<!-- knowledge: capability=test-regression-execution rev=1 sources=spec/archive/2026-09-25-add-test-regression-tab -->

# 全量回归执行与调度

全量回归的触发（手动文件信号 + 周期调度）、执行、JUnit XML 解析与结果快照落盘规则。

## 现行规则

- 手动触发走文件信号：`POST /api/regression/run`（body `{project}`）原子写入 `.fenix/regression_request.json`（含 `requested_at`），由 daemon 主循环消费，不在 HTTP 线程内同步执行回归。
- 消费守卫：校验项目 `verify.yaml` 的 `regression` 段存在且有效，无效/缺失丢弃信号并记 WARNING；托管判据与 code-review/approve_push 同源——daemon `hosting_state` 为 `stopped`/`unmanaged` 时 POST 端点前置拒绝（400/409），消费侧二次校验并丢弃；单飞——已有回归在跑时忽略请求（返回 409）并记日志，不排队、不并发。
- 执行：回归 worker 在项目根执行 `regression.cmd`（硬超时 = `timeout_seconds`），完成后读取 `regression.output` 的 JUnit XML 解析为结构化结果——总用例数、通过/失败/错误/跳过数，每个失败/错误用例的名称、文件:行、耗时、失败类型与摘要，`long_tests`（单用例 `time` > `long_test_threshold_seconds`），执行时间（started_at/finished_at，UTC）与总耗时。
- 状态判定：命令非零退出但 XML 可解析时以解析结果为准（`status: "failed"`）；命令零退出且无失败/超时为 `"passed"`；XML 不可解析为 `"parse_error"`（附原因），不静默当作全绿；命令被硬超时中止为 `"timeout"` 并标记本次回归未完成。
- 快照落盘 `.fenix/regression/last-run.json`：单文件覆盖式快照（status、计数、耗时、failures、long_tests、阈值、cmd、output、原因），目录为 gitignored 运行时产物，不作为 SPEC 交付物提交；读侧对快照缺失/损坏/非法 JSON 返回明确状态（`never_run` / `parse_error`），不抛 500。
- 周期调度：`admin.regression.enabled`（缺省 false）开启后与每日自省同周期（`admin.self_review.run_at` 时点）触发一次；同自然日防重用独立状态文件 `.fenix/regression/state.json` 的 `last_run_date`（不复用自省/code-review 防重状态）；在跑时单飞跳过；项目无有效 `regression` 段时跳过记日志（`reason: not_configured`）；开关关闭全链路零动作。
- 调度检查点挂既有 admin 巡检循环（不新增线程/定时器），异常只记日志不阻断巡检。
- 回归与主机级全量套件互斥：起跑前抢占 `bin/run_full_suite.py` 的同一把主机级锁（`.fenix/full-suite.lock`，等待上限同其 600s），拿不到即放弃本次执行并记日志，不得与之并发跑第二套全量测试。

## 溯源

- 2026-09-25 add-test-regression-tab（spec/archive/2026-09-25-add-test-regression-tab） — 新增回归触发文件信号与单飞守卫、JUnit XML 解析与状态判定、last-run.json 快照契约、周期调度防重与主机级全量套件互斥
