## Deliverables

```yaml
- path: core/code_fix.py
  kind: modify
- path: fenixd.py
  kind: modify
- path: core/dashboard/routes/regression_routes.py
  kind: modify
- path: core/dashboard/static/src/services/dashboard.ts
  kind: modify
- path: core/dashboard/static/src/pages/projects/components/RegressionTab.tsx
  kind: modify
- path: tests/test_regression_autofix.py
  kind: new
- path: core/dashboard/static/dist/index.html
  kind: reference
```

## 1. 回归快照→台账 findings 转换与复发重开（core/code_fix.py）

- [ ] 1.1 新增纯函数 `convert_regression_snapshot_to_findings(snapshot)`：按 spec 固化映射——failures 逐条（kind=failure→category `regression-failure` / kind=error→`regression-error`，severity high）、long_tests 逐条（`regression-long-test`，severity medium）、status=timeout 时追加单条（`regression-timeout`，severity high，file 固定 `.fenix/verify.yaml`，title「回归整体超时」，description 含 reason 与输出摘要——摘要经可选参数 `output_excerpt` 由消费端传入（预读快照 output 字段指向的日志文件尾部，读取失败置空），函数内截断 500 字，保持纯函数可单测）；title 取用例名，description 携带分类、耗时与失败 message（截断 500 字），suggestion 按类目固化文案（long 类须含「不改变测试通过结果」前提与优化手段建议）；输入容错：snapshot 缺失/字段缺失不抛异常返回空列表。
- [ ] 1.2 新增 `reopen_regression_items(project_root, live_keys)`：仅 category 以 `regression-` 为前缀、fingerprint/键命中本次快照问题集且 status 非 open 的条目重开为 open 并刷新 first_seen_at；读-改-写 + flock 与台账写同锁；非 `regression-` 前缀条目零触碰。
- [ ] 1.3 为 1.1/1.2 写单测（tests/test_regression_autofix.py，参照 test_code_fix_manual_trigger.py 的替身与隔离范式）：覆盖映射各分支、超长 message 截断、snapshot 损坏容错、重开命中/不命中/非 regression 前缀不触碰。

## 2. 触发与回链 API（core/dashboard/routes/regression_routes.py）

- [ ] 2.1 新增 `POST /api/regression/fix`（query project）：校验项目存在、`.fenix/regression/last-run.json` 快照存在且问题列表非空（failures 非空或 long_tests 非空或 status=timeout）→ 原子写 `.fenix/regression_fix_request.json`（含 created ISO 时间戳与 source）；校验失败以 `_coded_error` 拒绝（快照缺失/never_run/parse_error 损坏 → `regression_never_run`，快照可读但无异常 → `regression_no_issues`；parse_error 快照无 failures 键，不落 no_issues 以免误导），不写信号。
- [ ] 2.2 新增 `GET /api/regression/fix-result`（query project）：读 `.fenix/regression_fix_request_result.json` 原样返回，缺失返回 `{"status": "none"}`。
- [ ] 2.3 为 2.1/2.2 写单测（tests/test_regression_autofix.py，参照 test_dashboard_regression_api.py 的路由测试范式）：受理写信号、两拒绝分支错误码、结果文件读取与缺失兜底。

## 3. daemon 信号消费（fenixd.py）

- [ ] 3.1 新增 `_check_regression_fix_requests` 并挂载主循环（1s 粒度，紧邻 `_check_code_fix_requests`）：`_consume_request_file` 原子消费 → 读 PROJECT_ROOT 下 `.fenix/regression/last-run.json`（与编排器及既有 `_check_regression_requests` 同根；信号 query project 仅作受理校验，不参与消费定位；缺失/损坏→落 `snapshot_missing` 结果不继续）→ 预读快照 output 字段指向的日志文件尾部 500 字（读取失败置空）作 `output_excerpt` → `convert_regression_snapshot_to_findings` + `upsert_findings`（review_id=`regression-fix-<created>`，review_kind=`regression_fix`）+ `reopen_regression_items` → 编排器 `checkpoint(override_enabled=True)` → 无论结果原子写 `.fenix/regression_fix_request_result.json`（request_created 回链）；编排器未装配落 `orchestrator_missing`；异常落 `dispatch_exception`；checkpoint 拒绝（如 already_running）如实回传 reason 且不回滚台账。`review_kind=regression_fix` 为新值：已核实 `upsert_findings` 仅透传存储、无枚举校验，零破坏；`core/code_review.py` docstring 的 review_kind 取值列表未含新值属文档滞后，不要求同步（如顺手补注不得改逻辑）。
- [ ] 3.2 为 3.1 写单测（tests/test_regression_autofix.py）：消费→入账→triggered=true 全链路、snapshot_missing / orchestrator_missing / dispatch_exception 三兜底、already_running 拒绝时条目保留、信号消费后不残留。

## 4. 前端按钮与回链反馈（services/dashboard.ts + RegressionTab.tsx）

- [ ] 4.1 services/dashboard.ts 新增 `fixRegression(project)` 与 `getRegressionFixResult(project)` 封装（ApiError code 透传，对齐既有 triggerRegression 形态）。
- [ ] 4.2 RegressionTab 概览卡右下按钮区新增「自动修复回归问题」按钮（「立即执行全量回归」旁）：可用性由快照机械判定（failures 非空或 long_tests 非空或 status=timeout；never_run/parse_error 引导态不渲染）；点击 POST → loading 防重复 → 轮询 fix-result（request_created 比对本轮）→ triggered 弹成功提示并指引质量页签看进度、非 triggered 按 reason 分支提示（already_running/no_open_items/regression 契约缺失等）；全绿禁用态悬停提示「无异常用例可修复」；轮询沿用 QualityTab `getCodeFixRunResult` 既有范式（request_created 守卫 + 终态停轮），并设轮询上限（如 30s），超限提示「daemon 未响应，请确认 daemon 运行中」后恢复按钮；遵守项目 lint（禁宽松相等、禁嵌套三元）。
- [ ] 4.3 `npm run build` 通过（dist 为运行时重建产物，构建成功即视为交付；worktree 内执行）。

## 5. 收尾验证

- [ ] 5.1 运行 tests/test_regression_autofix.py 及既有相关回归（test_code_fix_manual_trigger.py、test_dashboard_regression_api.py、test_regression_execution.py）全部通过，全库 lint 通过。
