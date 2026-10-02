# 验证报告：add-regression-auto-fix

> ⚠️ 本报告由框架于 2026-09-25T05:43:14Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-09-25T05:43:14.883920+00:00

## 结论：✅ 通过（verified）

**状态：verified — 23/23 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 23/23 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 23 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 20.81M |
| 本链增量 Token（输出） | 0.27M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| cli-regfix-fixture-provision | 夹具供给（幂等复位）：在 /root 下创建/复位 8 个 regfix-* 合成项目（accept=2 失败用例快照 / clean=全绿 / never=无快照 / corrupt=损坏快照 / timeout=整体超时 / broken=2 失败+1 长耗时 / trigger=1 失败 / live=无快照+git 仓+最小 config），清理信号/结果/台账残留；registry 以 ~ 一级目录 + .fenix/STATE.md 自动发现（10s TTL 刷新）。出处 core/dashboard/registry.py:33-37 与 core/dashboard/http_server.py:50。 | pass | 0/7 | - |
| cli-regfix-convert-mapping | 回归快照→台账 findings 转换映射（纯函数）：kind=failure→category regression-failure、kind=error→regression-error（severity 均 high）、long_tests 逐条→regression-long-test（severity medium）、title 取用例名、description 携带耗时（0.8s/42s）与失败 message、长耗时 suggestion 固化「不改变测试通过结果」+「并发化」文案；落库后 review_kind=regression_fix、severity 归一为 major（既有 normalize_severity 契约）；非 dict 快照/条目容错。出处 core/code_fix.py:898-988（convert）、core/code_review.py:300-321（归一）。 | pass | 0/17 | - |
| cli-regfix-convert-timeout | 整体超时转换为单条目（纯函数）：status=timeout → 单条 regression-timeout、severity high、file 固定 .fenix/verify.yaml（修复入口锚点）、title 回归整体超时、description 携带 reason 与输出摘要（无摘要时不出现输出摘要段；超 500 字截断）；passed 快照不产生 timeout 条目。出处 core/code_fix.py:898-988 与 design D4。 | pass | 0/12 | - |
| cli-regfix-reopen-dedup | 去重与复发重开语义：同指纹（file+category+title）重复 upsert 不产生重复条目且不覆盖 status/first_seen_at（仅刷新 last_seen_at）；regression- 前缀条目 resolved 后同指纹再次消费 → reopen_regression_items 重开 open 并刷新 first_seen_at；code-review 来源条目（非 regression- 前缀、file/title 恰好同名）不被触碰。出处 core/code_fix.py:990-1060（fingerprints/reopen）、core/code_review.py:288-295（fingerprint）、core/code_review.py:365-430（upsert 去重语义）。 | pass | 0/11 | - |
| cli-regfix-consume-happy | daemon 消费信号正常路径（进程内装配，FenixDaemon.__new__ 最小装配 + monkeypatch PROJECT_ROOT）：消费信号 → 读快照 → 转换入账（review_id=regression-fix-<created>、review_kind=regression_fix）→ spy 编排器收到 checkpoint(override_enabled=True) → 结果文件 request_created 回链、triggered=true、dispatched 文案、finished_at 非空；信号先读后删；台账 2 条 open（regression-failure/error）。出处 fenixd.py:3135-3225（消费方法）、fenixd.py:3109（文案表）、fenixd.py:786（主循环挂载）。 | pass | 0/11 | - |
| cli-regfix-consume-degraded | daemon 消费端降级路径（进程内装配一次覆盖四分支）：编排器未装配 → orchestrator_missing 结果且不入账不静默；checkpoint 抛异常 → dispatch_exception 结果且已入账条目不回滚（design D6）；快照缺失 → snapshot_missing 结果、不入账、不调 checkpoint；损坏信号 JSON → 删除防卡死、不落结果、不触发 checkpoint。出处 fenixd.py:3135-3225（三兜底分支）、fenixd.py:3146-3157（orchestrator 前置检查）。 | pass | 0/13 | - |
| cli-regfix-impl-testsuite | 实现自带测试套件回归：pytest tests/test_regression_autofix.py -v --tb=short（31 例：转换分支/截断/容错/重开/端点受理与拒绝/消费全链路与兜底）应全绿。注意只用 -v 不并列 -q（否则输出退化为点号、PASSED 消失）。出处 tests/test_regression_autofix.py（main 实现 31 用例）。 | pass | 0/3 | - |
| api-regfix-unknown-project-404 | 「自动修复回归问题」两端点对未注册项目均 404：POST /api/regression/fix 与 GET /api/regression/fix-result 对 ghost-regfix-404（不在监控列表）MUST 返回 404「project not found」，不写信号。出处 core/dashboard/routes/regression_routes.py:352-355 与 440-443、core/dashboard/routes/base.py:378 与 431。 | pass | 0/4 | - |
| api-regfix-accept-writes-signal | 受理成功写信号 + 并发防重：POST /api/regression/fix?project=regfix-accept（快照存在 2 个失败用例）响应 200 {ok:true, requested_at}；紧接着第二次 POST 因信号文件尚未被消费（夹具无 daemon）以 O_CREAT\|O_EXCL 独占创建失败 → 409「已有未消费的回归修复触发请求（请稍后重试）」。出处 core/dashboard/routes/regression_routes.py:334-429（受理与 O_EXCL）、core/dashboard/routes/base.py:431。 | pass | 0/5 | - |
| api-regfix-reject-no-issues | 无异常时拒绝：POST /api/regression/fix?project=regfix-clean（快照 status=passed、failures/long_tests 均空）MUST 返回 400 且稳定错误码 code=regression_no_issues，MUST NOT 写信号文件。出处 core/dashboard/routes/regression_routes.py:374-386。 | pass | 0/3 | - |
| api-regfix-reject-never-run | 从未执行/快照损坏时拒绝：POST /api/regression/fix?project=regfix-never（.fenix/regression/last-run.json 缺失 → never_run）与 project=regfix-corrupt（快照非合法 JSON → parse_error）MUST 均返回 400 且错误码同归 regression_never_run，MUST NOT 写信号。出处 core/dashboard/routes/regression_routes.py:358-372、core/regression.py:356-369（读侧三态）。 | pass | 0/4 | - |
| api-regfix-fix-result-none | 回链结果读取·缺失形态：GET /api/regression/fix-result?project=regfix-never（结果文件不存在）MUST 返回 200 + {"status": "none"} 而非 404/500 报错。出处 core/dashboard/routes/regression_routes.py:431-451。 | pass | 0/2 | - |
| api-regfix-live-start | live 消费链启动：POST /api/projects/regfix-live/start 经 supervisor 托管拉起 regfix-live 的真实 daemon（主循环 1s 粒度挂载 _check_regression_fix_requests，fenixd.py:786），为 live 消费场景提供消费方。出处 core/dashboard/routes/project_routes.py:81,113（生命周期端点）。 | pass | 0/2 | - |
| web-regfix-btn-enabled-with-issues | 有异常用例时「自动修复回归问题」按钮可用：打开 regfix-broken（快照 2 失败+1 长耗时）项目页测试回归分面，修复按钮与「立即执行全量回归」并排渲染于概览卡右下按钮区、可点击（element_enabled），结果表列出失败与长耗时用例。出处 core/dashboard/static/src/pages/projects/components/RegressionTab.tsx:650-663（按钮渲染）、504-507（fixAvailable 机械判定）、list.tsx:1404（分面挂载）。 | pass | 0/6 | - |
| web-regfix-btn-disabled-when-clean | 全绿无长耗时时「自动修复回归问题」按钮渲染但禁用：打开 regfix-clean（status=passed、无异常）测试回归分面，按钮带 disabled 属性；悬停外层 span 出现 Tooltip「无异常用例可修复」（disabled 按钮不触发悬停，antd 惯例外包 span 承载）。出处 RegressionTab.tsx:650-663（Tooltip+span+disabled）、504-507（fixAvailable=false）。 | pass | 0/4 | - |
| web-regfix-btn-absent-guidance | 从未执行过回归（never_run 引导态）不出「自动修复回归问题」按钮：打开 regfix-never 测试回归分面，渲染引导文案与「立即执行全量回归」，修复按钮 MUST NOT 渲染（三态引导视图只保留手动触发）。出处 RegressionTab.tsx:432-468（never_run 分支）。 | pass | 0/4 | - |
| web-regfix-btn-absent-parse-error | 快照不可解析（parse_error 引导态）同样不出「自动修复回归问题」按钮：打开 regfix-corrupt（快照为非法 JSON）测试回归分面，渲染「回归结果不可解析」与 reason，修复按钮 MUST NOT 渲染。出处 RegressionTab.tsx:470-493（parse_error 分支）。 | pass | 0/4 | - |
| web-regfix-timeout-enabled | 整体超时时「自动修复回归问题」按钮可用（status===timeout 机械判定第三臂）：打开 regfix-timeout 测试回归分面，按钮可点击，概览卡展示超时原因文案。出处 RegressionTab.tsx:504-507（timeout 臂）、631-635（原因展示）。 | pass | 0/4 | - |
| web-regfix-trigger-inflight-loading | 触发在途 loading 防重复点击：点击「自动修复回归问题」→ POST 受理后进入 1s 间隔轮询（上限 30s，夹具无 daemon 不会命中回链），按钮呈现 antd loading 态（ant-btn-loading 类）；loading 期间重复点击被 antd handleClick 守卫拦截不产生第二个信号（无 409 错误 toast）。出处 RegressionTab.tsx:366-422（handleFix 轮询与防重复）、656（loading 绑定）。 | pass | 0/4 | - |
| cli-regfix-signal-file-contract | 信号文件落盘契约：api-regfix-accept-writes-signal 受理后 regfix-accept 项目根存在 .fenix/regression_fix_request.json，payload 键恰为 {source: regression_fix, created: ISO 时间戳}；被拒绝项目（clean/never）无信号残留；web 点击触发的 regfix-trigger 信号在途（证明前端按钮真实发出信号）。出处 core/dashboard/routes/regression_routes.py:388-429（信号写入）。 | pass | 0/9 | - |
| cli-regfix-live-consume-snapshot-missing | live daemon 主循环真实消费信号（spec「快照缺失时消费端落结果」端到端）：regfix-live 快照缺席预置后直写信号文件（{source: regression_fix, created} 生产者契约）→ 真实 daemon 主循环 1s 粒度原子消费 → 落结果文件 triggered=false、reason=snapshot_missing、固化文案、request_created 回链、finished_at 非空；不入账（无台账文件）；信号消费后消失。出处 fenixd.py:3160-3170（snapshot_missing 分支）、design D5。 | pass | 0/8 | - |
| api-regfix-live-result-passthrough | 回链结果读取·live 透传：daemon 刚写回的真实判定经 GET /api/regression/fix-result?project=regfix-live 原样透传（triggered=false、reason=snapshot_missing、message 中文文案、finished_at 非空）——真实 HTTP→文件信号→daemon 消费→结果文件→HTTP 回链闭环，非 mock。出处 core/dashboard/routes/regression_routes.py:431-451。 | pass | 0/5 | - |
| cli-regfix-live-cleanup | 环境收尾：停掉 regfix-live 的受托管 daemon（hosting 回 stopped），清除 live 信号/结果残留，保持夹具跨轮洁净（旧行为：daemon 遗留会持续消费后续轮次信号）。出处 core/fenix_session.py:435（stop_daemon）。 | pass | 0/4 | - |

## 本轮场景集变更

场景集与持久化集一致，无变更。

