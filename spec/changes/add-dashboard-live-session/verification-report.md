# 验证报告：add-dashboard-live-session

> ⚠️ 本报告由框架于 2026-09-18T13:27:30Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-09-18T12:35:07.426824+00:00

## 结论：❌ 未通过（Bug Found）

**状态：bug-found — 15/19 场景通过，4 失败，0 错误（1 个真实产品 Bug）**

19 场景 15 通过 4 失败。1) product-bug（1 个，跨 2 场景）：SessionModal afterHello 无条件注册 session watch，无会话项目打开 Modal 必现 404 + console.error。2) web-start-session flaky：点击「开始会话」后等 textarea 超时（5s），复现 0.47s 通过，属时序抖动非产品缺陷。3) web-stop-session 场景文件缺陷已原地修复：click 停止会话后缺等待异步 stop 完成步骤，已在 test_scenarios.json 补 wait .ant-modal textarea[disabled]（待框架重跑复核）

| 指标 | 数量 |
| --- | --- |
| 通过 | 15 |
| 失败 | 4 |
| 错误 | 0 |
| 产品 Bug | 1 |
| 本链增量 Token（输入） | 30.76M |
| 本链增量 Token（输出） | 0.36M |


## 真实产品 Bug

### BUG-01（severity=minor）· no_console_error

- 关联场景：web-modal-title-project、web-open-modal-empty-state
- 描述：打开会话 Modal（项目无会话、空态）时控制台产生确定性错误：POST /api/session/watch 404（session not found）+ 前端 console.error("Failed to register session watch")，no_console_error 断言失败
- 根因：core/dashboard/static/src/pages/projects/components/SessionModal.tsx:122-127 afterHello 在 SSE hello 分支无条件调 registerSessionWatch(project, cid)，未先校验 sessionIdRef.current 是否存在；服务端 core/dashboard/routes/session_routes.py:163-166 对无会话项目返回 404，前端 catch 块 console.error。项目首次打开 Modal（未启动会话）即必然触发
- 证据（场景 web-modal-title-project 结构化证据，引用）：
  - failed_assertions: [{"type": "no_console_error", "layer": 3, "expected": "无控制台错误", "actual": "[error] Failed to load resource: 404; [error] Failed to register session watch: Error: session not found"}]
  - screenshots: ["/root/fenixd/.fenix/verify-progress/add-dashboard-live-session/screenshots/web-modal-title-project_assert_fail.png"]
  - first_failed_step: 步骤4: 等待 .ant-modal-title 后 no_console_error 断言发现 console.error（session 不存在时 afterHello 仍调 registerSessionWatch）


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| api-session-get-readonly-no-session | 功能正向·回读端点不隐式启动进程（spec R1 scenario）：GET /api/session?project=scheduling-showcase 返回 session:null，MUST NOT 触发会话创建。连续两次 GET 均返回 null，证明只读语义。出处：core/dashboard/routes/session_routes.py:45-77（get 端点只读逻辑） | pass | 0/4 | - |
| api-session-start-unknown-project | 异常路径·不存在的项目启动会话返回 404（spec R1 scenario）：POST /api/session/start?project=__nonexistent__ 返回 404，MUST NOT 启动任何进程。出处：core/dashboard/routes/session_routes.py:22-24（项目校验） | pass | 0/1 | - |
| api-session-send-no-session | 异常路径·向不存在的会话发送返回 404（spec R2 scenario）：POST /api/session/send?project=__nonexistent__ 返回 404，MUST NOT 造成服务端异常。出处：core/dashboard/routes/session_routes.py:95-98（会话存在性校验） | pass | 0/1 | - |
| web-entry-button-visible | 功能正向·入口按钮位置（spec R5 scenario）：项目页标题栏显示「接入会话」按钮，位于「共 N 个 SPEC」文案之后且靠右对齐（marginLeft:auto）。出处：core/dashboard/static/src/pages/projects/list.tsx:1027-1038（D7 入口按钮实现） | pass | 0/4 | - |
| web-spec-menu-no-session | 回归·操作菜单不含会话入口（spec R5 scenario）：展开任一 SPEC 行的「更多」菜单，菜单中 MUST NOT 出现「接入会话」项（会话是项目级语义，不与具体 SPEC 绑定）。出处：core/dashboard/static/src/pages/projects/list.tsx:1003-1009（更多菜单项定义不含会话） | pass | 0/4 | - |
| web-modal-title-project | 功能正向·Modal 标题含项目名：打开会话 Modal 后，标题显示「接入会话 · scheduling-showcase · 与 Claude 自由对话（不绑定 SPEC）」。出处：core/dashboard/static/src/pages/projects/components/SessionModal.tsx:259-267（Modal title） | failed（已修正） | 1/5 | product-bug |
| web-open-modal-empty-state | 功能正向·打开会话 Modal 显示空态（spec R5）：点击「接入会话」按钮后 Modal 打开，显示「尚未接入会话」文案与「开始会话」按钮（会话尚未启动时的空态）。出处：core/dashboard/static/src/pages/projects/components/SessionModal.tsx:282-288（空态渲染） | failed（已修正） | 1/5 | product-bug |
| cli-pytest-sessions | 单元测试覆盖·session_manager + session_routes 全量 pytest：运行 tests/test_dashboard_session.py -v，断言全部测试 PASSED，覆盖：复用语义（test_reuse_same_handle）、hook 噪音过滤（test_hook_noise_filtered）、空文本拒绝（test_send_blank_400）、SSE watch 注册注销（test_watch_post_delete）、真实进程两轮往返（test_two_rounds_assistant_events）。出处：tests/test_dashboard_session.py（5.1-5.4 测试文件） | pass | 0/6 | - |
| cli-frontend-session-events | 前端单元测试覆盖·runEvents 会话终态分支：运行 core/dashboard/static/tests/sessionEvents.test.mjs，断言 session_ended 三种 reason 渲染为明确中文系统行、isReplay 回显渲染为文本行、既有 run 事件不回归。出处：core/dashboard/static/tests/sessionEvents.test.mjs（5.5 测试文件） | pass | 0/3 | - |
| api-session-start-reuse | 功能正向·创建会话与复用语义（spec R1）：首次 POST /api/session/start 返回 session ID；同项目再次 start 返回 session ID（复用），MUST NOT 新建进程。出处：core/dashboard/session_manager.py:112-116（复用逻辑）、core/dashboard/routes/session_routes.py:15-43（start 端点） | pass | 0/4 | - |
| web-start-session | 功能正向·点击「开始会话」启动进程（spec R5）：在 Modal 空态点击「开始会话」按钮后，会话进程启动（POST /api/session/start 被调用），Modal 转为消息区+输入区界面，输入框与发送按钮可用。出处：core/dashboard/static/src/pages/projects/components/SessionModal.tsx:285（按钮 onClick）、core/dashboard/static/src/pages/projects/components/SessionModal.tsx:290-329（已启动态渲染） | fail | - | flaky |
| api-session-send-blank-rejected | 异常路径·空/空白文本被拒绝（spec R2 scenario）：POST /api/session/send 的 text 为空字符串或纯空白时返回 400，MUST NOT 向 stdin 写入。出处：core/dashboard/routes/session_routes.py:79-118（send 端点空值校验） | pass | 0/2 | - |
| api-session-watch | 功能正向·SSE 订阅注册与注销（spec R3）：POST /api/session/watch 注册成功返回 200；DELETE 同路径注销成功返回 200。出处：core/dashboard/routes/session_routes.py:148-178（watch 端点） | pass | 0/2 | - |
| web-send-user-message | 功能正向·发送一轮用户消息（spec R2/R5 scenario）：在已启动的会话中输入文本并点击「发送」，用户消息立即出现在消息流中（--replay-user-messages 回显 isReplay user 事件），输入框清空。出处：core/dashboard/static/src/pages/projects/components/SessionModal.tsx:225-241（handleSend）、core/dashboard/static/src/pages/projects/components/SessionModal.tsx:302-315（输入区） | pass | 0/4 | - |
| api-session-stop-idempotent | 功能正向·终止会话幂等（spec R4 scenario）：有会话时 POST /api/session/stop 返回 200 并终止进程；无会话时 POST /api/session/stop 返回 200（幂等）。出处：core/dashboard/routes/session_routes.py:120-147（stop 端点幂等逻辑）、core/dashboard/session_manager.py:191-201（stop 内部） | pass | 0/2 | - |
| web-send-assistant-roundtrip | 功能正向·完整对话往返（spec R2 scenario）：发送提取数字问题「请提取这串字符里的数字并回复：fenix-verify-42 里的数字是多少？只回复数字」后，消息流中依次出现用户消息和 assistant 回复（Markdown 渲染），assistant 回复内容应含「42」（答案 token 独特，避免命中缓冲内旧 assistant 消息）。等待 LLM 推理完成。出处：core/dashboard/static/src/pages/projects/components/SessionModal.tsx:225-241（发送）、core/dashboard/static/src/components/claude-msg/ClaudeMessageList.tsx（消息渲染） | pass | 0/3 | - |
| web-reopen-modal-reconnect | 交互流程·关闭重开 Modal 接回会话（spec R3 scenario）：会话已启动后关闭 Modal，重新打开后会话接回（不重启进程），消息区显示之前的事件缓冲（GET 全量回读）。出处：core/dashboard/static/src/pages/projects/components/SessionModal.tsx:82-183（onOpen 拉全量+注册 watch）、core/dashboard/static/src/pages/projects/components/SessionModal.tsx:186-201（onClose 注销 watch） | pass | 0/5 | - |
| web-stop-session | 功能正向·停止会话显示终态（spec R4/R5 scenario）：在已启动会话中点击「停止会话」按钮后，输入区禁用（textarea disabled），底部显示「会话已结束，如需新会话请关闭后重新打开。」提示文案。出处：core/dashboard/static/src/pages/projects/components/SessionModal.tsx:243-250（handleStop）、core/dashboard/static/src/pages/projects/components/SessionModal.tsx:334-338（终态提示） | failed（已修正） | 3/5 | test-defect |
| cli-session-no-fenix-artifacts | 回归·会话不写 run 产物（spec R6 scenario）：通过 API 完成 start→send→stop 流程后，scheduling-showcase/.fenix/runs/ 下无新增文件，.fenix/STATE.md 内容不变。出处：core/dashboard/session_manager.py:103-150（start）、core/dashboard/routes/session_routes.py:79-118（send）、spec R6 requirement | pass | 0/3 | - |


## 断言级豁免清单

以下失败断言被归类为非产品缺陷（不记产品 Bug），逐条列出供人工复核豁免是否掩盖真实缺陷（场景级一句话归因不足以复核）。

| 场景 | 断言 | 归类 | 豁免理由 | 证据 |
| --- | --- | --- | --- | --- |
| web-start-session | wait .ant-modal textarea 操作（步骤6：点击「开始会话」后等待输入框可见） | flaky | 不稳定复现（非产品缺陷） | 步骤6 wait 超时 5000ms，断言未执行（assertion_results 为空）；复现已证明 0.47s 通过，后续 web-send-user-message 确认同一流程 textarea 可见，属时序抖动 |
| web-stop-session | text_contains .ant-modal '会话已结束，如需新会话请关闭后重新打开' 终态提示文案 | test-defect | 测试用例自身缺陷（非产品缺陷） | 场景文件缺陷（断言时序）：click 停止会话后无等待终态步骤；stop POST 同步阻塞服务端进程终止，setEnded 异步完成，断言先于终态渲染；已原地修复 test_scenarios.json 补 wait .ant-modal textarea[disabled] |
| web-stop-session | attribute_match .ant-modal textarea disabled expected '' actual null 输入框已禁用 | test-defect | 测试用例自身缺陷（非产品缺陷） | 同断言时序根因：disabled={ended\|\|sending}，ended 未置位；修复后由 wait textarea[disabled] 等终态 |
| web-stop-session | attribute_match .ant-modal textarea placeholder '会话已结束' 输入框 placeholder 已结束 | test-defect | 测试用例自身缺陷（非产品缺陷） | placeholder={ended?'会话已结束':'输入消息…'}，ended 未置位；同根因，修复同上 |

## 本轮场景集变更

当前稳定场景集共 19 个（第 1 轮）。

- 首轮写入 19 个场景

