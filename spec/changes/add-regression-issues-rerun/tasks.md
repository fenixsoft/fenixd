## Deliverables

```yaml
- path: core/regression.py
  kind: modify
- path: core/code_fix.py
  kind: modify
- path: core/agent_runner/maintenance_runs.py
  kind: modify
- path: fenixd.py
  kind: modify
- path: core/dashboard/routes/regression_routes.py
  kind: modify
- path: core/dashboard/routes/base.py
  kind: modify
- path: core/dashboard/data/quality_gates.py
  kind: modify
- path: core/dashboard/static/src/services/dashboard.ts
  kind: modify
- path: core/dashboard/static/src/pages/projects/components/RegressionTab.tsx
  kind: modify
- path: tests/test_regression_execution.py
  kind: modify
- path: tests/test_codefix_targeted_retry.py
  kind: modify
- path: tests/test_dashboard_regression_api.py
  kind: modify
- path: tests/test_quality_gates_progress.py
  kind: modify
- path: core/dashboard/static/tests/regressionTab.test.mjs
  kind: new
- path: core/dashboard/static/dist/index.html
  kind: reference
```

## 1. 核心层：classname 补齐、映射封装与 run_scope 标记

- [ ] 1.1 `core/regression.py` `extract_long_tests`：条目补带 `classname`（对齐 failures 侧 add-codefix-targeted-retry 1.1 的补齐做法，cases 侧本就携带）；`tests/test_regression_execution.py` 补用例：长耗时条目含 classname、缺 classname 的存量快照不受影响（读侧宽松）
- [ ] 1.2 `core/regression.py` `run_and_write_regression` 增可选参 `run_scope: str | None = None`（缺省 None，既有调用点零迁移）：非 None 时在 `write_result` 前把 `run_scope` stamp 进结果 dict（一个 stamp 点覆盖全部状态路径）；`tests/test_regression_execution.py` 补用例：传 issues 时快照含 `run_scope=="issues"`、不传时无该键
- [ ] 1.3 `core/code_fix.py` 新增公开封装 `map_snapshot_issues_to_nodeids(snapshot, exec_root=None) -> tuple[list, bool]`：`failures` + `long_tests` 构造映射条目（**剥离 `file` 键**——pytest junitxml 不产 file 属性、快照 file 为点分 classname 兜底，带入会被 `_map_junit_failures_to_nodeids` 的 file 一致性校验恒判失败；long_tests 条目补 `kind: "long"`），复用 `_map_junit_failures_to_nodeids`，结果按 nodeid 去重（failures 与 long_tests 同例）且保持稳定顺序；任一条目不可映射（如缺 classname）→ `(空或部分?, ok=False)` 整体 fail-closed。`tests/test_codefix_targeted_retry.py` 补用例：并集去重、file=classname 兜底形态可映射成功（剥离 file 生效）、缺 classname 整体 ok=False、非 dict 条目 ok=False

## 2. 门面与消费端：scope 分支派发

- [ ] 2.1 `core/agent_runner/maintenance_runs.py` `run_regression` 门面：`_apply_pytest_subset` 改写成功时向 `run_and_write_regression` 传 `run_scope="issues"`，回退全量分支 MUST NOT 传；日志文案「code-fix 定向子集回归」泛化为「定向子集回归」（回退分支文案同步泛化）；测试补断言：子集生效时封装层收到 run_scope=issues、回退时收到 None（mock `run_and_write_regression` 捕获入参）
- [ ] 2.2 `fenixd.py` `_check_regression_requests`：payload `scope == "issues"` 分支——`core.regression.read_result` 读快照 → `map_snapshot_issues_to_nodeids(snapshot, PROJECT_ROOT)` 算子集（exec_root 传 PROJECT_ROOT 供在盘测试文件探测） → 命中且非空以 `subset_nodeids=<nodeids>` 派发 `self.agent_runner.run_regression(spec, reason="manual", subset_nodeids=...)`；映射失败/结果空 → WARNING 日志留痕并按全量派发（fail-closed，MUST NOT 丢弃请求、MUST NOT 派发空跑）；无 `scope`/未知 `scope` 按既有全量路径（行为逐字节不变）；时效分档/单飞/hosting 守卫全部沿用不动。`tests/test_regression_execution.py` 补用例：scope=issues 派发带子集、缺 classname 回退全量且请求不丢、无 scope 兼容全量

## 3. 端点层：run-issues 与守卫收敛

- [ ] 3.1 `core/dashboard/routes/regression_routes.py`：`_api_regression_run` 与新端点的重复守卫链（404 / 400 `regression_not_configured` / 409 `regression_already_running` / hosting 守卫）收敛为 mixin 内共享 helper（对齐 item e22bfec7b9ee 收敛先例），run 端点行为零变化；新增 `_api_regression_run_issues`：快照校验（`core.regression.read_result`，缺失/损坏/parse_error → 400 `regression_never_run`；failures/long_tests 均空且 status 非 timeout → 400 `regression_no_issues`，判定口径对齐 fix 端点 has_issues）→ 写 `.fenix/regression_request.json` payload `{"source": "dashboard", "requested_at": <UTC ISO>, "scope": "issues"}`（三步原子独占写走既有 `_write_trigger_signal`）→ `200 {ok, requested_at}`；冲突 409 `regression_request_pending`、写入失败 500 文案与 run 端点同款
- [ ] 3.2 `core/dashboard/routes/base.py`：注册 `("exact", "/api/regression/run-issues", _post_regression_run_issues)`（POST 路由表 regression 段）
- [ ] 3.3 `tests/test_dashboard_regression_api.py` 补用例：受理成功写 scope=issues 信号（requested_at 与响应一致）、`regression_no_issues` 拒绝且不写信号、`regression_never_run` 拒绝、`regression_already_running` 409、信号已存在 409 `regression_request_pending`、既有 run 端点守卫收敛后行为回归（各守卫分支抽查）

## 4. 质量门禁：子集快照不可见

- [ ] 4.1 `core/dashboard/data/quality_gates.py` `_full_suite_product_status`：在 status 白名单判定之前，快照为 dict 且 `data.get("run_scope") == "issues"` → 返回 `(None, "")`（`data` 非 dict 一并按不可见返回 `(None, "")`——`read_result` 对合法 JSON 非 dict 载荷原样返回，不做 isinstance 守卫直取 `.get` 会 AttributeError 穿透 fail-open 契约；本源不可见，沿用既有 fail-open 逐级回落，MUST NOT 抛异常）；`tests/test_quality_gates_progress.py` 补用例：子集快照（issues + passed + 指纹匹配）不呈现 passed（回落 pending/自查值）、全量快照（无 run_scope）行为零变化

## 5. 前端：按钮与子集快照标识

- [ ] 5.1 `core/dashboard/static/src/services/dashboard.ts`：新增 `triggerRegressionIssues(project)`（POST `/api/regression/run-issues?project=`，空对象 body 与同族一致，返回 `{ok, requested_at}`）；`RegressionResult` 接口增 `run_scope?: string`
- [ ] 5.2 `core/dashboard/static/src/pages/projects/components/RegressionTab.tsx`：主态概览卡按钮行「自动修复回归问题」与「立即执行全量回归」之间插入新按钮——`type="primary"`（蓝底白字）、文案「立即执行错误/长耗时回归」、Tooltip「只重跑失败/错误/长耗时的用例；无法定向时自动回退全量」；可用性机械判定 = 快照 `failures` 或 `long_tests` 非空（不可用禁用，span+Tooltip「无异常用例可重跑」，对齐自动修复按钮禁用态范式）；`running`/`awaitingStart` 与全量按钮同口径禁用；`handleTriggerIssues` 对齐 `handleTrigger` 受理范式（ApiError 按稳定 code 分支：`regression_already_running`/`regression_not_configured`/`regression_never_run`/`regression_no_issues`/`regression_request_pending`，受理成功 → awaitingStart 过渡态 + 经 loadResultRef 刷新）；快照 `run_scope=="issues"` 时概览卡状态 Tag 旁展示「定向子集」Tag 与口径说明（用例总数按子集口径，再跑全量即恢复）
- [ ] 5.3 新建 `core/dashboard/static/tests/regressionTab.test.mjs`：按钮渲染位置与 primary 形态、全绿时禁用 + 有异常行时可用、点击调用 run-issues、受理后进入等待启动态、`run_scope=="issues"` 快照渲染「定向子集」Tag

## 6. 构建与回归

- [ ] 6.1 前端构建产物重建落位 `core/dashboard/static/dist/`（reference）
- [ ] 6.2 后端测试全绿：`python3 -m pytest tests/test_dashboard_regression_api.py tests/test_regression_execution.py tests/test_codefix_targeted_retry.py tests/test_quality_gates_progress.py tests/test_regression_autofix.py tests/test_regression_contract.py -x -q`
- [ ] 6.3 前端测试全绿：`core/dashboard/static/tests/` 全量
