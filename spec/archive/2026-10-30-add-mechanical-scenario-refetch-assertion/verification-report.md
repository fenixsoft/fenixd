# 验证报告：add-mechanical-scenario-refetch-assertion

> ⚠️ 本报告由框架于 2026-10-27T15:32:47Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-10-27T15:32:45.923083+00:00+run-result@mtime1793115165977690824

## 结论：✅ 通过（verified）

**状态：verified — 13/13 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 13/13 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 13 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 0.19M |
| 本链增量 Token（输出） | 0.07M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| net-assert-unit-tests-green | 引擎网络断言单测面全绿（tasks.md 1.2 ①-④ 与 2.2 ①-④ 的集中验收）：pytest 运行新建的 tests/test_verify_engine_network_assertion.py，exit 0 且 -q 汇总含 passed（命令只写 -q 不并列 -v：pytest 9 中 -q 覆盖 -v 后输出退化为点线、不打印 PASSED 行，output_match 断言必须与实际输出形态一致）。该文件应覆盖：①窗口内 1 个匹配请求通过；②零匹配 fail 且明细含「期望 ≥1 实际 0」；③窗口尾部静默等待生效（延迟请求不漏计）；④非匹配 URL 不计入；以及契约校验面：合法形态过验收、非交互步骤携带被拒、非法形态逐条报错、min_count>3 落 WARNING 不拒绝。出处：spec/changes/add-mechanical-scenario-refetch-assertion/tasks.md 1.2/2.2、core/verify_engine/browser.py（监听窗口实现位）、core/verify_engine/scenarios.py:1322（_validate_web 契约校验位）。 | pass | 0/3 | - |
| net-assert-step-roundtrip | TestStep.expect_network 规范字段解析与回环序列化（tasks.md 1.1 配套要求）：构造 click 步骤 dict（含 expect_network=[{url_pattern, min_count}]），经 TestStep.from_dict 解析后 to_dict 回环，expect_network 键与值（url_pattern/min_count）逐字段保真——评审实测 from_dict 显式构造全部字段、TestStep 无 extra 字段，不补模型字段则该键在解析层被静默丢弃、引擎不可见，本场景钉死该回归点。出处：core/verify_engine/scenarios.py:926-1029（TestStep 模型与 to_dict）、tasks.md 1.1。 | pass | 0/3 | - |
| net-assert-validate-accept-interactive | 契约校验正向路径（tasks.md 2.2 ①）：交互步骤（click/hover/type，D3 交互集成员）携带合法形态 expect_network（url_pattern 非空子串 + min_count 正整数 1/2/3，含 >3 预警边界内的 3）经 validate_scenario_dicts 验收零错误——合法形态不得被拒。出处：core/verify_engine/scenarios.py:1322（_validate_web）、design.md D3（交互/非交互显式集合收口）、specs/scenario-network-assertion/spec.md「交互触发请求被断言通过」。 | pass | 0/3 | - |
| net-assert-validate-reject-noninteractive | 契约校验异常路径·非交互步骤携带被拒（tasks.md 2.1/2.2 ②，spec「非交互步骤携带字段被验收拒绝」）：navigate/wait/mock_api 三类非交互步骤（D3 非交互集）携带 expect_network 时验收必须报错，且错误逐条指向各步骤（合并错误文本须逐个含 navigate/wait/mock_api 定位）——验收期拦截，不进运行时。出处：design.md D3（非交互 = navigate/wait/seed/mock_api）、specs/scenario-network-assertion/spec.md「非交互步骤携带字段被验收拒绝」Scenario、core/verify_engine/scenarios.py:1322。 | pass | 0/2 | - |
| net-assert-validate-reject-bad-shape | 契约校验异常路径·非法形态逐条报错（tasks.md 2.1/2.2 ③，spec「非法形态验收报告」）：携带 expect_network=[{"url_pattern": "", "min_count": 0}]（spec 原例）、空白 url_pattern + 负 min_count、非字符串 url_pattern + 非整数 min_count 的步骤，验收必须报错且错误文本逐条点出 url_pattern（非空字符串）与 min_count（正整数）两处形态要求。出处：specs/scenario-network-assertion/spec.md「非法形态验收报告」Scenario、tasks.md 2.1。 | pass | 0/2 | - |
| net-assert-validate-warn-mincount-over3 | 契约校验边界·min_count>3 落 WARNING 不拒绝（tasks.md 2.1/2.2 ④，design.md 风险段「验收对 min_count > 3 给 WARNING 提示」）：click 步骤携带 min_count=5 的 expect_network，validate_scenario_dicts 返回零错误（放行，不制造新拒绝模式），同时经 Python logging（root handler 捕获）产出含 min_count 字样的 WARNING 级提示——稳健用法引导而非硬拒。出处：design.md Risks「planner 滥用新字段」段、tasks.md 2.1。 | pass | 0/3 | - |
| net-assert-planner-contract-declaration | planner 出题契约段能力声明落地（tasks.md 3.1）：agents/planner-plan.md 契约段必须包含 expect_network 能力声明与最小示例，标记物：expect_network 字段名、url_pattern、min_count、示例端点 /api/command-center/pipeline（tasks.md 3.1 钦定示例「click 筛选 → [{url_pattern: "/api/command-center/pipeline", min_count: 1}]」），并注明稳健用法（端点子串 + min_count: 1）。出处：tasks.md 3.1、agents/planner-plan.md:88 附近契约段（支持的操作类型清单所在）。 | pass | 0/2 | - |
| net-assert-browser-capture-positive | 引擎执行能力·真实 playwright 端到端正向（tasks.md 1.1/1.2 ①③，spec「交互触发请求被断言通过」）：直接驱动 core.verify_engine.browser.BrowserManager.execute_action——set_content 页面按钮点击后 setTimeout 150ms 才 fetch（落在 design 钦定的约 300ms 尾部静默窗内，钉「延迟请求不漏计」），带 expect_network 的 click 步骤须捕获并判成功：①纯子串 url_pattern（/api/ping）；②re: 前缀正则 url_pattern（re:/api/ping\?x=\d+，design D2 双匹配模式）。请求经 page.route fulfill 供体（无真实网络），结果以 success 且无嵌套 pass:false 为成功判据。出处：core/verify_engine/browser.py:840（execute_action 步骤执行器）、design.md D1/D2 与 Risks「监听窗口竞态」段、tasks.md 1.1。 | pass | 0/2 | - |
| net-assert-browser-zero-match-fails | 引擎执行能力·零请求缺陷暴露与误计数防护（tasks.md 1.1/1.2 ②④，spec「零请求缺陷被暴露」BUG-1 形态）：同一 execute_action 通路两个负例——①点击不发任何请求的按钮，expect_network min_count 1 须判失败且失败明细含「期望/实际」计数字样（spec 钦定「期望 ≥1 实际 0」形态）；②点击仅发非匹配 URL（/api/unrelated）的按钮，同断言须失败——非匹配 URL 不计入实际计数。失败判据兼容两种返回形态（顶层 success=False 或嵌套 pass:false），并打印原始结果供归因。出处：specs/scenario-network-assertion/spec.md「零请求缺陷被暴露」Scenario、tasks.md 1.2 ②④、design.md D5（失败计入场景 fail、明细 type/message 一致）。 | pass | 0/2 | - |
| net-assert-no-networkidle-guard | 设计决策守卫·回归点（design.md Risks「监听窗口竞态」段硬约束）：core/verify_engine/browser.py 的 expect_network 窗口收尾 MUST 用固定短静默窗，MUST NOT 引入 wait_for_load_state("networkidle")——本仓库页面常驻 SSE、networkidle 永不满足，browser.py 文件头设计决策（browser.py:8）已明确移除该等待，新能力不得回添；同时断言 browser.py 已落地 expect_network 能力标记。出处：design.md Risks 段、core/verify_engine/browser.py:8（networkidle 移除设计决策）。 | pass | 0/3 | - |
| net-assert-regression-existing-tests-green | 回归锁定·既有 verify_engine 场景执行/验收用例全绿（tasks.md 4.1「无 expect_network 的场景行为逐位不变」）：pytest 一次性运行六份既有测试文件——场景持久化/校验（test_verify_scenarios.py）、多形态词表与执行（test_verify_multi_kind.py）、cli/api runner（test_verify_cli_runner.py、test_verify_api_runner.py）、场景静态检查（test_scenario_static_check.py）、验证契约（test_verify_contract.py），exit 0 且汇总含 passed（只 -q 不并列 -v，output_match 与 -q 输出形态一致）。当前 HEAD 基线 169 passed（planner 轮实测），实现后不得引入回归。出处：tasks.md 4.1、tests/ 上述六文件。 | pass | 0/2 | - |
| cc-web-refetch-tab-switch-network-asserted | 引擎能力真实应用端到端·BUG-1 形态回归锁定（proposal.md Why 段动机场景）：指挥中心 Tab 切换属「交互触发重拉取」——点击「交付流水线」Tab 应在步骤执行窗口内即时发出 /api/command-center/pipeline 聚合请求（useScreenResource 激活 effect 立即 run，非 60s 轮询兜底），expect_network 断言 min_count≥1；再点「执行台账」Tab 断言 /api/command-center/ledger 请求。「点了但没拉数据」类缺陷（BUG-1：筛选切换后各屏 0 新请求滞留 60s）从此机械可暴露。页面以零聚合数据渲染（夹具项目 scheduling-showcase 为 fixture=True，被缺省聚合分支剔除，command_center_routes.py:48-50），列头与 KPI 标签照常渲染，不依赖项目数据。navigate 出处：core/dashboard/static/src/app.tsx:139（/command-center 路由注册）；请求出处：core/dashboard/static/src/pages/command-center/useScreen.ts:46-49（激活 effect 即时拉取）、PipelineBoard.tsx:81-87（refreshKey 即时重拉）、ExecutionLedger.tsx:133-148（台账/KPI 独立加载）、core/dashboard/routes/command_center_routes.py:80-95（pipeline/ledger 端点）；选择器出处：shared.ts:138-144（五列中文列头「需求评审」）、ExecutionLedger.tsx:85（KPI 标签「7 日交付 SPEC」）、add-command-center 修复注记（antd 6.6 面板作用域 .ant-tabs-content-active）。 | pass | 0/4 | - |
| net-assert-contract-example-passes-validation | 契约示例过引擎验收·防契约与实现漂移（tasks.md 3.2）：从 agents/planner-plan.md 契约段正则提取 url_pattern 示例值（兼容 JSON 形态 "url_pattern": "…" 与 JS 形态 {url_pattern: "…"}），以该值构造带 navigate + click(expect_network) 的最小 web 场景 dict，经 validate_scenario_dicts 实测必须零错误——契约段写出的示例形态与引擎验收逐字同源，文档漂移在此暴露。出处：tasks.md 3.2、core/verify_engine/scenarios.py:1661（validate_scenario_dicts 单一来源）。 | pass | 0/3 | - |

## 本轮场景集变更

当前稳定场景集共 13 个（第 1 轮）。

- 首轮写入 13 个场景

