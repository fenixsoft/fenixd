# 验证报告：add-test-regression-tab

> ⚠️ 本报告由框架于 2026-09-20T22:19:54Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-09-20T22:19:53.961161+00:00

## 结论：✅ 通过（verified）

**状态：verified — 22/22 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 22/22 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 22 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 43.02M |
| 本链增量 Token（输出） | 0.31M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| cli-regression-contract-tests | 回归声明契约单元测试：pytest tests/test_regression_contract.py -v 覆盖有效段解析、缺省阈值10秒、无段→None、无效段缺cmd/output→None+WARNING、format非junit→无效、非法值回退缺省、argv列表cmd支持。（spec test-regression-declaration scenarios） | pass | 0/6 | - |
| cli-regression-execution-tests | 回归执行与JUnit解析单元测试：pytest tests/test_regression_execution.py -v 覆盖JUnit XML解析（全绿/失败/错误/缺失/非法/缺省time/classname兜底）、长耗时抽取、快照读写、状态文件读写、run_regression全绿/超时杀进程组/argv列表/parse_error/长耗时、巡检检查点守卫矩阵、信号消费。（spec test-regression-execution scenarios） | pass | 0/8 | - |
| cli-regression-api-tests | Dashboard回归API与配置管理单元测试：pytest tests/test_dashboard_regression_api.py -v 覆盖GET result三态+404、POST run受理/未配置400/未托管409/404、admin.regression配置_source_keys登记/缺省回显/写读回环/非法值拒绝/开关缺省关闭、运行中标记roundtrip。（spec test-regression-execution + test-regression-view scenarios） | pass | 0/6 | - |
| cli-clean-snapshot | 清理回归快照与运行中标记：确保 .fenix/regression/ 目录干净（删除 last-run.json 与 .running），为 never_run 验证提供确定性初始状态。 | pass | 0/2 | - |
| api-regression-result-unknown-project | GET /api/regression/result?project=no-such-proj → 404（spec test-regression-view「未知项目」Scenario）。regression_routes.py:38-40 _project_from_query → None → self._error(404)。 | pass | 0/1 | - |
| api-regression-run-not-configured | POST /api/regression/run?project=fenixd → 400「该项目未配置全量回归」（spec test-regression-execution「项目未配置 regression 段时触发」Scenario）。regression_routes.py:68-73 load_verify_contract → regression=None → 400。项目 verify.yaml 无 regression 段。 | pass | 0/2 | - |
| api-regression-config-reset-off | 确定性复位 admin.regression.enabled=false：POST /api/config?project=fenixd 提交 {regression: {enabled: false}}（与前端 QualityPanel.tsx:117-119 提交形状一致，config_admin.py:1167 写路径校验），为 web-settings-regression-default-off 提供确定性初始态（跨轮共享主树 config.yaml，不可假定缺省未改）。断言响应 regression.enabled == false。 | pass | 0/2 | - |
| web-settings-regression-default-off | 设置页「质量」页签回归开关缺省关闭：admin.regression.enabled 缺省 false，开关回显为关闭（config.py:1289 get_regression_config, config_admin.py:172 _DEFAULT_REGRESSION）。regression_routes.py:129 关闭时巡检检查点不做任何事。 | pass | 0/6 | - |
| web-regression-trigger-error | 测试回归分面手动触发按钮错误路径：点击「立即执行全量回归」按钮，POST /api/regression/run 返回 400「该项目未配置全量回归（verify.yaml regression 段）」，前端 catch 展示 warning 提示（RegressionTab.tsx:189-193）。verify.yaml 无 regression 段 → load_verify_contract → regression=None → 400。 | pass | 0/2 | - |
| api-regression-result-never-run | GET /api/regression/result?project=fenixd → {status: never_run} 200（spec test-regression-execution「从未执行过」Scenario）。regression_routes.py:38-42 读快照 → core/regression.py:311 read_result 缺文件返回 never_run。需在任何 seed 写入 last-run.json 前执行。 | pass | 0/3 | - |
| web-regression-tab-never-run | 项目页「测试回归」分面引导态：快照 never_run 时展示「尚未执行过全量回归」引导文案 + 手动触发按钮。RegressionTab.tsx:211-239 三态渲染never_run分支。路由 #/projects/fenixd → Tabs → 点击「测试回归」tab。 | pass | 0/5 | - |
| web-settings-regression-switch-toggle | 设置页「质量」页签开启周期性全量回归：项目级作用域切换 → 勾选 regression-enabled-switch → 保存（POST /api/config {regression: {enabled: true}}）→ 前端回显开关开启。对齐 add-settings-system-tab 的项目级保存模式。QualityPanel.tsx:326-345 回归开关卡片。 | pass | 0/4 | - |
| cli-seed-passed-snapshot | 写入全绿回归快照到 .fenix/regression/last-run.json（status=passed, total=5045, passed=5045, duration=200s）。供后续 api/web passed 状态场景消费。写路径相对 scenario_root（= serving worktree root = 项目路径）。 | pass | 0/4 | - |
| api-regression-config-persisted | GET /api/config?project=fenixd → json_path regression.enabled == true，验证 admin.regression.enabled 经 POST /api/config 写入后落盘回显。config_admin.py:649 _DEFAULT_REGRESSION 为 {enabled: False}，写入后回显 true。 | pass | 0/2 | - |
| api-regression-result-valid-snapshot | GET /api/regression/result?project=fenixd → 200，status=passed，含 cmd/total=5045/passed=5045/duration_seconds/failures=[]/long_tests=[]。regression_routes.py:38-42 读 last-run.json 快照全字段。 | pass | 0/7 | - |
| web-regression-tab-passed-overview | 项目页「测试回归」分面全绿概览：快照 status=passed 时展示概览卡片（Tag「全部通过」+ Descriptions 测试路径/用例总数/通过数/执行时间/总耗时）。RegressionTab.tsx:326-380 概览卡片渲染。 | pass | 0/7 | - |
| cli-seed-failed-snapshot | 写入失败回归快照：status=failed, total=5045, passed=5041, failed=2, errors=1, skipped=1, failures 含 test_auth_edge_case(failure) + test_db_timeout(error), long_tests 含 test_auth_edge_case(12.5s) + test_slow_query(15.3s)。buildRows 去重后渲染3行（失败/错误/长耗时）。 | pass | 0/4 | - |
| api-regression-result-failed-with-issues | GET /api/regression/result?project=fenixd → 200，status=failed，json_path failures 数组非空、long_tests 数组非空。验证失败/错误/长耗时用例的 name/file/line/time/kind 字段完整。 | pass | 0/7 | - |
| web-regression-tab-failed-table | 项目页「测试回归」分面异常态结果表：快照 status=failed 时概览下渲染 Table（用例名/文件:行/耗时/分类列）。Tag 颜色：失败=红、错误=橙、长耗时=金。RegressionTab.tsx:300-310 分类Tag + 404-413 结果表。 | pass | 0/8 | - |
| cli-seed-corrupt-snapshot | 写入损坏的快照文件到 .fenix/regression/last-run.json（非合法 JSON 文本）。regression.py:316 读取时 json.JSONDecodeError → {status: parse_error}。 | pass | 0/4 | - |
| api-regression-result-parse-error | GET /api/regression/result?project=fenixd → 200，json_path status == parse_error，json_path reason 非空。regression_routes.py:38-42 → core/regression.py:316 read_result → JSONDecodeError → parse_error。MUST NOT 500。 | pass | 0/4 | - |
| web-regression-tab-parse-error | 项目页「测试回归」分面不可解析态：快照 parse_error 时展示「回归结果不可解析」文案 + reason。RegressionTab.tsx:242-258 三态渲染 parse_error 分支。 | pass | 0/5 | - |

## 本轮场景集变更

场景集与持久化集一致，无变更。

