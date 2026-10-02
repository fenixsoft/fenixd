## ADDED Requirements

### Requirement: 回归页签「自动修复回归问题」按钮
测试回归页签（RegressionTab）SHALL 在「立即执行全量回归」按钮旁（同一右侧按钮区）渲染「自动修复回归问题」按钮。按钮可用性 SHALL 由最近一次回归快照机械判定：快照存在且问题列表非空（failures 非空，或 long_tests 非空，或 status === 'timeout'）时可用；快照缺失（never_run/parse_error）、无异常用例、或触发请求在途时 MUST 禁用。三态引导视图（never_run / parse_error）MUST NOT 渲染本按钮。

#### Scenario: 有异常用例时按钮可用
- **WHEN** 回归快照 status 为 failed 且 failures 含 2 条、long_tests 含 1 条
- **THEN** 「自动修复回归问题」按钮可点击，与「立即执行全量回归」并排渲染于概览卡右下按钮区

#### Scenario: 全绿无长耗时时按钮禁用
- **WHEN** 回归快照 status 为 passed 且 failures 与 long_tests 均为空
- **THEN** 按钮渲染但禁用，悬停提示说明「无异常用例可修复」

#### Scenario: 从未执行过回归时不出按钮
- **WHEN** 快照状态为 never_run 或 parse_error（引导态视图）
- **THEN** 该视图不渲染「自动修复回归问题」按钮（引导态只保留「立即执行全量回归」）

#### Scenario: 触发在途时防重复点击
- **WHEN** 用户已点击按钮且受理判定回链尚未返回
- **THEN** 按钮进入 loading 态并禁用，重复点击不产生第二个信号

### Requirement: 触发与回链 API
后端 SHALL 新增 `POST /api/regression/fix`（query project）：校验项目存在、最近一次回归快照存在且问题列表非空后，原子写信号文件 `.fenix/regression_fix_request.json`（含 `created` ISO 时间戳与 `source: "regression_fix"`）；校验失败 MUST 以稳定错误码拒绝（快照缺失/从未执行/parse_error 损坏 → `regression_never_run`；快照可读但无异常 → `regression_no_issues`），MUST NOT 写信号。SHALL 新增 `GET /api/regression/fix-result`（query project）：读 `.fenix/regression_fix_request_result.json` 原样返回（含 `request_created/triggered/reason/message/finished_at`）；结果文件缺失时返回 `{"status": "none"}` 形态而非 404 报错。

#### Scenario: 受理成功写信号
- **WHEN** POST /api/regression/fix 且快照存在 2 个失败用例
- **THEN** 响应 200，`.fenix/regression_fix_request.json` 被原子写入且含 created 时间戳

#### Scenario: 无异常时拒绝
- **WHEN** POST /api/regression/fix 且快照 status 为 passed 且 failures/long_tests 均空
- **THEN** 响应 400，错误码 `regression_no_issues`，不写信号文件

#### Scenario: 从未执行过回归时拒绝
- **WHEN** POST /api/regression/fix 且 `.fenix/regression/last-run.json` 缺失
- **THEN** 响应 400，错误码 `regression_never_run`，不写信号文件

#### Scenario: 回链结果读取
- **WHEN** GET /api/regression/fix-result 且 daemon 已消费信号并落结果
- **THEN** 返回结果文件全字段；结果文件不存在时返回 `{"status": "none"}` 而非报错

### Requirement: daemon 消费信号并转换为台账条目
daemon 主循环 SHALL 新增 `_check_regression_fix_requests`（1s 粒度，与 `_check_code_fix_requests` 同构）：以 `_consume_request_file` 原子模式消费 `.fenix/regression_fix_request.json` → 读最近一次回归快照 → 将问题列表转换为 code-fix 台账 findings 并经 `upsert_findings` 写入（`review_id` 取 `regression-fix-<signal created>`，`review_kind` 固定 `regression_fix`）→ 经编排器以 `override_enabled=True` 调 `checkpoint()` → 无论结果如何 MUST 原子写 `.fenix/regression_fix_request_result.json`（`request_created` 回链信号 created）。转换映射 SHALL 固化为：kind=failure → category `regression-failure`、kind=error → category `regression-error`、severity 均为 high；long_tests 逐条 → category `regression-long-test`、severity medium；title 取用例名；description 携带分类、耗时与失败 message（超长截断至 500 字）；suggestion 按类目固化文案。编排器未装配 MUST 落 `orchestrator_missing` 结果；消费异常 MUST 落 `dispatch_exception` 结果，均不静默丢信号。

#### Scenario: 失败与错误用例转换入账
- **WHEN** 快照 failures 含 kind=failure 与 kind=error 各 1 条（均有 file/line）
- **THEN** 台账新增 2 条 open 条目，category 分别为 `regression-failure` / `regression-error`，severity 均为 high，title 为用例名，review_kind 为 `regression_fix`

#### Scenario: 长耗时用例转换入账
- **WHEN** 快照 long_tests 含 1 条耗时 42s 的用例
- **THEN** 台账新增 category=`regression-long-test`、severity=medium 的 open 条目，description 含「42s」耗时信息，suggestion 为固化文案

#### Scenario: 触发后投递一批并落结果
- **WHEN** 消费信号、转换入账成功且 code-fix 链空闲（无在飞 run、enabled 守卫被 override 绕过）
- **THEN** `checkpoint(override_enabled=True)` 投递一批，结果文件记录 `triggered: true`

#### Scenario: code-fix 链在飞时条目并入在飞链
- **WHEN** 消费信号时 code-fix 链已有在飞 run，checkpoint 以 `already_running` 拒绝
- **THEN** 转换后的台账条目保持已入账状态（在飞链下一批 select_batch 自然吸收），结果文件记录 `triggered: false`、reason=`already_running`，不丢条目、不静默

#### Scenario: 快照缺失时消费端落结果
- **WHEN** 消费信号时 `.fenix/regression/last-run.json` 已被清理或损坏
- **THEN** 不写台账、不调 checkpoint，结果文件记录 `triggered: false`、reason=`snapshot_missing`

#### Scenario: 编排器缺失不静默
- **WHEN** 消费信号时 agent_runner 未装配 code-fix 编排器
- **THEN** 结果文件记录 `triggered: false`、reason=`orchestrator_missing`

#### Scenario: 消费异常落结果不静默
- **WHEN** 转换或 checkpoint 抛出异常
- **THEN** 结果文件记录 `triggered: false`、reason=`dispatch_exception`，信号已消费不残留

### Requirement: 超时与去重及复发重开语义
整体超时（快照 status === 'timeout'，无逐用例定位）SHALL 转换为单条台账条目：category `regression-timeout`、severity high、file 固定 `.fenix/verify.yaml`（回归硬超时声明落点，作为修复入口锚点）、title 固定「回归整体超时」、description 携带 reason 与输出摘要（摘要由消费端预读快照 output 字段指向的日志文件尾部获得，读取失败置空；截断至 500 字）。去重 SHALL 沿用 `upsert_findings` 的 fingerprint（file+category+title）语义：同用例重复出现仅刷新 last_seen_at/severity/description/suggestion，MUST NOT 覆盖 status/first_seen_at。重开语义：category 以 `regression-` 为前缀的台账条目，若在本次快照问题列表中仍出现（fingerprint 命中）但 status 已非 open，消费转换时 SHALL 重开为 open 并刷新 first_seen_at——保证复发问题可再次触发修复；非 `regression-` 前缀条目（code-review 来源）MUST NOT 被此规则触碰。

#### Scenario: 整体超时转换为单条目
- **WHEN** 快照 status 为 timeout，reason 为「硬超时 1800s 中止」
- **THEN** 台账新增 1 条 category=`regression-timeout` 条目，file 为 `.fenix/verify.yaml`，title 为「回归整体超时」，description 含超时原因摘要

#### Scenario: 同一失败用例重复触发不重复入账
- **WHEN** 同一失败用例（同 file+category+title）已入账，用户再次点击按钮且快照中该用例仍失败
- **THEN** 台账仍只有 1 条对应条目（fingerprint 命中刷新），不产生重复条目

#### Scenario: 已修复条目复发被重开
- **WHEN** 某 `regression-failure` 条目 status 为 resolved，最近快照中该用例（同 fingerprint）再次失败
- **THEN** 消费转换时该条目被重开为 open 并刷新 first_seen_at，后续 checkpoint 可选取修复

#### Scenario: code-review 来源条目不受重开规则影响
- **WHEN** 某 code-review 来源条目（category 非 `regression-` 前缀）status 为 resolved
- **THEN** 消费转换不改变其 status，即使 file/title 恰好同名

### Requirement: 长耗时修复语义固化
`regression-long-test` 条目的 suggestion SHALL 固化为：以不改变测试通过结果为前提，允许优化被测实现或测试代码本身（去冗余 sleep、修慢 fixture、并发化等）。修复 Agent 对长耗时条目的处置 MUST NOT 使原测试由通过变为失败。

#### Scenario: 长耗时条目携带不改行为约束
- **WHEN** 修复 Agent 被投递含 `regression-long-test` 条目的批
- **THEN** 条目 suggestion 明确「不改变测试通过结果」前提与优化手段建议

#### Scenario: 长耗时条目修复后测试仍须通过
- **WHEN** 某长耗时用例经修复批处置且批验证回归重跑
- **THEN** 该用例在回归结果中仍为通过（允许耗时下降），若变为失败则按既有批失败语义处置
