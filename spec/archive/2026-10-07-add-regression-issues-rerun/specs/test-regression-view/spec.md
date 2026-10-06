# test-regression-view 能力增量（add-regression-issues-rerun）

> 分面新增第二个手动触发按钮（定向子集回归）与子集快照标识；三态渲染、表格结构、全量触发按钮与其余 Scenario 全部保持不变（原文各 Scenario 继续有效）。

## MODIFIED Requirements

### Requirement: 项目页「测试回归」分面展示全量回归结果

项目页「测试回归」分面（`regression` key）MUST 由独立组件承载，active 门控（仅在选中该分面时拉取数据，未选中零请求，对齐 `QualityTab`/`SessionPanel`）。分面数据来自 `GET /api/regression/result?project=<name>`。

分面 MUST 按快照状态渲染三种形态：

1. **全绿（`status: "passed"`）**：以概览卡片展示——测试路径（`cmd`）、用例总数、通过数、执行时间（本地时区）、总耗时（秒/人类可读）；同时若 `long_tests` 非空仍展示长耗时用例表。
2. **存在失败/错误/超时/长耗时用例**：在概览之下渲染结果表格，逐条列出这些用例，列至少含：用例名、文件:行、耗时、分类（失败/错误/超时/长耗时）。失败/错误/超时与长耗时可分区或同表带分类列。
3. **未执行/不可解析（`never_run` / `parse_error`）**：展示引导态（未执行过全量回归 / 结果不可解析 + 原因），MUST NOT 报错或显示空表。

分面 MUST NOT 承载「是否周期执行」的开关配置（配置归设置页「质量」页签），但 MUST 提供「立即执行全量回归」手动触发按钮（POST /api/regression/run）。

分面概览卡按钮行 MUST 另提供「立即执行错误/长耗时回归」按钮（POST /api/regression/run-issues，见 `regression-issues-rerun` 能力）：位于「立即执行全量回归」旁（其左侧）、`type="primary"`（蓝底白字）。可用性机械判定 = 快照 `failures` 或 `long_tests` 非空（即结果表存在可重跑行；「整体超时」伪行非用例、不计入），不可用时禁用并以 Tooltip 说明；`running` / 等待启动期间与全量按钮同口径禁用；受理成功后进入与全量触发一致的等待启动过渡态（轮询/进度条接管）。

快照携带 `run_scope == "issues"` 时，分面概览卡 MUST 展示「定向子集」标识（状态 Tag 旁）与口径说明（用例总数按子集口径；单快照覆盖语义，再跑全量即恢复），MUST NOT 让子集计数被误读为全量。

#### Scenario: 全绿概览

- **WHEN** 快照 `status: "passed"`，含 cmd、总数 5045、耗时 200、started/finished
- **THEN** 分面展示概览卡片：测试路径、用例数 5045、执行时间、耗时 200s；无失败行

#### Scenario: 失败/超时/长耗时用例表

- **WHEN** 快照含 2 个失败用例 + 1 个超时 + 3 个长耗时用例
- **THEN** 分面在概览下方以表格列出这些用例，含名称、文件:行、耗时、分类列

#### Scenario: 未执行过

- **WHEN** 快照返回 `{status: "never_run"}`
- **THEN** 分面展示「尚未执行过全量回归」引导态（含手动触发按钮），不显示空表

#### Scenario: 手动触发按钮

- **WHEN** 用户点击分面「立即执行全量回归」
- **THEN** 前端调用 POST /api/regression/run，成功后提示已受理并进入运行中态（轮询快照更新）

#### Scenario: 定向子集按钮受理

- **WHEN** 快照含 1 个失败用例 + 2 个长耗时用例，用户点击「立即执行错误/长耗时回归」
- **THEN** 按钮以 primary 形态呈现且可点击；点击后前端调用 POST /api/regression/run-issues，成功后提示已受理并进入与全量触发一致的等待启动过渡态

#### Scenario: 全绿时定向子集按钮禁用

- **WHEN** 快照 `status: "passed"` 且 failures/long_tests 均空
- **THEN** 「立即执行错误/长耗时回归」禁用，悬停 Tooltip 说明无异常用例可重跑；「立即执行全量回归」不受影响

#### Scenario: 子集快照标识

- **WHEN** 快照 `run_scope == "issues"`、`total == 3`
- **THEN** 概览卡展示「定向子集」Tag 与口径说明（总数 3 为子集口径），MUST NOT 呈现为全量结果
