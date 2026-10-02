# regression-issues-rerun

## ADDED Requirements

### Requirement: 定向子集回归触发端点

框架 MUST 提供 `POST /api/regression/run-issues?project=<name>`（不消费请求体，与同族端点一致）：校验通过后原子写 `.fenix/regression_request.json` 文件信号，payload 为 `{"source": "dashboard", "requested_at": <UTC ISO>, "scope": "issues"}`，返回 `200 {ok: true, requested_at}`。

守卫链与 `POST /api/regression/run` 一致，拒绝以稳定错误码表达（`_coded_error`，前端按 code 分支）：

- 项目不存在 → 404
- verify.yaml 无有效 regression 段 → 400 `regression_not_configured`
- 已有回归在跑（marker 新鲜度判定）→ 409 `regression_already_running`
- daemon 未受 supervisor 托管 / 未运行 → 409 / 400（hosting 守卫，与 run 端点共用实现）
- 最近快照缺失/损坏/不可解析 → 400 `regression_never_run`
- 快照可读但 failures 与 long_tests 均空且 status 非 timeout → 400 `regression_no_issues`
- 信号文件已存在（并发第二 POST 或上一信号未消费）→ 409 `regression_request_pending`

两端点重复的守卫链 MUST 收敛为共享实现（MUST NOT 复制两份同构守卫）。

#### Scenario: 受理成功写 scope 信号

- **WHEN** 项目契约有效、无回归在跑、快照含 1 个失败用例，POST run-issues
- **THEN** 返回 `200 {ok: true, requested_at}`，`.fenix/regression_request.json` 存在且 `scope == "issues"`、`requested_at` 与响应一致

#### Scenario: 无异常用例拒绝

- **WHEN** 快照 `status: "passed"` 且 failures/long_tests 均空，POST run-issues
- **THEN** 返回 400、`code == "regression_no_issues"`，MUST NOT 写信号文件

#### Scenario: 快照缺失拒绝

- **WHEN** `.fenix/regression/last-run.json` 不存在，POST run-issues
- **THEN** 返回 400、`code == "regression_never_run"`，MUST NOT 写信号文件

#### Scenario: 回归在跑拒绝

- **WHEN** `.fenix/regression/.running` marker 新鲜（运行中），POST run-issues
- **THEN** 返回 409、`code == "regression_already_running"`，MUST NOT 写信号文件

### Requirement: 消费端子集计算与 fail-closed 回退

daemon 主循环 `_check_regression_requests` 消费信号时：payload `scope == "issues"` MUST 触发定向子集路径——读最近快照，将 `failures`（失败+错误）与 `long_tests`（长耗时）条目映射为 nodeid 并集（按 nodeid 去重），以既有门面参数 `subset_nodeids` 派发 `run_regression`；payload 无 `scope` 或 `scope` 未知时 MUST 按全量消费（向后兼容）。

子集计算 MUST fail-closed：任一用例映射失败、映射结果为空、或命令非 pytest 形态（`_apply_pytest_subset` 返回 None）时，MUST 回退跑全量并记 WARNING 日志留痕——MUST NOT 静默漏跑用例、MUST NOT 派发空跑。时效分档（陈旧信号不执行）与单飞守卫沿用既有消费端语义不变。

#### Scenario: 子集派发

- **WHEN** 信号 `scope=="issues"`，快照含 2 个失败用例 + 1 个长耗时用例（均带可映射 classname），命令为 pytest 形态
- **THEN** `run_regression` 收到去重后的 nodeids 子集（`subset_nodeids` 非空），快照按子集结果落盘

#### Scenario: 映射失败回退全量

- **WHEN** 信号 `scope=="issues"`，快照 failures 条目缺 `classname`（存量旧快照）
- **THEN** 记 WARNING 并按全量回归派发（`subset_nodeids` 不生效），MUST NOT 丢弃请求

#### Scenario: 非 pytest 命令回退全量

- **WHEN** 信号 `scope=="issues"`，verify.yaml regression.cmd 为非 pytest 形态（如 jest）
- **THEN** 记 WARNING 并按全量回归派发（fail-closed，与 targeted-retry 同语义）

#### Scenario: 无 scope 键按全量消费

- **WHEN** 信号 payload 只有 `source`/`requested_at`（存量写手）
- **THEN** 按全量回归消费，行为与既有完全一致

### Requirement: 子集快照 run_scope 标记

当且仅当子集改写实际生效（`_apply_pytest_subset` 成功）时，本次运行落盘的快照 MUST 携带 `run_scope: "issues"`；回退全量的运行落盘快照 MUST NOT 携带该标记（真全量可被门禁正常采信）。全量触发（无 scope 或回退）落盘快照与既有字段完全兼容，读侧零迁移。

#### Scenario: 子集生效落标记

- **WHEN** 子集改写成功的回归完成落盘
- **THEN** 快照含 `run_scope == "issues"`，其余字段（计数/failures/long_tests/指纹）照常

#### Scenario: 回退全量不落标记

- **WHEN** scope=issues 信号因映射失败回退全量并完成落盘
- **THEN** 快照 MUST NOT 含 `run_scope` 键（或值非 issues），门禁按全量产物采信

### Requirement: full-suite 门对子集快照不可见

门禁读侧（`_full_suite_product_status`）对 `run_scope == "issues"` 的框架侧回归产物 MUST 判本源不可见（与指纹陈旧同款 fail-open 回落：回落 run 内自查值/既有逐级回落，MUST NOT 抛异常或产生 error）。子集通过 MUST NOT 使 full-suite 门呈现 passed。

#### Scenario: 子集快照不洗白全量门

- **WHEN** 快照 `run_scope=="issues"`、`status=="passed"`、指纹匹配当前分支
- **THEN** full-suite 门不采信该产物（按数据源优先级回落），MUST NOT 呈现「passed（子集）」

#### Scenario: 全量快照不受影响

- **WHEN** 快照无 `run_scope` 键（全量产物）、指纹匹配
- **THEN** full-suite 门按既有规则正常采信，行为零变化
