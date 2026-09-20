## Why

项目页已有「测试回归」分面（`add-project-detail-tabs` 预留的 `regression` key，当前 `children: null` 占位），但至今没有任何数据源——用户无法在 Dashboard 看到全量回归结果，也不知道"这次改动跑没跑全量、多慢、有没有挂起"。同时全量回归目前只能由 implementer agent 在 run 内手工跑（`bin/run_full_suite.py`），没有独立的周期调度与历史留存。这导致：回归质量不可观测、慢测试/超时测试无集中视图、也无从周期性回归。

## What Changes

- **新增 `.fenix/verify.yaml` 的 `regression` 段**：声明全量回归如何执行（`cmd`）、硬超时（`timeout_seconds`）、结果格式（`format: junit`，JUnit XML 为跨语言统一标准）、长耗时用例阈值（`long_test_threshold_seconds`，缺省 10）。框架为**通用开发框架**，回归命令不硬编码为 pytest——由项目声明；命令须产出 JUnit XML（pytest `--junit-xml`、jest-junit、go-junit-report 等均可）。
- **AI 自动起草 `regression` 段**：`verify.yaml` 无 `regression` 段（或文件整体缺失）时，administrator agent 在既有 verify 契约起草流程中一并探测项目测试体系（语言/测试框架/测试目录）并生成该段，经 `bin/fenix_verify_contract.py` 自证后落位（复用 add-verify-contract-autodraft 既有通道）。
- **新增回归执行车道**：daemon 消费 `POST /api/regression/run` 写入的 `.fenix/regression_request.json` 文件信号（对齐 code-review 的「dashboard 原子写 → daemon 主循环消费」范式），在后台执行 `regression.cmd`，解析 JUnit XML，结果写入 `.fenix/regression/last-run.json`（单飞、防重、与 code-review 同构）。
- **新增周期调度**：`admin.regression.enabled` 开关（与 `admin.code_review.enabled` 同形制），开启后与每日自省同周期（`admin.self_review.run_at` 时点）自动执行一次全量回归，同一自然日防重。
- **项目页「测试回归」分面**：替换 `list.tsx` 现有 `regression` 占位为 `RegressionTab` 组件，active 门控拉取 `GET /api/regression/result`。全绿时展示概览（测试路径、用例总数、执行时间、耗时）；存在失败/超时/长耗时用例时，在结果表中逐条展示这些用例（名称、文件:行、耗时、分类）。
- **设置页「质量」页签新增开关**：`admin.regression.enabled` + 长耗时阈值等，与「周期性代码审查」卡片同层（配置归设置页，分面只读展示 + 手动触发）。

## Capabilities

### New Capabilities

- `test-regression-declaration`: 全量回归的执行声明（`verify.yaml` 的 `regression` 段：cmd / timeout_seconds / format / long_test_threshold_seconds）与 AI 自动起草（探测项目测试体系并生成该段、自证、落位）。
- `test-regression-execution`: 回归执行车道（手动信号消费、每日周期调度检查点、JUnit XML 解析、结果快照落盘 `.fenix/regression/last-run.json`、单飞与防重），及只读结果 API `GET /api/regression/result`、触发 API `POST /api/regression/run`。
- `test-regression-view`: 项目页「测试回归」分面（全绿概览 + 失败/超时/长耗时用例表）与设置页「质量」页签的周期开关（`admin.regression.enabled`）配置读写。

### Modified Capabilities

（无——`spec/specs/` 当前为空，本次全部为新媒体；对 `verify.yaml` 的结构扩展通过 `test-regression-declaration` 新能力承载，不构成既有 spec 文件的需求变更。）

## Impact

- **配置契约**：`.fenix/verify.yaml` 新增可选 `regression` 段（旧文件零迁移，缺省回退「未配置回归」）；`.fenix/config.yaml` 新增 `admin.regression.*` 段。
- **代码**：
  - `core/verify_contract.py`（新增 `RegressionSpec` 解析 + dataclass 字段）
  - `core/regression.py`（新模块：JUnit XML 解析、结果快照读写、状态文件）
  - `core/admin_monitor.py`（新增 `_run_regression_checkpoint`，挂既有巡检循环）
  - `fenixd.py`（新增 `_check_regression_requests` 信号消费，与 `_check_code_review_requests` 同构）
  - `core/agent_runner/maintenance_runs.py`（`run_regression` 执行函数，对齐 `run_code_review`）
  - `core/dashboard/routes/regression_routes.py`（新路由：result / run / config）
  - `core/dashboard/data/regression.py`（读侧组装）
  - 前端 `core/dashboard/static/src/pages/projects/components/RegressionTab.tsx`（新）、`pages/projects/list.tsx`（替换占位）、`pages/settings/components/QualityPanel.tsx`（新增开关）、`services/dashboard.ts`（新接口）
  - `agents/administrator.md`（起草手册新增 `regression` 段）
- **兼容性**：`verify.yaml` 无 `regression` 段时，分面显示「未配置全量回归」引导态，不报错；周期开关缺省关闭，零动作。
