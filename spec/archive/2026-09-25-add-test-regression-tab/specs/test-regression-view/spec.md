# test-regression-view

## ADDED Requirements

### Requirement: 项目页「测试回归」分面展示全量回归结果

项目页「测试回归」分面（`regression` key）MUST 由独立组件承载，active 门控（仅在选中该分面时拉取数据，未选中零请求，对齐 `QualityTab`/`SessionPanel`）。分面数据来自 `GET /api/regression/result?project=<name>`。

分面 MUST 按快照状态渲染三种形态：

1. **全绿（`status: "passed"`）**：以概览卡片展示——测试路径（`cmd`）、用例总数、通过数、执行时间（本地时区）、总耗时（秒/人类可读）；同时若 `long_tests` 非空仍展示长耗时用例表。
2. **存在失败/错误/超时/长耗时用例**：在概览之下渲染结果表格，逐条列出这些用例，列至少含：用例名、文件:行、耗时、分类（失败/错误/超时/长耗时）。失败/错误/超时与长耗时可分区或同表带分类列。
3. **未执行/不可解析（`never_run` / `parse_error`）**：展示引导态（未执行过全量回归 / 结果不可解析 + 原因），MUST NOT 报错或显示空表。

分面 MUST NOT 承载「是否周期执行」的开关配置（配置归设置页「质量」页签），但 MUST 提供「立即执行全量回归」手动触发按钮（POST /api/regression/run）。

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

### Requirement: 设置页「质量」页签配置周期性全量回归

设置页「质量」页签 MUST 新增周期性全量回归配置卡片（与既有「周期性代码审查」卡片同层），承载：

- `admin.regression.enabled`（开关，缺省 false）：开启后与每日自省同周期自动执行全量回归；
- 长耗时阈值（`verify.yaml` 的 `regression.long_test_threshold_seconds`，缺省 10）：本卡片 MUST 以只读方式说明其来源并复用既有 `GET/POST /api/verify-yaml` 端点提供编辑入口；MUST NOT 为该阈值另开第二写入路径（阈值归执行声明，见 design D1/R4——双写会让来源分叉）。

配置读写 MUST 经既有 `GET/POST /api/config` 通道（`admin.regression.enabled` 走 config）；保存后 MUST 与其它质量配置一致地持久化并回显。该键 MUST 在 `core/dashboard/data/config_admin.py` 的 `_SOURCE_KEYS` 登记并纳入写路径 patch 合并（对齐 `admin.code_review` 的四处同款改造），否则前端提交的键被静默丢弃、开关保存后不回显。

#### Scenario: 开关回显与保存

- **WHEN** `admin.regression.enabled` 为 true，打开设置页「质量」页签
- **THEN** 开关回显为开启；关闭并保存后 `GET /api/config` 返回 `admin.regression.enabled == false`

#### Scenario: 缺省不回显为开启

- **WHEN** `admin.regression.enabled` 键缺失
- **THEN** 开关 MUST 回显为关闭（缺省 false，不因键缺失而报错或默认开启）

### Requirement: 回归结果只读 API

框架 MUST 提供 `GET /api/regression/result?project=<name>`：返回 `.fenix/regression/last-run.json` 快照内容（含状态、计数、耗时、failures、long_tests、阈值等）；项目不存在 → 404；快照缺失 → `{status: "never_run"}`；快照损坏 → `{status: "parse_error", reason: <非空>}`。MUST NOT 因快照问题抛 500。

#### Scenario: 读取有效快照

- **WHEN** 项目存在且快照合法
- **THEN** 返回快照全字段（200）

#### Scenario: 未知项目

- **WHEN** query 的 project 不存在
- **THEN** 返回 404

#### Scenario: 快照损坏不 500

- **WHEN** `.fenix/regression/last-run.json` 内容为非法 JSON
- **THEN** 返回 `{status: "parse_error", reason: <非空>}`（200），不抛 500
