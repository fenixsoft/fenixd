## Deliverables

```yaml
- path: core/verify_contract.py
  kind: modify
- path: core/regression.py
  kind: new
- path: core/admin_monitor.py
  kind: modify
- path: fenixd.py
  kind: modify
- path: core/agent_runner/maintenance_runs.py
  kind: modify
- path: core/agent_runner/runner.py
  kind: modify
- path: core/config.py
  kind: modify
- path: core/dashboard/routes/regression_routes.py
  kind: new
- path: core/dashboard/routes/base.py
  kind: modify
- path: core/dashboard/server.py
  kind: modify
- path: core/dashboard/data/regression.py
  kind: new
- path: core/dashboard/data/__init__.py
  kind: modify
- path: core/dashboard/static/src/pages/projects/components/RegressionTab.tsx
  kind: new
- path: core/dashboard/static/src/pages/projects/list.tsx
  kind: modify
- path: core/dashboard/static/src/pages/settings/components/QualityPanel.tsx
  kind: modify
- path: core/dashboard/static/src/services/dashboard.ts
  kind: modify
- path: agents/administrator.md
  kind: modify
- path: .fenix/config.template.yaml
  kind: modify
- path: docs/help/08-dashboard.md
  kind: modify
- path: tests/test_regression_contract.py
  kind: new
- path: tests/test_regression_execution.py
  kind: new
- path: tests/test_dashboard_regression_api.py
  kind: new
```

## 1. 执行声明：verify.yaml 的 regression 段解析

- [ ] 1.1 在 `core/verify_contract.py` 新增 `RegressionSpec` dataclass（字段：`cmd`、`output`、`timeout_seconds=1800`、`format="junit"`、`long_test_threshold_seconds=10`）
- [ ] 1.2 在 `VerifyContract` dataclass 增设 `regression: Optional[RegressionSpec] = None` 字段；`load_verify_contract` 解析顶层 `regression` 段（缺 `cmd`/`output` 视为无效 → `None` 并记 WARNING；`format` 非 `junit` → 记 WARNING 按 junit 处理）
- [ ] 1.3 阈值/超时非法值（非正数、类型错误）回退缺省（10 / 1800），与 `get_code_review_config` 的缺省回退同范式
- [ ] 1.4 在 `tests/test_regression_contract.py` 覆盖：有效段解析、缺省阈值 10、无段 → None、无效段（缺 cmd/output）→ None + WARNING、非法值回退

## 2. 回归结果解析与快照（core/regression.py）

- [ ] 2.1 新建 `core/regression.py`：`parse_junit_xml(path) -> dict` 宽松递归解析（遍历所有 `testcase`；`time` 缺失记 0；`file` 从 `file`/`classname` 兜底；`failure`/`error`/`skipped` 子元素判定分类），返回 `{total, passed, failed, errors, skipped, failures: [...], cases: [...]}`
- [ ] 2.2 实现 `extract_long_tests(cases, threshold)`：`time > threshold` 的用例（含通过的）归入 `long_tests` 列表（name/file/line/time）
- [ ] 2.3 实现快照读写：`regression_dir(project_root)`、`write_result(project_root, result)` 原子写 `.fenix/regression/last-run.json`、`read_result(project_root)`（缺失 → `{status: "never_run"}`；非法 JSON → `{status: "parse_error", reason}` 非空）
- [ ] 2.4 实现状态文件 `read_state`/`save_state`（`.fenix/regression/state.json` 的 `last_run_date`，独立于自省/code-review 防重状态）
- [ ] 2.5 实现 `run_regression(project_root, spec, logger) -> dict`：按 `spec.cmd` 在项目根执行（shell 字符串 / argv 列表两态）、硬超时 `spec.timeout_seconds` 中止、解析 XML、组装快照（status: passed/failed/timeout/parse_error + 计数 + 时间 + failures + long_tests）、写盘
- [ ] 2.6 在 `tests/test_regression_execution.py` 覆盖：全绿解析、失败/错误分类、长耗时抽取（含通过用例）、超时（进程不结束 → status timeout）、XML 缺失/非法 → parse_error、快照从未执行态

## 3. 执行车道接线（信号消费 + worker）

- [ ] 3.1 在 `core/agent_runner/maintenance_runs.py` 新增 `run_regression(manifest_ctx) -> ...` 执行函数（对齐 `run_code_review` 形态：run_id 前缀 `regression-<epoch>`、独立 token 记账、结果写完后返回），并在 `core/agent_runner/runner.py` 的转发表中注册
- [ ] 3.2 在 `fenixd.py` 新增 `_check_regression_requests()`（对齐 `_check_code_review_requests`：读 `.fenix/regression_request.json` → 校验项目 regression 段 → hosting_state 守卫 → 单飞 → 投递后台 worker），并在主循环（`fenixd.py:579` 邻近）调用
- [ ] 3.3 在 `core/admin_monitor.py` 新增 `_run_regression_checkpoint()`（对齐 `_run_code_review_checkpoint`：`admin.regression.enabled` 守卫 → run_at 时点 → 同自然日防重 → 单飞 → 无 regression 段跳过），在既有巡检循环（`admin_monitor.py:784` 邻近）调用
- [ ] 3.4 在 `core/config.py` 新增 `get_regression_config(config)`（`admin.regression.enabled` 缺省 False，回退范式同 `get_code_review_config`）
- [ ] 3.5 在 `tests/test_regression_execution.py` 补充：JSON 信号消费（有效/无效/未托管/单飞）、检查点守卫矩阵（disabled/before_run_at/already_ran_today/already_running/not_configured）

## 4. Dashboard 后端：路由与数据层

- [ ] 4.1 新建 `core/dashboard/data/regression.py`：`read_regression_result(project_root)` 读快照返回结构化 dict（含 never_run/parse_error 降级）；在 `core/dashboard/data/__init__.py` 导出
- [ ] 4.2 新建 `core/dashboard/routes/regression_routes.py`：`H12RegressionRoutesMixin` 承载 `GET /api/regression/result`（404/never_run/parse_error 三态）、`POST /api/regression/run`（写信号 + 同 code-review 的 400/409 守卫）
- [ ] 4.3 在 `core/dashboard/routes/base.py` 注册两条路由（对齐 `_get_code_review_items`/`_post_code_review_run` 派发形态）；在 `core/dashboard/server.py` 把 `H12RegressionRoutesMixin` 加入 `DashboardHandler` 基类列表
- [ ] 4.4 在 `tests/test_dashboard_regression_api.py` 覆盖：result 有效快照/未知项目 404/never_run/parse_error 不 500；run 受理/未托管 409/已有在跑 409/未配置 400

## 5. Dashboard 前端：项目页分面与设置页开关

- [ ] 5.1 在 `core/dashboard/static/src/services/dashboard.ts` 新增 `RegressionResult` 类型与 `getRegressionResult(project)`、`triggerRegression(project)` 两个接口函数
- [ ] 5.2 新建 `core/dashboard/static/src/pages/projects/components/RegressionTab.tsx`：active 门控拉取；三态渲染（全绿概览卡片：测试路径/用例数/执行时间/耗时；异常态结果表：用例名/文件:行/耗时/分类；never_run/parse_error 引导态）；「立即执行全量回归」按钮
- [ ] 5.3 在 `core/dashboard/static/src/pages/projects/list.tsx` 把 `regression` 占位替换为 `<RegressionTab project={name} active={activeTab === 'regression'} />`
- [ ] 5.4 在 `core/dashboard/static/src/pages/settings/components/QualityPanel.tsx` 新增「周期性全量回归」卡片：`admin.regression.enabled` 开关（读写经既有 GET/POST /api/config），并以只读说明长耗时阈值来源（verify.yaml `regression.long_test_threshold_seconds` 缺省 10）
- [ ] 5.5 执行 `npm run build`（在 `core/dashboard/static`）产出 `dist`（构建产物不入库，属运行时）

## 6. 配置模板与文档

- [ ] 6.1 在 `.fenix/config.template.yaml` 新增 `admin.regression` 段（enabled 缺省 false + 注释说明与 code_review 同周期、需 verify.yaml 有 regression 段）
- [ ] 6.2 在 `docs/help/08-dashboard.md` 补充「测试回归」分面说明（三态展示 + 手动触发）与设置页「质量」页签的周期开关
- [ ] 6.3 在 `agents/administrator.md` 的验证契约起草手册补充：起草 verify.yaml 时若项目有测试体系，MUST 一并生成 `regression` 段（识别语言/框架/测试目录，产出 JUnit XML 的 cmd 与 output），经自证后落位

## 7. 收尾

- [ ] 7.1 全量跑 `tests/` 确认无回归（存量失败除外）
- [ ] 7.2 在 `core/regression.py` 与 `core/verify_contract.py` 的 regression 相关改动处补齐设计理由注释（对齐仓内长注释风格：JUnit XML 跨语言取舍、单快照 Non-Goal、独立防重状态的理由）
