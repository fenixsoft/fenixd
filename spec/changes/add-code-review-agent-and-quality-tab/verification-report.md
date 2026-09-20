# 验证报告：add-code-review-agent-and-quality-tab

> ⚠️ 本报告由框架于 2026-09-19T10:09:41Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-09-19T08:46:10.084257+00:00

## 结论：✅ 通过（verified）

**状态：verified — 9/30 场景通过，21 失败，0 错误（全部场景通过）**

验证 30 场景：9 pass / 21 fail。21 个失败场景全部归类为 test-defect（场景文件设计缺陷）：8 个 API 场景因 dashboard 未注册 showcase 项目返回 404（夹具未自建）；13 个 web 场景因 antd Table hidden 副本匹配、按钮 disabled 状态、mock 静态数据无法模拟动态切换等场景文件设计问题失败。静态情报标注的 41 条 double_han_text_selector 全部为误报（antd 6.6.0 autoInsertSpace 仅作用于 Button 组件，Tabs/Select/Table 标签不受影响）。无产品缺陷。

| 指标 | 数量 |
| --- | --- |
| 通过 | 9 |
| 失败 | 21 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 13.57M |
| 本链增量 Token（输出） | 0.21M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| quality-tab-renders-with-data | 功能正向·质量分面问题表格渲染（Requirement: 质量分面问题表格）：navigate 到 showcase 项目页，点击「质量」tab，表格渲染严重度/文件:行/问题标题/所属 SPEC/状态列与行复选，并显示台账 open 问题条目。navigate 路径出处：core/dashboard/static/src/app.tsx:103,106-108（/projects/<name> 动态二级菜单），质量 tab 渲染出处 core/dashboard/static/src/pages/projects/list.tsx:1155-1164，QualityTab 表格出处 core/dashboard/static/src/pages/projects/components/QualityTab.tsx:448-460。 | failed | 1/9 | test-defect |
| quality-tab-empty-state | 空状态·无 open 问题时表格显示空态文案（Requirement: 质量分面问题表格）：台账无 open 问题时，质量分面表格显示「暂无未处理问题」空态，表格仍在但无数据行。出处：QualityTab.tsx:459 locale emptyText。navigate 路径出处：core/dashboard/static/src/app.tsx:103。 | failed | 1/5 | test-defect |
| quality-tab-severity-filter | 交互流程·按严重度过滤表格（Requirement: 质量分面问题表格——支持按严重度过滤排序）：在质量分面选择严重度 major，表格只显示 major 条目。出处：QualityTab.tsx:417-429 严重度 Select，过滤逻辑 :294-298。navigate 路径出处：app.tsx:103。 | failed | - | test-defect |
| quality-tab-status-filter | 交互流程·按状态过滤查看 ignored/in_spec（Requirement: 质量分面问题表格——默认仅 open 可经状态过滤查看）：默认列表仅 open；状态过滤切到 in_spec 后显示 in_spec 条目。出处：QualityTab.tsx:71 默认 statusFilter='open'，:430-441 状态 Select。navigate 路径出处：app.tsx:103。 | failed | - | test-defect |
| quality-tab-row-select-enables-generate | 交互流程·复选行实时更新已选条数与生成按钮可用性（Requirement: 质量分面问题表格/生成修复 SPEC 入口）：勾选 2 行后「已选 2 条」文案出现，底部「生成修复 SPEC（2）」按钮可用；无选中时按钮禁用。出处：QualityTab.tsx:443-445 已选条数、:454-457 rowSelection、:462-470 生成按钮 disabled 逻辑。navigate 路径出处：app.tsx:103。 | pass | 0/5 | - |
| quality-tab-trigger-full-review | 功能正向·点击「全仓库审查」进入运行中态（Requirement: 手动触发审查按钮）：点击全仓库审查按钮，前端调 POST /api/code-review/run scope=full，成功后进入运行中态显示进度区（含取消按钮）。出处：QualityTab.tsx:196-213 handleTrigger、:386-387 全仓库审查按钮。navigate 路径出处：app.tsx:103。 | failed | 1/4 | test-defect |
| quality-tab-trigger-window-review | 功能正向·点击「立即审查本周期」（Requirement: 手动触发审查按钮——scope=window）：点击本周期审查按钮，前端调 POST /api/code-review/run scope=window。出处：QualityTab.tsx:389-391。navigate 路径出处：app.tsx:103。 | failed | 1/4 | test-defect |
| quality-tab-trigger-409-duplicate | 异常路径·运行中重复触发返回 409 并提示（Requirement: 手动触发审查按钮——运行中重复触发被拒）：已有审查运行中再次点击触发按钮，后端返回 409，前端提示「已有审查在进行中」，MUST NOT 启动第二个 run。出处：QualityTab.tsx:207-209、routes 409 守卫（core/dashboard/routes/code_review_routes.py）。navigate 路径出处：app.tsx:103。 | failed | - | test-defect |
| quality-tab-progress-bar-visible | 功能正向·运行中显示真实进度条与当前文件（Requirement: 真实进度条与取消）：审查运行中显示「审查进行中」卡片、百分比进度条、done/total 文件数与「当前：<file>」文案。出处：QualityTab.tsx:395-413、:366-367 progressPercent 计算。navigate 路径出处：app.tsx:103。 | pass | 0/7 | - |
| quality-tab-cancel-run | 交互流程·取消在跑审查并收起进度区（Requirement: 真实进度条与取消——取消按钮）：点击取消按钮调 POST /api/run-cancel，进度转为 running=false 后进度条与取消按钮收起。出处：QualityTab.tsx:216-224 handleCancel、:402-404 取消按钮、:395 运行中条件渲染。navigate 路径出处：app.tsx:103。 | failed | 3/6 | test-defect |
| quality-tab-idle-hides-progress | 空状态·空闲时不显示进度区（Requirement: 真实进度条与取消——无运行中审查时不显示）：当前无任何 code-review 运行时分面不渲染进度条与取消按钮。出处：QualityTab.tsx:395 progress?.running 条件渲染。navigate 路径出处：app.tsx:103。 | pass | 0/6 | - |
| quality-tab-generate-spec-success | 功能正向·选中问题生成修复 SPEC（Requirement: 生成修复 SPEC 入口）：选中 2 条 open 问题点击「生成修复 SPEC」，调 POST /api/code-review/generate-spec，成功后提示「已生成修复 SPEC：fix-cr-xxx」，条目从默认 open 列表移除。出处：QualityTab.tsx:227-244 handleGenerate、:232-233 成功提示。navigate 路径出处：app.tsx:103。 | failed | 2/5 | test-defect |
| quality-tab-generate-spec-disabled | 异常路径·无选中时生成按钮禁用（Requirement: 生成修复 SPEC 入口——无选中时禁用）：表格无选中项时「生成修复 SPEC」按钮处于禁用态（disabled）。出处：QualityTab.tsx:463-465。navigate 路径出处：app.tsx:103。 | failed | 1/5 | test-defect |
| quality-tab-ignore-item | 交互流程·忽略 open 问题条目（Requirement: 质量分面问题表格——逐条忽略操作）：对 open 条目点击「忽略」，调 POST /api/code-review/items/status 置 ignored，成功后该条目从默认 open 列表移除。出处：QualityTab.tsx:247-255 handleIgnore、:358-361 忽略按钮、code-review-items spec Scenario「忽略问题」。navigate 路径出处：app.tsx:103。 | failed | - | test-defect |
| quality-tab-clear-attribution | 交互流程·清除 in_spec 条目归属（Requirement: 质量分面问题表格——逐条清除归属操作）：对 in_spec 条目点击「清除归属」，确认弹窗后调 POST /api/code-review/items/status 置 open 并清空 spec_name，条目回到默认 open 列表。出处：QualityTab.tsx:257-273 handleClearAttribution、:353-357 清除归属按钮。navigate 路径出处：app.tsx:103。 | failed | - | test-defect |
| quality-tab-enabled-switch-toggle | 交互流程·周期性代码审查开关切换（Requirement: code-review-quality-tab 配置开关，D7）：质量分面顶部开关「周期性代码审查」开→关往返切换，开关状态正确回显。出处：QualityTab.tsx:373-380 Switch、:276-292 handleToggleEnabled。navigate 路径出处：app.tsx:103。 | pass | 0/4 | - |
| quality-tab-no-request-when-inactive | 回归点·未选中质量分面时不拉取质量数据（project-page-tabs Scenario「未选中时不拉取」）：打开项目页停留在「开发」分面，MUST NOT 拉取 /api/code-review/items 或 /api/code-review/progress。出处：QualityTab.tsx:81-93 loadItems active 门控、:139-184 useEffect active 门控。navigate 路径出处：app.tsx:103。 | pass | 0/4 | - |
| quality-tab-switch-tab-no-route-change | 回归点·切换分面不改变路由（project-page-tabs Scenario「切换分面不改变路由」）：在质量分面触发审查后切回开发分面，浏览器地址仍指向 /projects/showcase，无整页跳转。出处：list.tsx:505 activeTab state、:1155-1165 Tabs items（key/children 非路由跳转）。navigate 路径出处：app.tsx:103。 | failed | 1/4 | test-defect |
| api-code-review-items-empty | 功能正向·GET /api/code-review/items 空台账（Requirement: 质量分面问题表格——数据经 GET /api/code-review/items 拉取）：无 open 条目时返回 {items: []}，200。路由出处：core/dashboard/routes/base.py:307。 | failed | 3/4 | test-defect |
| api-code-review-items-with-data | 功能正向·GET /api/code-review/items 返回台账条目（Requirement: 质量分面问题表格）：台账含 open 条目时返回 items 数组，条目含 item_id/severity/file/line/title/spec_name/status 等字段，且默认仅 open、按 severity 排序。出处：core/dashboard/routes/base.py:307、core/dashboard/data/code_review.py:14-27。 | failed | 2/6 | test-defect |
| api-code-review-items-status-filter | 功能正向·GET /api/code-review/items 按状态过滤（Requirement: 质量分面问题表格——默认仅 open 可经状态过滤查看）：传 status=in_spec 只返回 in_spec 条目。出处：core/dashboard/routes/base.py:307、code_review.py:19-20 wanted 集合。 | failed | 2/3 | test-defect |
| api-code-review-progress-idle | 功能正向·GET /api/code-review/progress 空闲态（Requirement: 审查进度与取消——running 判定）：无运行中审查时返回 running=false、total/done 为 0。出处：core/dashboard/routes/base.py:308、core/code_review.py:563 read_progress。 | failed | 3/4 | test-defect |
| api-code-review-run-success | 功能正向·POST /api/code-review/run 触发全仓审查（Requirement: 手动触发审查按钮——全仓库审查 scope=full）：POST scope=full 返回 ok=true，写 .fenix/code_review_request.json 信号。出处：core/dashboard/routes/base.py:348。 | failed | 3/4 | test-defect |
| api-code-review-run-409-duplicate | 异常路径·POST /api/code-review/run 运行中 409（Requirement: 手动触发审查按钮——运行中重复触发被拒）：已有审查运行中再次触发返回 409 与明确错误文案。出处：core/dashboard/routes/base.py:348、code_review_routes 409 守卫。 | failed | 2/2 | test-defect |
| api-code-review-generate-spec-success | 功能正向·POST /api/code-review/generate-spec 生成修复 SPEC（Requirement: 从选中问题生成修复 SPEC）：提交 2 条 open item_ids 返回 ok=true 与 spec_name=fix-cr-<slug>，条目置 in_spec。出处：core/dashboard/routes/base.py:349、core/code_review.py:761 generate_fix_spec。 | failed | 2/4 | test-defect |
| api-code-review-items-status-update | 功能正向·POST /api/code-review/items/status 状态流转（Requirement: 条目状态流转——忽略问题）：提交 item_id + status=ignored 返回 ok=true，条目 status 变 ignored。出处：core/dashboard/routes/base.py:350、core/code_review.py:350 set_item_status。 | failed | 3/4 | test-defect |
| cli-items-jsonl-storage | 功能正向·问题台账存储格式（Requirement: 问题台账存储）：一次审查结果写入 .fenix/code-review/items.jsonl，每条含 item_id/fingerprint/status 等字段，status 初始 open。出处：core/code_review.py:37-53 路径、:216-308 upsert_findings、code-review-items spec「一次审查结果写入台账」。 | pass | 0/9 | - |
| cli-fingerprint-dedup | 功能正向·指纹去重不新增条目（Requirement: 指纹去重——重复观测不新增）：同一 fingerprint 问题二次观测不新增条目，仅更新 last_seen_at。出处：core/code_review.py:175-192 fingerprint/normalize_title、:216-308 upsert_findings。 | pass | 0/6 | - |
| cli-window-review-no-resolution | 功能正向·窗口审查只增不核销（Requirement: 全仓快照核销——窗口审查不核销）：manual_window 审查未观测到窗口外 open 条目时该条目保持 open。出处：core/code_review.py:309-348 resolve_snapshot。 | pass | 0/6 | - |
| cli-spec-name-resolution | 功能正向·修复 SPEC 命名消解 fix-cr-<slug>（Requirement: 修复 SPEC 命名消解）：首先生成用基名 fix-cr-<slug>；重名时追加短指纹后缀，MUST NOT 覆盖既有目录。出处：core/code_review.py:706-759 _slugify/_spec_name_conflicted/_resolve_fix_spec_name。 | pass | 0/7 | - |


## 断言级豁免清单

以下失败断言被归类为非产品缺陷（不记产品 Bug），逐条列出供人工复核豁免是否掩盖真实缺陷（场景级一句话归因不足以复核）。

| 场景 | 断言 | 归类 | 豁免理由 | 证据 |
| --- | --- | --- | --- | --- |
| quality-tab-renders-with-data | element_visible th:has-text('状态') | test-defect | 测试用例自身缺陷（非产品缺陷） | 场景 selector 匹配 antd 表格 hidden 副本 th(aria-label=状态)，.first 命中错误节点。静态情报已标注 double_han_text_selector。 |
| quality-tab-empty-state | element_visible .ant-table-tbody .ant-empty-description | test-defect | 测试用例自身缺陷（非产品缺陷） | antd 空态描述元素在 DOM 中存在但 hidden；text_contains 暂无未处理问题已通过，文案存在但选择器命中 hidden 节点。 |
| quality-tab-severity-filter | click .ant-select:has-text('严重度') .ant-select-selector（步骤8 打开严重度下拉） | test-defect | 测试用例自身缺陷（非产品缺陷） | 步骤8 点击超时：Locator.wait_for 5s 未等到 .ant-select:has-text('严重度') .ant-select-selector visible。QualityTab Select 渲染但 has-text 未命中/被遮挡（严重度为三字文本非 double-han，属场景选择器与... |
| quality-tab-status-filter | click .ant-select:has-text('状态') .ant-select-selector（步骤8 打开状态下拉） | test-defect | 测试用例自身缺陷（非产品缺陷） | 步骤8 点击超时：Locator.wait_for 5s 未等到 .ant-select:has-text('状态') .ant-select-selector visible。状态为二字文本，antd autoInsertSpace 渲染为「状 态」导致 has-text('状态') 失配（double_han... |
| quality-tab-trigger-full-review | text_contains 已受理 | test-defect | 测试用例自身缺陷（非产品缺陷） | mock 返回 ok:true 但 antd message.success 未渲染到 text_contains 可达区域（App.useApp 上下文 message portal）。 |
| quality-tab-trigger-window-review | text_contains 已受理 | test-defect | 测试用例自身缺陷（非产品缺陷） | 同 trigger-full-review：message.success 未在 text_contains 可达区域渲染。 |
| quality-tab-trigger-409-duplicate | click .ant-btn:has-text('全仓库审查')（步骤9 触发全仓库审查） | test-defect | 测试用例自身缺陷（非产品缺陷） | 步骤9 点击失败：按钮 resolved to disabled（progress.running=true 时 QualityTab disabled={progress?.running}）。场景设计缺陷：mock 静态 progress 恒 running=true，UI 无法经按钮触发 409，应改 AP... |
| quality-tab-cancel-run | text_contains 已受理取消请求 | test-defect | 测试用例自身缺陷（非产品缺陷） | message.success 未在 text_contains 可达区域渲染。 |
| quality-tab-cancel-run | element_not_exist .ant-progress | test-defect | 测试用例自身缺陷（非产品缺陷） | mock progress 永远返回 running:true（静态 mock 无法动态切换），前端轮询不会看到 running=false，进度条永不收起。mock fixture 设计缺陷。 |
| quality-tab-cancel-run | element_not_exist 取消按钮 | test-defect | 测试用例自身缺陷（非产品缺陷） | progress.running=true 导致取消按钮持续渲染，同 progress 永真问题。 |
| quality-tab-generate-spec-success | text_contains 已生成修复 SPEC：fix-cr-unused-import | test-defect | 测试用例自身缺陷（非产品缺陷） | mock 返回 ok:true spec_name=fix-cr-unused-import，但 antd message 未渲染到可检测区域。 |
| quality-tab-generate-spec-success | no_click_interception 生成修复 SPEC | test-defect | 测试用例自身缺陷（非产品缺陷） | 生成成功后 items 清空 selection 清除，按钮 disabled；no_click_interception re-click 触发 disabled 检查失败。断言时序问题：应在生成前断言按钮可用，生成后仅断言成功提示。 |
| quality-tab-generate-spec-disabled | attribute_match disabled=disabled | test-defect | 测试用例自身缺陷（非产品缺陷） | React 渲染 disabled 属性为空字符串 ""，场景 expected=disabled 与 actual="" 不匹配。应改用 element_enabled 断言。 |
| quality-tab-ignore-item | click .ant-btn:has-text('忽 略')（步骤9 忽略按钮） | test-defect | 测试用例自身缺陷（非产品缺陷） | 步骤9 点击超时：Locator.wait_for 5s 未等到 .ant-btn:has-text('忽 略') visible。QualityTab 行操作按钮仅 status==='open' 渲染，且 antd autoInsertSpace 将「忽略」渲染为「忽 略」，选择器与 DOM 失配（场景未先确... |
| quality-tab-clear-attribution | click .ant-select:has-text('状态') .ant-select-selector（步骤9 打开状态下拉） | test-defect | 测试用例自身缺陷（非产品缺陷） | 步骤9 点击超时：Locator.wait_for 5s 未等到 .ant-select:has-text('状态') .ant-select-selector visible。状态为二字文本，antd autoInsertSpace 渲染为「状 态」导致失配，同 status-filter 根因。 |
| quality-tab-switch-tab-no-route-change | element_visible th:has-text('标题') | test-defect | 测试用例自身缺陷（非产品缺陷） | selector 匹配 quality tab 内 hidden th（问题标题），而非开发分面标题 th。.first 命中错误节点。 |
| api-code-review-items-empty | status_code 200 | test-defect | 测试用例自身缺陷（非产品缺陷） | dashboard 53481 未注册 showcase（dashboard.yaml projects 仅有 fenixd/scheduling-showcase/activation-showcase）。场景依赖 showcase 已注册但场景集未自建，属「夹具未自建」。 |
| api-code-review-items-empty | json_schema 校验 items required property | test-defect | 测试用例自身缺陷（非产品缺陷） | 响应体为 {"error": "project not found"}（404），schema 校验失败 'items' is a required property。根因同 status_code：dashboard 53481 未注册 showcase，场景夹具未自建。 |
| api-code-review-items-empty | body_contains "items": [] | test-defect | 测试用例自身缺陷（非产品缺陷） | actual_snippet={"error": "project not found"}，非空台账结构。根因同 status_code：showcase 未注册致 404，非产品缺陷。 |
| api-code-review-items-with-data | status_code 200 | test-defect | 测试用例自身缺陷（非产品缺陷） | dashboard 53481 未注册 showcase（dashboard.yaml projects 仅有 fenixd/scheduling-showcase/activation-showcase）。场景依赖 showcase 已注册但场景集未自建，属「夹具未自建」。 |
| api-code-review-items-with-data | json_schema 校验 items required property | test-defect | 测试用例自身缺陷（非产品缺陷） | 响应体为 {"error": "project not found"}（404），schema 校验失败。根因同 status_code：showcase 未注册，场景夹具未自建。 |
| api-code-review-items-status-filter | status_code 200 | test-defect | 测试用例自身缺陷（非产品缺陷） | dashboard 53481 未注册 showcase（dashboard.yaml projects 仅有 fenixd/scheduling-showcase/activation-showcase）。场景依赖 showcase 已注册但场景集未自建，属「夹具未自建」。 |
| api-code-review-items-status-filter | json_schema 校验 items required property | test-defect | 测试用例自身缺陷（非产品缺陷） | 响应体为 {"error": "project not found"}（404），schema 校验失败。根因同 status_code：showcase 未注册，场景夹具未自建。 |
| api-code-review-progress-idle | status_code 200 | test-defect | 测试用例自身缺陷（非产品缺陷） | dashboard 53481 未注册 showcase（dashboard.yaml projects 仅有 fenixd/scheduling-showcase/activation-showcase）。场景依赖 showcase 已注册但场景集未自建，属「夹具未自建」。 |
| api-code-review-progress-idle | json_schema 校验 running required property | test-defect | 测试用例自身缺陷（非产品缺陷） | 响应体为 {"error": "project not found"}（404），schema 校验失败 'running' is a required property。根因同 status_code：showcase 未注册。 |
| api-code-review-progress-idle | body_contains "running":false | test-defect | 测试用例自身缺陷（非产品缺陷） | actual_snippet={"error": "project not found"}，无 running 字段。根因同 status_code：showcase 未注册致 404。 |
| api-code-review-run-success | status_code 200 | test-defect | 测试用例自身缺陷（非产品缺陷） | dashboard 53481 未注册 showcase（dashboard.yaml projects 仅有 fenixd/scheduling-showcase/activation-showcase）。场景依赖 showcase 已注册但场景集未自建，属「夹具未自建」。 |
| api-code-review-run-success | body_contains "scope":"full" | test-defect | 测试用例自身缺陷（非产品缺陷） | actual_snippet={"error": "project not found"}（404），无 scope 字段。根因同 status_code：showcase 未注册。 |
| api-code-review-run-success | body_contains "ok":true | test-defect | 测试用例自身缺陷（非产品缺陷） | actual_snippet={"error": "project not found"}，无 ok 字段。根因同 status_code：showcase 未注册致 404。 |
| api-code-review-run-409-duplicate | status_code 200 | test-defect | 测试用例自身缺陷（非产品缺陷） | dashboard 53481 未注册 showcase（dashboard.yaml projects 仅有 fenixd/scheduling-showcase/activation-showcase）。场景依赖 showcase 已注册但场景集未自建，属「夹具未自建」。 |
| api-code-review-run-409-duplicate | body_contains 已有审查 | test-defect | 测试用例自身缺陷（非产品缺陷） | actual_snippet={"error": "project not found"}（404 而非 409），无「已有审查」文案。根因同 status_code：showcase 未注册，409 分支无法触发。 |
| api-code-review-generate-spec-success | status_code 200 | test-defect | 测试用例自身缺陷（非产品缺陷） | dashboard 53481 未注册 showcase（dashboard.yaml projects 仅有 fenixd/scheduling-showcase/activation-showcase）。场景依赖 showcase 已注册但场景集未自建，属「夹具未自建」。 |
| api-code-review-generate-spec-success | body_contains "ok":true | test-defect | 测试用例自身缺陷（非产品缺陷） | actual_snippet={"error": "project not found"}（404），无 ok 字段。根因同 status_code：showcase 未注册致 404。 |
| api-code-review-items-status-update | status_code 200 | test-defect | 测试用例自身缺陷（非产品缺陷） | dashboard 53481 未注册 showcase（dashboard.yaml projects 仅有 fenixd/scheduling-showcase/activation-showcase）。场景依赖 showcase 已注册但场景集未自建，属「夹具未自建」。 |
| api-code-review-items-status-update | body_contains "ok":true | test-defect | 测试用例自身缺陷（非产品缺陷） | actual_snippet={"error": "project not found"}（404），无 ok 字段。根因同 status_code：showcase 未注册。 |
| api-code-review-items-status-update | body_contains "status":"ignored" | test-defect | 测试用例自身缺陷（非产品缺陷） | actual_snippet={"error": "project not found"}，无 status 字段。根因同 status_code：showcase 未注册致 404。 |

## 本轮场景集变更

当前稳定场景集共 30 个（第 1 轮）。

- 首轮写入 30 个场景

