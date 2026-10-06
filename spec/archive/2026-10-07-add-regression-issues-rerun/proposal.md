## Why

项目页「测试回归」分面目前只有「立即执行全量回归」一条手动触发路径：fenixd 自托管全量回归 7000+ 用例、数十分钟级。修复或调参后往往只需重跑上次出问题（失败/错误）与长耗时的用例做验证，全量重跑大量浪费。仓库已具备定向子集回归的全部底层机制（add-codefix-targeted-retry 引入的 `_apply_pytest_subset` 命令改写与 `subset_nodeids` 门面参数、junit classname→nodeid 重构），但 dashboard 触发车道没有把它接出来。

## What Changes

- 「测试回归」分面概览卡按钮行新增「立即执行错误/长耗时回归」按钮（`type="primary"` 蓝底白字，「立即执行全量回归」左侧）：只重跑最近一次快照中 `failures`（失败+错误）与 `long_tests`（长耗时）的用例并集（口径已与用户确认；「整体超时」伪行非用例、不可选）。
- 新端点 `POST /api/regression/run-issues`：守卫链与 `/api/regression/run` 一致（404 / 400 未配置 / 409 在跑 / hosting 守卫 / 400 无异常用例），命中后写同一信号文件 `.fenix/regression_request.json`，payload 增 `scope: "issues"`。
- daemon 消费端 `_check_regression_requests`：`scope=="issues"` 时从最近快照计算 nodeid 子集（failures+long_tests 映射、去重），经既有 `subset_nodeids` 门面参数派发；映射失败 / 命令非 pytest 形态 / 旧快照缺 classname → **fail-closed 回退全量**（warning 留痕，对齐定向重试既有语义）。
- 快照新增 `run_scope` 标记（仅子集实际生效时 stamp `issues`）：full-suite 质量门对 `run_scope=="issues"` 快照判本源不可见（fail-open 回落 run 自查值），堵住「子集通过 → 全量门 passed」的白洗通道。
- `extract_long_tests` 补带 `classname`（对齐 failures 侧 add-codefix-targeted-retry 1.1 的补齐做法，nodeid 映射源）；code_fix 侧新增公开映射封装供消费端复用。

## Capabilities

### New Capabilities

- `regression-issues-rerun`: 定向子集回归触发链——run-issues 端点契约、`scope=issues` 信号契约、daemon 消费端子集计算（nodeid 映射/去重/fail-closed 回退）、`run_scope` 快照标记与 full-suite 门不可见规则。

### Modified Capabilities

- `test-regression-view`: 分面概览卡新增「立即执行错误/长耗时回归」按钮（位置/样式/可用性/运行态禁用）与子集快照的「定向子集」标识展示。
- `quality-gates-progress`: full-suite 门数据源①（框架侧回归产物）增加子集快照不可见规则——`run_scope=="issues"` 的快照按不可见处理，不采信为全量回归证据。

## Impact

- 前端：`core/dashboard/static/src/pages/projects/components/RegressionTab.tsx`、`core/dashboard/static/src/services/dashboard.ts`、新增前端测试 `core/dashboard/static/tests/regressionTab.test.mjs`
- 路由：`core/dashboard/routes/regression_routes.py`（新端点 + 守卫链抽共享 helper）、`core/dashboard/routes/base.py`（注册）
- 消费端：`fenixd.py` `_check_regression_requests`（scope 分支）
- 核心：`core/regression.py`（extract_long_tests 带 classname、run_scope 透传 stamp）、`core/agent_runner/maintenance_runs.py`（透传 + 日志文案泛化）、`core/code_fix.py`（公开映射封装）
- 门禁：`core/dashboard/data/quality_gates.py` `_full_suite_product_status`（子集快照不可见）
- 测试：`tests/test_dashboard_regression_api.py`、`tests/test_regression_execution.py`、`tests/test_quality_gates_progress.py` 扩展
- 无破坏性变更：信号文件键增量向后兼容（无 scope 键按全量消费），既有端点/快照读侧零迁移。
