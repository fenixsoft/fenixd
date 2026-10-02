# 验证报告：add-session-composer

> ⚠️ 本报告由框架于 2026-09-25T06:04:01Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-09-25T06:04:01.527409+00:00

## 结论：✅ 通过（verified）

**状态：verified — 22/22 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 22/22 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 22 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 8.80M |
| 本链增量 Token（输出） | 0.11M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| web-session-tab-empty-state-compact | 空态·会话页签空态紧凑呈现（session-composer R1 场景：空态不悬空）：直接以 ?tab=session 打开无会话项目，显示「尚未接入会话」与「开始会话」紧凑顶部排布，composer 输入区不渲染。出处 core/dashboard/static/src/pages/projects/components/SessionPanel.tsx:465-473（COMPACT_NOTE_STYLE 空态）、list.tsx:1407-1411（session 页签） | pass | 0/5 | - |
| api-commands-no-session-empty | 空状态·无在飞会话返回空列表（dashboard-live-session delta R3 场景）：对全程无会话的项目 activation-showcase 请求 commands 端点，返回 200 与空 slash_commands、空 skills（前端空列表不触发菜单的契约前提）。出处 session_routes.py:233-236 | pass | 0/3 | - |
| api-files-returns-project-files | 功能正向·files 端点返回项目文件列表（dashboard-live-session delta R2 场景）：GET /api/session/files?project=scheduling-showcase 返回 200 与相对路径字符串数组（含 tracked+未忽略 untracked，夹具仓库含 pyproject.toml），条数 ≤5000。出处 session_routes.py:175-220（git ls-files + 截断） | pass | 0/5 | - |
| api-files-and-commands-unknown-project-404 | 异常路径·未注册项目返回 404（dashboard-live-session delta R2/R3 场景）：files 与 commands 端点对 registry 外的 project 参数均返回 404（_project_from_query 口径）。出处 session_routes.py:23-41（_session_context）、:216-218、:229-231 | pass | 0/3 | - |
| web-mobile-empty-state-compact | 移动端·空态紧凑不悬空（session-composer R1 场景 空态不悬空 390×844）：移动视口打开无会话项目的会话页签，「尚未接入会话」与「开始会话」在首屏可视范围内紧凑呈现（MUST NOT 视口居中悬空），composer 不渲染。出处 SessionPanel.tsx:68-76（COMPACT_NOTE_STYLE 弃用居中）、:465-473 | pass | 0/5 | - |
| cli-viewport-meta-interactive-widget | 构建产物·viewport meta 含 interactive-widget=resizes-content（session-composer R2 场景 viewport meta 声明）：fresh 构建产物 dist/index.html 中 viewport meta 恰好一条且含 interactive-widget=resizes-content（Android Chrome 键盘压缩布局视口，D4 meta 侧）。出处 core/dashboard/static/config/config.ts:36-44（metas 声明） | pass | 0/4 | - |
| cli-composer-frontend-unit-tests | 单元测试覆盖·composer 纯逻辑 node --test：草稿键名/读写/项目隔离、@ 触发与片段替换、斜杠触发与 150ms debounce、候选过滤与频次排序全量通过。出处 core/dashboard/static/tests/session-composer.test.mjs、composerLogic.ts | pass | 0/2 | - |
| cli-session-endpoint-pytest-suite | 单元测试覆盖·会话链路 pytest 全量（dashboard-live-session delta R1 场景 既有用例不回归）：tests/test_dashboard_session.py 全部通过，含本轮新增 files/commands 端点与 init 缓存用例（非 git 项目 200 空数组、5000 截断、init 覆盖与缓存消亡等浏览器无法直接驱动的分支）。出处 tests/test_dashboard_session.py:531-733（新增 12 用例） | pass | 0/2 | - |
| cli-composer-guard-source-contract | 源码契约·浏览器不可驱动的守卫分支（session-composer R2/R5 场景 IME 不误发+并发防重+键盘适配只监听 resize）：无头浏览器无法模拟 IME composing 与真实虚拟键盘，改以源码契约断言 isComposing 守卫、sendingRef 并发防重镜像、visualViewport 仅 addEventListener('resize') 三处守卫真实存在于交付源码。出处 useComposerState.ts:62-66（sendingRef/disabledRef）、:192-194（isComposing）、useVisualViewportHeight.ts:20-26 | pass | 0/4 | - |
| web-composer-mount-and-start | 功能正向·composer 挂载替换（dashboard-live-session delta R1 场景）：点击「开始会话」后输入区为 session-composer 控件（textarea+发送/停止/命令工具钮），消息流仍为 claude-msg 形态，空输入时发送钮禁用。出处 SessionPanel.tsx:338-368（handleStart）、:489-500（SessionComposer 挂载）、SessionComposer.tsx:32（placeholder 常量） | pass | 0/11 | - |
| web-at-mention-select-replace-highlight | 功能正向·@ 提及触发与选中替换（session-composer R4 场景）：键入 @pyproject 弹出文件候选，点击候选项后输入框 @ 片段替换为完整相对路径 @pyproject.toml 并以 overlay 高亮着色，候选浮层关闭。出处 useFileMentions.tsx:56-70（触发）、:124-162（selectFile 替换）、:98-122（renderInputWithMentions 着色） | pass | 0/6 | - |
| web-at-mention-top10-candidates | 边界·@ 提及候选 top10 上限（session-composer R4：最多展示 10 条）：仅键入 @（空查询）时候选浮层恰好渲染 10 条（夹具项目 git ls-files 共 223 个文件 > 10）。出处 composerLogic.ts:13（FILE_MENTION_LIMIT=10）、:169-180（filter 截取）、session_routes.py:210-220（files 端点） | pass | 0/4 | - |
| web-send-failure-restores-draft | 异常路径·发送失败还原草稿（session-composer R5 场景）：mock POST /api/session/send 返回 500（该端点非本 SPEC 交付物，mock 只为驱动前端失败分支），按 Enter 发送后输入内容还原为发送前文本并显示「发送失败」错误提示。出处 useComposerState.ts:138-146（失败还原）、SessionPanel.tsx:383-391（message.error + rethrow） | pass | 0/6 | - |
| web-draft-persists-tab-and-route-switch | 回归·草稿按 project 键持久化（session-composer R5 场景）：输入未发送文本后切到其他页签、再经路由切离又切回会话页签（等价刷新重挂载），输入框文本仍在（localStorage draft_input_<project>）。出处 useComposerState.ts:69-82（草稿读写）、chatStorage.ts:11-13（键名） | pass | 0/4 | - |
| web-enter-send-passthrough-and-clear | 功能正向·Enter 发送与 @ 原文透传（session-composer R4/R5 场景）：输入含 @pyproject.toml 的文本按 Enter 发送，POST /api/session/send 的 text 为原始文本（用户消息回显原样含 @pyproject.toml，不被 UI 改写），发送成功后输入框清空。出处 useComposerState.ts:190-200（Enter 发送）、:148-155（成功清空）、SessionPanel.tsx:372-392（handleSend→sendSessionMessage） [admin 2026-09-25 裁决修正：回显时延=完整模型往返（实测 8-12s+），原 wait 1500 过短且断言级 timeout 键经 from_dict/to_dict 往返被剥离无效，改前置双轮睡眠+selector 等待，总预算 42s] | pass | 0/4 | - |
| web-slash-menu-opens-with-cached-commands | 功能正向·斜杠补全触发（session-composer R3 场景）：在飞会话 init 缓存到达后于空输入框键入 /，补全菜单弹出，候选来自 GET /api/session/commands 的 slash_commands 与 skills。出处 useSlashCommands.ts:166-191（触发）、SessionPanel.tsx:410-433（started 后拉取+3s 补拉）、session_manager.py:371-375（init 缓存） [admin 2026-09-25 裁决修正：实测 claude CLI 的 system/init 仅随首条用户消息到达（spawn 后仅产 hook 事件，两次对照探针证实），且前端仅在 started 拉取一次+3s 补拉一次——原前提「在飞会话 init 缓存到达」在任何环境均不可满足；改依赖 web-enter-send-passthrough-and-clear 先行注入首条真实消息使缓存就绪，场景主体断言不变] | pass | 0/4 | - |
| api-commands-cached-from-live-session | 功能正向·init 到达即缓存（dashboard-live-session delta R4 场景）：会话在飞且 init 已到达时 GET /api/session/commands?project=scheduling-showcase 返回 200，slash_commands 为非空数组（与 init 事件一致），skills 为数组。出处 session_manager.py:371-375（缓存）、session_routes.py:222-241（commands 端点） | pass | 0/3 | - |
| web-mobile-composer-fullwidth-in-viewport | 移动端·输入区贴底且在首屏可视范围（session-composer R1 场景 移动端全宽贴底/390×844）：以 390×844 视口打开在飞会话的会话页签，textarea 与 composer 根节点完全在首屏可视范围内（贴底形态，无按钮挤压半宽与键盘遮挡回归入口），输入区可用。出处 SessionPanel.tsx:59-67（移动端 dvh 高度常数）、SessionComposer.tsx:133-137（fenix-composer 根节点） | pass | 0/5 | - |
| web-slash-keyboard-nav-select-no-send | 交互流程·键盘导航选中且不误发送（session-composer R3 场景）：补全菜单打开按 ↓ 高亮首项再按 Enter，输入框被替换为「/命令名 」，菜单关闭，MUST NOT 触发消息发送。出处 useSlashCommands.ts:208-232（ArrowDown/Enter 消费）、useComposerState.ts:180-204（菜单优先消费键盘） [admin 2026-09-25 裁决修正：init 缓存由 web-enter-send 首条消息引导，既有引导消息使消息区非空，「未发送」断言从 element_not_exist 改为 element_count expected=1——若键盘操作误触发发送，textarea 将被成功发送清空，仍被 text_match 断言捕获，语义不变且更强] | pass | 0/5 | - |
| web-slash-escape-closes-menu | 交互流程·Esc 关闭补全菜单（session-composer R3 键盘交互）：菜单打开时按 Esc 关闭且输入保持 / 不发送。出处 useSlashCommands.ts:234-238（Escape resetCommandMenuState） [admin 2026-09-25 裁决修正：init 缓存由 web-enter-send 首条消息引导，既有引导消息使消息区非空，「未发送」断言从 element_not_exist 改为 element_count expected=1——若键盘操作误触发发送，textarea 将被成功发送清空，仍被 text_match 断言捕获，语义不变且更强] | pass | 0/5 | - |
| web-stop-session-terminal-disable | 功能正向·停止会话终态禁用（session-composer R5 场景 会话终态禁用输入）：点击 composer「停止」按钮后 textarea 禁用、placeholder 变「会话已结束」、下方显示会话已结束提示文案。出处 SessionComposer.tsx:257-268（停止钮）、:210（disabled placeholder）、:288-290（终态提示）、SessionPanel.tsx:394-408（handleStop→stopSession） | pass | 0/6 | - |
| api-commands-cache-dies-with-session | 回归·会话终止缓存消亡（dashboard-live-session delta R4 场景）：会话被停止且 Session 移除后 GET /api/session/commands 返回 200 与两个空数组，MUST NOT 返回陈旧缓存。出处 session_routes.py:233-236（无会话分支）、session_manager.py:56-60（缓存随 Session 存亡） | pass | 0/3 | - |

## 本轮场景集变更

场景集与持久化集一致，无变更。

