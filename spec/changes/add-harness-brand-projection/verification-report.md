# 验证报告：add-harness-brand-projection

> ⚠️ 本报告由框架于 2026-10-14T05:54:18Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-10-14T05:47:11.374195+00:00+run-result@mtime1791957245548437417

## 结论：❌ 未通过（Bug Found）

**状态：bug-found — 10/15 场景通过，5 失败，0 错误（1 个真实产品 Bug）**

验证不通过：15 场景 10 通过 / 5 失败。5 个失败 web 场景共享同一根因（≥3 场景聚合为 1 个 Bug）：详情页 chunk 缺 HarnessBrandProvider import 导致整页崩溃、时间轴 run 卡片不渲染。选择器有源码出处（detail.tsx:1359/1363）、API 数据契约已被 hbp-api-run-meta-harness-exposure 证实、同批其他 web 场景通过排除环境/并行干扰 → product-bug（非场景缺陷，修复属产品代码：补 L22 import 即可）。无 test-defect/flaky/env 场景，未触发场景文件修复协议。

| 指标 | 数量 |
| --- | --- |
| 通过 | 10 |
| 失败 | 5 |
| 错误 | 0 |
| 产品 Bug | 1 |
| 本链增量 Token（输入） | 0.86M |
| 本链增量 Token（输出） | 0.19M |


## 真实产品 Bug

### BUG-01（severity=major）· step_error/click（element_not_found_or_not_actionable）

- 关联场景：hbp-web-run-record-dsh-brand、hbp-web-run-record-claude-brand、hbp-web-run-record-legacy-fallback、hbp-web-run-record-unknown-badge、hbp-web-timeline-inline-pane-dsh
- 描述：spec 详情页整页崩溃：detail.tsx:1377 使用 HarnessBrandProvider 但导入清单（L1-36）缺失该 import，构建产物运行时抛 ReferenceError: HarnessBrandProvider is not defined，error boundary 接管渲染「Something went wrong」，时间轴 run 卡片（「查看运行记录」折叠与「最大化查看」按钮）不渲染，5 个 web 场景点击超时。影响范围：所有时间轴含 run 节点的 spec 详情页（即全部真实项目）均不可用
- 根因：core/dashboard/static/src/pages/projects/detail.tsx 使用 <HarnessBrandProvider>（L1377/1379）但未从 '@/components/claude-msg' 导入；umi 产物 p__projects__detail.async.js 中该标识符未定义，时间轴 Array.map 渲染时抛 ReferenceError
- 证据（场景 hbp-web-run-record-dsh-brand 结构化证据，引用）：
  - failed_assertions: [{"type": "step_error", "selector": "button[title=\"最大化查看\"]", "expected": "点击步骤成功", "actual": "Locator.wait_for: Timeout 5000ms exceeded."}]
  - screenshots: []
  - first_failed_step: 步骤3: 点击 button[title="最大化查看"] 超时（c-hbp-dsh 详情页时间轴 run 卡片控件 5s 未可见）
  - repro: playwright 探针访问 c-hbp-dsh 详情页：pageerror=ReferenceError: HarnessBrandProvider is not defined（detail chunk Array.map 渲染时间轴时），bodyHead 含 "Something went wrong"，timelineItems=0/maxBtns=0


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| hbp-fixture-provision | 【夹具】幂等重建专用夹具项目 /root/harness-brand-showcase（整目录重建，跨轮次零残留）：.fenix/STATE.md 4 个 done spec（c-hbp-dsh/c-hbp-claude/c-hbp-pi/c-hbp-legacy）；.fenix/runs/ 写 4 个 impl run 产物（run_id=impl-<spec>-<epoch>，时间戳段使 run_spec_part 全等归属各自 spec）+ 2 个 admin run 产物（admin-hbp-dsh-probe/admin-hbp-legacy-probe，中段非真实 spec 名不串入 spec runs 列表）；.fenix/logs/fenixd.log 追加 run_metrics 结构化行（harness=dsh/claude/pi 各一条，legacy 两例有意缺行=真实存量读径）；.fenix/admin_alerts.json 写两条 kind=disposition 记录（created 钉序 2027-06 置顶，记录不带 harness——admin 值由读侧注入）；注册表 Registry.add_project(name, fixture=True) 登记（ADR-163 夹具打标降噪，已存在时 mark_fixture 补写）；随后数据级自检（run_spec_part 全等归属/load_run_metric/get_runs 缺省回退/classify_run/get_admin_activities 注入/get_spec_timeline run 节点 harness）并轮询被测实例 /api/projects 直到发现（发现 TTL 10s）。cli 非零退出码=夹具环境阻塞信号，后续场景均 depends_on 本场景。出处：core/agent_runner/run_files.py:28-88（前缀表）与:184（run_spec_part）、core/dashboard/data/runs.py:136（.fenix/logs/fenixd.log 指标索引）与:619-637（get_runs harness 缺省 claude）、core/dashboard/data/admin_alerts.py:228-240（admin harness 读侧注入）、core/dashboard/registry.py:463/549（add_project/mark_fixture）、bin/fixture_scheduling_showcase.py（夹具供给先例） | pass | 0/14 | - |
| hbp-cli-dsh-logo-inline-contract | 【spec「dsh 官方图标入库」·源码级契约】结构化抽检前端源码与构建产物：DshLogo.tsx 含 aria-label="dsh"、fill="#4D6BFE"（基础品牌蓝固化）且零 @media 媒体查询（明暗两态可见的静态保证）；源资产 spec/changes/add-harness-brand-projection/assets/dsh-mark.svg 保留 @media(prefers-color-scheme（证明移除发生在内联时而非资产）；HarnessBrand.tsx 注册表含 dsh 映射与缺省 ClaudeLogo、未知值徽标（rounded-full）；harnessBrandLogic.ts 注册集 new Set(['claude','dsh']) 与 DEFAULT_BRAND_NAME='Claude'；MessageItem.tsx 经 useHarnessBrand() 且零 ClaudeLogo 字面、无 return 'Claude' 字面标签（去字面耦合）；tests/harnessBrand.test.mjs 在位；dist 构建产物含 #4D6BFE 与 "aria-label":"dsh"（fresh 构建冒烟）。出处：core/dashboard/static/src/components/claude-msg/DshLogo.tsx:5-9/18/24、spec/changes/add-harness-brand-projection/assets/dsh-mark.svg:6-7、components/claude-msg/HarnessBrand.tsx:26-42/58-59、claude-msg/harnessBrandLogic.ts:18/22、claude-msg/MessageItem.tsx:15/47-58、tasks.md 1.1-1.3 | pass | 0/16 | - |
| hbp-cli-harness-brand-unit-tests | 【任务 4.1】运行 node --test tests/harnessBrand.test.mjs（cwd core/dashboard/static）：回退链三分支单测全绿——缺省（无字段/null/空串）=claude、dsh 映射、未知值回退徽标（'pi'→'P' 且标签保留原值）。实测 10 pass / 0 fail（非 TTY 汇总行 ℹ pass 10 / ℹ fail 0），仅 -v 形态跑法不配 -q（-q 会吞 PASSED/汇总计数行）。出处：core/dashboard/static/tests/harnessBrand.test.mjs:1-67（10 用例）、components/claude-msg/harnessBrandLogic.ts:24-39（被测纯逻辑） | pass | 0/3 | - |
| hbp-cli-run-metrics-write-side-tests | 【任务 2.1·写侧形态】运行 python3 -m pytest tests/test_run_metrics_persistence.py -v --tb=short（cwd 验证树根）：run_metrics 结构化行 harness 键写侧契约全绿——经派发的 run 指标行携带 harness（claude 缺省解析）、adapter 未装配的提前终态路径省略该键、并发 run 不串号（收尾从 run 自身上下文取值而非进程级全局）。实测 9 passed。出处：core/agent_runner/runner.py:8587（收尾从 _run_harness 取值）与:8506（派发登记）、:809（登记声明）、tests/test_run_metrics_persistence.py:288/315/334（三契约用例） | pass | 0/4 | - |
| hbp-cli-python-readside-tests | 【任务 2.2·读侧透出】运行 python3 -m pytest tests/test_dashboard_data.py -v --tb=short（cwd 验证树根）：runs.py 读侧 harness 透出契约全绿——指标行携带→透出、指标行缺键→缺省 claude、无指标行→缺省 claude、时间轴 run 节点携带、admin 记录携带/缺键不下发。实测 167 passed。出处：core/dashboard/data/runs.py:619-637（get_runs 缺省 claude）、core/dashboard/data/timeline.py:399-402（时间轴节点）、core/dashboard/data/admin_alerts.py:228-240（admin 注入）、tests/test_dashboard_data.py:2893-3006（TestGetRunsHarness/TestAdminActivitiesHarness） | pass | 0/4 | - |
| hbp-cli-frontend-regression-green | 【任务 4.3·前端半边回归】运行前端全量 node --test tests/*.test.mjs（cwd core/dashboard/static）：新增 harnessBrand.test.mjs 连同存量消息列表/输出面板/工具聚合等全部测试文件全绿（SessionPanel 渲染路径、runEvents 转换、toolGrouping 等不受去字面耦合影响）。实测 238 pass / fail 0（仅 -v 形态跑法，不配 -q）。出处：core/dashboard/static/tests/（18 个测试文件）、tasks.md 4.3 | pass | 0/3 | - |
| hbp-api-run-meta-harness-exposure | 【真相源·读侧透出】GET /api/specs/c-hbp-dsh?project=harness-brand-showcase 断言 runs[0].harness=="dsh"且 runs[0].run_id 为 dsh run（时间轴 run 节点同数据源）；同口径断言 c-hbp-claude→"claude"（显式值）、c-hbp-pi→"pi"（未知值原样透出，前端走徽标回退）、c-hbp-legacy→"claude"（无 run_metrics 行缺省回退=存量 run 契约）；再 GET /api/admin-activities?project=harness-brand-showcase（显式点名查询：聚合分支 alert_routes.py:232/263 过滤 fixture 项目，单项目分支 :213-224 零过滤）断言 activities[0].harness=="dsh"、activities[0].admin_run_id 为 dsh 处置 run、activities[1].admin_run_id 为 legacy 处置 run（其 harness 键缺省不下发形态由 python 单测覆盖）。五请求全打真实实例端点、零 mock。出处：core/dashboard/routes/base.py:588（/api/specs/<spec>）与:592（/api/admin-activities）、core/dashboard/data/summary.py:961/1035（spec_detail 下发 runs）、core/dashboard/data/runs.py:619-637、core/dashboard/data/admin_alerts.py:228-240 | pass | 0/13 | - |
| hbp-web-run-record-dsh-brand | 【spec「dsh run 显示 dsh 品牌」·弹窗注入】项目详情页时间轴 dsh run 卡片点全屏按钮开 RunRecordModal，断言助手消息头像为官方鲸鱼图标 svg[aria-label="dsh"]、path fill 固化基础品牌蓝 #4D6BFE（spec「明暗两态可见」的 DOM 级固化落点：媒体查询已移除、恒品牌蓝），消息头标签精确等于 dsh（MessageItem 经 useHarnessBrand），弹窗内不存在 ClaudeLogo——缺省品牌被按 run meta 的 harness 投影替换而非叠加。出处：core/dashboard/static/config/config.ts:15（hash 路由）与 config/routes.ts:23（/projects/:name/:spec）、core/dashboard/static/src/pages/projects/detail.tsx:1357-1368（最大化按钮 setRecordRun 携 item.harness）与:2224（RunRecordModal 注入）、pages/projects/components/RunRecordModal.tsx:32（HarnessBrandProvider）、components/claude-msg/DshLogo.tsx:18/24、claude-msg/MessageItem.tsx:47-58 | failed（已修正） | - | product-bug |
| hbp-web-run-record-claude-brand | 【spec「claude run 显示不变」·回归点】同弹窗路径打开 harness=claude 的 run：svg[aria-label="Claude"] 可见、标签精确等于 Claude、头像 path fill 保持现状色 #D77655（ClaudeLogo 源钉值），弹窗内不存在 dsh 鲸鱼图标——claude 通道品牌投影与改造前渲染一致（存量行为零变化回归）。出处：core/dashboard/static/config/config.ts:15、config/routes.ts:23、core/dashboard/static/src/pages/projects/detail.tsx:1357-1368/2224、pages/projects/components/RunRecordModal.tsx:32、components/claude-msg/ClaudeLogo.tsx:10/16、claude-msg/harnessBrandLogic.ts:22（DEFAULT_BRAND_NAME='Claude'） | failed（已修正） | - | product-bug |
| hbp-web-run-record-legacy-fallback | 【spec「回退链」第 1 级·存量 run 缺 harness 字段】打开无 run_metrics 指标行的存量形态 run（真实存量读径：索引无 meta 可取）：弹窗缺省回退 Claude 品牌——svg[aria-label="Claude"] 可见、标签精确等于 Claude、无 dsh 图标、无未知值徽标，页面正常不崩。出处：core/dashboard/static/config/config.ts:15、config/routes.ts:23、core/dashboard/static/src/pages/projects/detail.tsx:1357-1368/2224、pages/projects/components/RunRecordModal.tsx:14（harness 缺省 undefined）、components/claude-msg/harnessBrandLogic.ts:24-29（无字段→default/claude）、core/dashboard/data/runs.py:619-637（读侧缺省 claude 兜底） | failed（已修正） | - | product-bug |
| hbp-web-run-record-unknown-badge | 【spec「未知 harness 回退徽标」·异常路径】打开 harness=pi（未注册值）的 run：头像渲染 P 首字母徽标（圆形底 div[aria-label="pi"]，内容为 P）、标签保留原值精确等于 pi、无 dsh/Claude 图标，页面正常无控制台错误（回退链 MUST NOT 抛错白屏的端到端落点）。出处：core/dashboard/static/config/config.ts:15、config/routes.ts:23、core/dashboard/static/src/pages/projects/detail.tsx:1357-1368/2224、pages/projects/components/RunRecordModal.tsx:32、components/claude-msg/HarnessBrand.tsx:26-37（首字母徽标工厂）与:52-54（fallback 分支）、claude-msg/harnessBrandLogic.ts:36-38（'pi'→'P'） | failed（已修正） | - | product-bug |
| hbp-web-timeline-inline-pane-dsh | 【任务 3.1 第二注入点·内嵌 pane】时间轴 run 卡片展开「查看运行记录」折叠（不经弹窗）：内嵌 ClaudeOutputPane 同口径注入 harness——折叠区内鲸鱼头像 svg[aria-label="dsh"] 可见、fill 固化 #4D6BFE、标签精确等于 dsh。与弹窗场景分别覆盖 detail.tsx 两个注入点。出处：core/dashboard/static/config/config.ts:15、config/routes.ts:23、core/dashboard/static/src/pages/projects/detail.tsx:1377-1379（内嵌 HarnessBrandProvider）、components/claude-msg/DshLogo.tsx:18/24、claude-msg/MessageItem.tsx:47-58 | failed（已修正） | - | product-bug |
| hbp-web-admin-modal-dsh | 【任务 3.2·admin 车道 dsh 品牌】运维记录页点「查看处置过程」开 AdminRunModal：harness 取自处置记录（真实 API 由 run_metrics 读侧注入），弹窗内鲸鱼头像可见、标签精确等于 dsh、无 ClaudeLogo。列表经 mock_api 供给（** 前缀完整 URL glob）：夹具项目登记 fixture=True 后被跨项目聚合分支结构化排除（alert_routes.py:232/263），运维页缺省无参查询拿不到夹具记录——mock 仅顶替聚合传输层，弹窗内容仍从真实实例 /api/runs/admin-hbp-dsh-probe 拉取；真实端点契约由 api 场景hbp-api-run-meta-harness-exposure 零 mock 覆盖（非交付物端点豁免形态：两半拼合覆盖完整交付）。出处：core/dashboard/static/config/config.ts:15、config/routes.ts:37（/activities）、core/dashboard/static/src/pages/activities/index.tsx:156-159（查看处置过程按钮）与:530-532/:615-622（AdminRunModal harness）、pages/activities/components/AdminRunModal.tsx:73-75（Provider）、core/dashboard/routes/alert_routes.py:225-264（聚合分支 fixture 过滤）、core/verify_engine/browser.py:997-1110（mock_api 语义） | pass | 0/7 | - |
| hbp-web-admin-modal-fallback-claude | 【任务 3.2·admin 车道缺省回退】处置记录无 harness（存量形态：无 run_metrics 行时读侧不下发该键，admin_alerts.py:239-240 仅在指标行携带时注入）：AdminRunModal 走回退链缺省 Claude——svg[aria-label="Claude"] 可见、标签精确等于 Claude、无 dsh 图标。列表 mock 同 S8 口径（夹具项目被聚合分支结构化排除），弹窗内容从真实实例 /api/runs/admin-hbp-legacy-probe 拉取。出处：core/dashboard/static/config/config.ts:15、config/routes.ts:37、core/dashboard/static/src/pages/activities/index.tsx:251-253（ViewingRun harness 缺省 undefined）与:615-622、pages/activities/components/AdminRunModal.tsx:12-13（缺失时走回退链）、components/claude-msg/harnessBrandLogic.ts:24-29、core/dashboard/routes/alert_routes.py:225-264 | pass | 0/6 | - |
| hbp-web-session-panel-default-brand | 【任务 3.3·SessionPanel 豁免不破坏·空状态】项目页「会话接入」分面（claude 专用车道，缺省品牌即正确）：空会话空态「尚未接入会话」+「开始会话」按钮正常渲染、无控制台错误——未注入 Provider 的使用点（缺省 Claude 品牌）渲染路径未被品牌投影改造破坏。出处：core/dashboard/static/config/config.ts:15、config/routes.ts:27（/projects/:name）、core/dashboard/static/src/pages/projects/list.tsx:1566-1572（会话接入 tab）、pages/projects/components/SessionPanel.tsx:33（ClaudeMessageList 引用链）与:891-893（空态）、components/claude-msg/HarnessBrand.tsx:58-59（context 缺省值=Claude 品牌） | pass | 0/4 | - |


## 断言级豁免清单

以下失败断言被归类为非产品缺陷（不记产品 Bug），逐条列出供人工复核豁免是否掩盖真实缺陷（场景级一句话归因不足以复核）。

无非 product-bug 的被豁免失败断言。

## 本轮场景集变更

当前稳定场景集共 15 个（第 2 轮）。

- 首轮写入 15 个场景

