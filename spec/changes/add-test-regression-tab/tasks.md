## Deliverables

```yaml
- path: core/verify_contract.py
  kind: modify
- path: bin/fenix_verify_contract.py
  kind: modify
- path: core/verify_contract_template.yaml
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
- path: core/dashboard/data/config_admin.py
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
- path: docs/help/09-config.md
  kind: modify
- path: docs/help/10-artifacts.md
  kind: modify
- path: core/dashboard/static/dist/index.html
  kind: reference
- path: tests/test_regression_contract.py
  kind: new
- path: tests/test_regression_execution.py
  kind: new
- path: tests/test_dashboard_regression_api.py
  kind: new
```

> 说明：`core/dashboard/static/dist/`（前端构建产物，被 `.gitignore:30` 的 `dist/` 排除、
> 主树未跟踪）不入库，属 `reference` 非交付物；仅需保证 `npm run build` 通过
> （与 `add-code-review-agent-and-quality-tab` tasks.md:48 同款处置）。
> `.fenix/regression/last-run.json`、`.fenix/regression/state.json` 与
> `.fenix/regression_request.json` 均为 gitignored 运行时产物，不进声明段。

## 1. 执行声明：verify.yaml 的 regression 段解析

- [ ] 1.1 在 `core/verify_contract.py` 新增 `RegressionSpec` dataclass（字段：`cmd`、`output`、`timeout_seconds=1800`、`format="junit"`、`long_test_threshold_seconds=10`）
- [ ] 1.2 在 `VerifyContract` dataclass 增设 `regression: Optional[RegressionSpec] = None` 字段；`load_verify_contract` 解析顶层 `regression` 段（缺 `cmd`/`output` 视为无效 → `None` 并记 WARNING；`format` 非 `junit`（含显式声明其它格式）同样视为整段无效 → `None` + WARNING，对齐 design D2 的「只支持 junit」边界，不得静默按 junit 处理）
- [ ] 1.3 阈值/超时非法值（非正数、类型错误）回退缺省（10 / 1800），与 `get_code_review_config` 的缺省回退同范式
- [ ] 1.4 在 `tests/test_regression_contract.py` 覆盖：有效段解析、缺省阈值 10、无段 → None、无效段（缺 cmd/output）→ None + WARNING、非法值回退
- [ ] 1.5 在 `core/verify_contract_template.yaml` 增补 `regression` 段示例（惰性注释形态，与既有 prepare/serve/ready 同款）：模板单一来源同时供 `fenix-init` 生成与 setup skill 复制（`core/dashboard/routes/settings_routes.py:315` 的「插入模板」也读它），漏改会让新项目模板与解析器口径分叉
- [ ] 1.6 在 `bin/fenix_verify_contract.py` 更新 docstring 并增补 regression 段的**可选**自证：`regression` 段存在时按 `cmd` 跑一次确认 `output` 产出可解析 JUnit XML，结果作为独立一行输出（不计入退出码，prepare/serve/ready 三段判定语义不变——避免 1800s 级全量回归拖垮既有三段自证门与 2 轮上限流程）；探测失败必须走「省略该段」而非写错命令

## 2. 回归结果解析与快照（core/regression.py）

- [ ] 2.1 新建 `core/regression.py`：`parse_junit_xml(path) -> dict` 宽松递归解析（遍历所有 `testcase`；`time` 缺失记 0；`file` 从 `file`/`classname` 兜底；`failure`/`error`/`skipped` 子元素判定分类），返回 `{total, passed, failed, errors, skipped, failures: [...], cases: [...]}`
- [ ] 2.2 实现 `extract_long_tests(cases, threshold)`：`time > threshold` 的用例（含通过的）归入 `long_tests` 列表（name/file/line/time）
- [ ] 2.3 实现快照读写：`regression_dir(project_root)`、`write_result(project_root, result)` 原子写 `.fenix/regression/last-run.json`、`read_result(project_root)`（缺失 → `{status: "never_run"}`；非法 JSON → `{status: "parse_error", reason}` 非空）
- [ ] 2.4 实现状态文件 `read_state`/`save_state`（`.fenix/regression/state.json` 的 `last_run_date`，独立于自省/code-review 防重状态）
- [ ] 2.5 实现 `run_regression(project_root, spec, logger) -> dict`：按 `spec.cmd` 在项目根执行（shell 字符串 / argv 列表两态）、硬超时 `spec.timeout_seconds` 中止、解析 XML、组装快照（status: passed/failed/timeout/parse_error + 计数 + 时间 + failures + long_tests）、写盘
- [ ] 2.6 在 `tests/test_regression_execution.py` 覆盖：全绿解析、失败/错误分类、长耗时抽取（含通过用例）、超时（进程不结束 → status timeout）、XML 缺失/非法 → parse_error、快照从未执行态
- [ ] 2.7 与 `bin/run_full_suite.py` 的**主机级全量套件锁**（`.fenix/full-suite.lock`，`bin/run_full_suite.py:48`/`SuiteLock`）互斥：`run_regression` 起跑前按同款 fcntl 独占锁 + 同款等待超时（600s）语义抢占；拿不到锁即放弃本次（记日志、不派发、按已有回归处理）。该锁是主机级（`.fenix/` 不入 git 时的共享锁路径），防 implementer 收尾的全量套件与周期回归同时在主机上跑两套完整测试（CPU/磁盘/端口互相干扰）。命令形态无法在锁内执行时（无锁文件权限等）记 WARNING 后继续——与 `SuiteLock` 的「等不到也继续执行」同款保守语义
- [ ] 2.8 `run_regression` MUST 以 `spec.timeout_seconds` 为硬超时并在超时中止**整个进程组**（`start_new_session=True` + 杀进程组，对齐 `core/verify_contract.py:433` 与 `core/v2_dev_server.py:175` 的既有进程组杀树形态）；仅杀直接子进程会让 shell 形态 `cmd` 派生的测试进程存活，回归名存实亡且产物锁被占

## 3. 执行车道接线（信号消费 + worker）

- [ ] 3.1 在 `core/agent_runner/maintenance_runs.py` 新增 `run_regression(manifest_ctx) -> ...` 执行函数（对齐 `run_code_review` 形态：run_id 前缀 `regression-<epoch>`、独立 token 记账、结果写完后返回），并在 `core/agent_runner/runner.py` 的转发表中注册
- [ ] 3.2 在 `fenixd.py` 新增 `_check_regression_requests()`（对齐 `_check_code_review_requests`：读 `.fenix/regression_request.json` → 校验项目 regression 段 → hosting_state 守卫 → 单飞 → 投递后台 worker），并在 `FenixDaemon` 主循环的「文件信号拾取」块（`fenixd.py:603-607`，与 `_check_code_review_requests` 同块同 1s 粒度）按同形制调用。信号文件在**框架根** `PROJECT_ROOT`（`fenixd.py:42`）下——与 code-review 信号同为单项目自托管形态，MUST NOT 按多项目 registry 逐项目扫描
- [ ] 3.3 在 `core/admin_monitor.py` 新增 `_run_regression_checkpoint()`（对齐 `_run_code_review_checkpoint`：`admin.regression.enabled` 守卫 → run_at 时点 → 同自然日防重 → 单飞 → 无 regression 段跳过），在既有巡检循环（`admin_monitor.py:784` 邻近）调用
- [ ] 3.4 在 `core/config.py` 新增 `get_regression_config(config)`（`admin.regression.enabled` 缺省 False，回退范式同 `get_code_review_config`）
- [ ] 3.5 在 `core/dashboard/data/config_admin.py` 接入 `admin.regression` 受管键：`_SOURCE_KEYS` 新增 `"admin.regression"`、新增 `_DEFAULT_REGRESSION = {"enabled": False}` 并在 `read_config` 两处缺省块回显、写路径 patch 合并与前置校验（`enabled` 严格 bool，非法 fail 不落盘）；MUST 逐条对齐既有 `admin.code_review` 的四处同款改造（`config_admin.py:67`/`:349`/`:874`/`:1032`）——前端提交的 `regression` patch 不走这层就静默丢弃，开关保存后不回显。本改动并入既有 `write_config` 的 admin 合并路径，MUST NOT 依赖 `.fenix/config.yaml` 写入 `admin.regression` 段本身（未知 admin 键由 `_managed_admin_keys` 白名单狭窄回显，读不懂写入值）
- [ ] 3.6 在 `tests/test_regression_execution.py` 补充：JSON 信号消费（有效/无效/未托管/单飞）、检查点守卫矩阵（disabled/before_run_at/already_ran_today/already_running/not_configured）、`admin.regression.enabled` 的 config 读回显 / 写入校验 / dashboard `sources` 标注

## 4. Dashboard 后端：路由与数据层

- [ ] 4.1 新建 `core/dashboard/data/regression.py`：`read_regression_result(project_root)` 读快照返回结构化 dict（含 never_run/parse_error 降级）；在 `core/dashboard/data/__init__.py` 导出
- [ ] 4.2 新建 `core/dashboard/routes/regression_routes.py`：`H12RegressionRoutesMixin` 承载 `GET /api/regression/result`（404/never_run/parse_error 三态）、`POST /api/regression/run`（写信号 + 同 code-review 的 400/409 守卫）
- [ ] 4.3 在 `core/dashboard/routes/base.py` 注册两条路由（对齐 `_get_code_review_items`/`_post_code_review_run` 派发形态）；在 `core/dashboard/server.py` 把 `H12RegressionRoutesMixin` 加入 `DashboardHandler` 基类列表
- [ ] 4.4 在 `tests/test_dashboard_regression_api.py` 覆盖：result 有效快照/未知项目 404/never_run/parse_error 不 500；run 受理/未托管 409/已有在跑 409/未配置 400

## 5. Dashboard 前端：项目页分面与设置页开关

- [ ] 5.1 在 `core/dashboard/static/src/services/dashboard.ts` 新增 `RegressionResult` 类型与 `getRegressionResult(project)`、`triggerRegression(project)` 两个接口函数
- [ ] 5.2 新建 `core/dashboard/static/src/pages/projects/components/RegressionTab.tsx`：active 门控拉取；三态渲染（全绿概览卡片：测试路径/用例数/执行时间/耗时；异常态结果表：用例名/文件:行/耗时/分类；never_run/parse_error 引导态）；「立即执行全量回归」按钮
- [ ] 5.3 在 `core/dashboard/static/src/pages/projects/list.tsx` 把 `regression` 占位替换为 `<RegressionTab project={name} active={activeTab === 'regression'} />`
- [ ] 5.4 在 `core/dashboard/static/src/pages/settings/components/QualityPanel.tsx` 新增「周期性全量回归」卡片：`admin.regression.enabled` 开关表单键名 `code_review_enabled`/`regression_enabled` 二者分开，提交时以 `{admin: {...}}` 或顶层 `regression: {enabled}` 形状提交（对齐既有 `code_review: {enabled}` 的提交形状）；长耗时阈值以只读说明其来源（verify.yaml `regression.long_test_threshold_seconds` 缺省 10）+ 复用既有 `GET/POST /api/verify-yaml` 端点的编辑入口，MUST NOT 在卡片内新增第二个阈值写入路径（双写会让阈值来源分叉）
- [ ] 5.5 执行 `npm run build`（在 `core/dashboard/static`）确认构建通过；`dist/` 为 gitignored 前端构建产物（`.gitignore:30`，主树未跟踪），声明为 `kind: reference`（对齐 `add-code-review-agent-and-quality-tab` tasks.md:48 同款处置），不入库
- [ ] 5.6 在 `RegressionTab.tsx` 的「立即执行」成功后，状态以**服务端快照 `started_at` 是否推进**为运行中判据（沿用分面既有的轮询 `GET /api/regression/result`），MUST NOT 仅以 POST 受理时点在前端本地计时——回归可跑 1800s，跨刷新后本地态丢失会让分面回落到「上次结果」

## 6. 配置模板与文档

- [ ] 6.1 在 `.fenix/config.template.yaml` 新增 `admin.regression` 段（enabled 缺省 false + 注释说明与 code_review 同周期、需 verify.yaml 有 regression 段）
- [ ] 6.2 在 `docs/help/08-dashboard.md` 补充「测试回归」分面说明（三态展示 + 手动触发）与设置页「质量」页签的周期开关
- [ ] 6.3 在 `agents/administrator.md` 的验证契约起草手册补充：起草 verify.yaml 时若项目有测试体系，MUST 一并生成 `regression` 段（识别语言/框架/测试目录，产出 JUnit XML 的 cmd 与 output），经自证后落位；**无测试体系 / 探测不出可产出 JUnit XML 的命令时 MUST 省略该段**（`regression` 段可选，臆造命令会让周期回归每天以 parse_error 空转）
- [ ] 6.4 在 `docs/help/09-config.md`（配置参考，`admin.code_review` 段所在文档）补充 `admin.regression.enabled` 条目 + `.fenix/verify.yaml` 的 `regression` 段字段说明；`docs/help/10-artifacts.md`（文件与数据地图）补 `.fenix/regression/`（`last-run.json` / `state.json` / 请求信号）路径——仅改 `08-dashboard.md` 会让配置键与运行时产物在权威文档中缺席

## 7. 收尾

- [ ] 7.1 全量跑 `tests/` 确认无回归（存量失败除外）
- [ ] 7.2 在 `core/regression.py` 与 `core/verify_contract.py` 的 regression 相关改动处补齐设计理由注释（对齐仓内长注释风格：JUnit XML 跨语言取舍、单快照 Non-Goal、独立防重状态的理由）
